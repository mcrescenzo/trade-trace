"""Deterministic read-only strategy health report.

Aggregates local process-health signals across strategies. This report does not
rank performance, fetch external data, or provide trading advice.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from trade_trace.contracts.report_filter import STRATEGY_NONE_SENTINEL, ReportFilter
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import _resolve_strategy_filter, process_filter
from trade_trace.storage.database import read_snapshot
from trade_trace.timestamps import (
    parse_report_timestamp_strict_utc_naive_as_utc as _parse_ts,
)
from trade_trace.tools._helpers import now_iso

REPORT_NAME = "report.strategy_health"
REPORT_FILTER_SUPPORT = frozenset({
    "actors.actor_id",
    "actors.agent_id",
    "actors.model_id",
    "actors.environment",
    "actors.run_id",
    "strategy.strategy_id",
    "time_window.created_at_gte",
    "time_window.created_at_lt",
})
DEFAULT_HEALTH_MIN_SAMPLE = 5


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _id_section(ids: list[str]) -> dict[str, Any]:
    return {"count": len(ids), "record_ids": ids}


def _extend_filter_sql(alias: str, rf: ReportFilter, params: list[Any], *, time_col: str = "created_at") -> str:
    clauses: list[str] = []
    actors = rf.actors
    for field in ("actor_id", "agent_id", "model_id", "environment", "run_id"):
        values = getattr(actors, field)
        if values:
            clauses.append(f"{alias}.{field} IN ({','.join('?' for _ in values)})")
            params.extend(values)
    tw = rf.time_window
    if tw.created_at_gte:
        clauses.append(f"{alias}.{time_col} >= ?")
        params.append(tw.created_at_gte)
    if tw.created_at_lt:
        clauses.append(f"{alias}.{time_col} < ?")
        params.append(tw.created_at_lt)
    if alias == "d":
        if tw.decision_at_gte:
            clauses.append("d.created_at >= ?")
            params.append(tw.decision_at_gte)
        if tw.decision_at_lt:
            clauses.append("d.created_at < ?")
            params.append(tw.decision_at_lt)
    return "".join(f" AND {clause}" for clause in clauses)


def _partition_ids(
    conn: sqlite3.Connection, sql: str, params: list[Any]
) -> dict[str, list[str]]:
    """Run one batch query and partition its `(strategy_id, record_id)` rows.

    Each query selects ``strategy_id`` as the first column and the record id
    as the second, ordered so that rows for a given strategy already arrive in
    the report's required within-strategy order. Appending into a list per
    strategy preserves that SQL ordering, so the partitioned output is
    identical to the previous per-strategy queries that filtered on a single
    ``strategy_id``.
    """

    out: dict[str, list[str]] = defaultdict(list)
    for sid, record_id in conn.execute(sql, tuple(params)).fetchall():
        out[sid].append(record_id)
    return out


def _strategy_filter_sql(alias: str, strategy_ids: list[str], params: list[Any]) -> str:
    """Append an ``alias.strategy_id IN (...)`` clause scoping to ``strategy_ids``.

    Callers only invoke this with a non-empty list (the empty-scope case is
    short-circuited in :func:`_batch_signals`), so the placeholder list is
    always non-empty and SQLite never sees an empty ``IN ()``.
    """

    placeholders = ",".join("?" for _ in strategy_ids)
    params.extend(strategy_ids)
    return f" AND {alias}.strategy_id IN ({placeholders})"


def _batch_signals(
    conn: sqlite3.Connection,
    strategy_ids: list[str],
    rf: ReportFilter,
    *,
    as_of: str,
) -> dict[str, dict[str, list[str]]]:
    """Compute every per-strategy signal in a small constant number of queries.

    Replaces the previous ``O(strategies * 5)`` fan-out: each of the five
    signal queries runs once across all in-scope strategies (scoped with a
    single ``strategy_id IN (...)`` clause) and is partitioned in Python by
    strategy. Query count is now exactly five regardless of strategy count.
    All queries run inside the caller's pinned ``read_snapshot`` view.
    """

    empty: dict[str, dict[str, list[str]]] = {
        "decisions": {},
        "due": {},
        "missing_source_thesis": {},
        "open_forecast": {},
        "override": {},
    }
    if not strategy_ids:
        return empty

    params: list[Any] = []
    scope = _strategy_filter_sql("d", strategy_ids, params)
    decision_filter = _extend_filter_sql("d", rf, params)
    decisions = _partition_ids(conn, f"SELECT d.strategy_id, d.id FROM decisions d WHERE 1=1{scope}{decision_filter} ORDER BY d.strategy_id, d.created_at, d.id", params)

    params = [as_of]
    scope = _strategy_filter_sql("d", strategy_ids, params)
    due = _partition_ids(conn, f"""
        SELECT d.strategy_id, d.id FROM decisions d
        WHERE d.type IN ('watch','hold','review')
          AND d.review_by IS NOT NULL AND d.review_by <= ?{scope}
          {_extend_filter_sql('d', rf, params)}
        ORDER BY d.strategy_id, d.review_by, d.created_at, d.id
    """, params)

    params = []
    scope = _strategy_filter_sql("t", strategy_ids, params)
    thesis_filter = _extend_filter_sql("t", rf, params)
    missing_source_thesis = _partition_ids(conn, f"""
        SELECT t.strategy_id, t.id FROM theses t
        WHERE NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE ((e.source_kind = 'thesis' AND e.source_id = t.id)
                OR (e.target_kind = 'thesis' AND e.target_id = t.id))
              AND (e.source_kind = 'source' OR e.target_kind = 'source')
        ){scope}{thesis_filter}
        ORDER BY t.strategy_id, t.created_at, t.id
    """, params)

    params = []
    scope = _strategy_filter_sql("t", strategy_ids, params)
    forecast_filter = _extend_filter_sql("f", rf, params)
    open_forecast = _partition_ids(conn, f"""
        SELECT t.strategy_id, f.id FROM forecasts f JOIN theses t ON t.id = f.thesis_id
        WHERE f.scoring_state IN ('pending','failed')
          AND f.invalidated_at IS NULL{scope}{forecast_filter}
        ORDER BY t.strategy_id, f.created_at, f.id
    """, params)

    params = []
    scope = _strategy_filter_sql("d", strategy_ids, params)
    override = _partition_ids(conn, f"""
        SELECT DISTINCT d.strategy_id, d.id FROM decisions d
        JOIN decision_playbook_rules dpr ON dpr.decision_id = d.id
        WHERE dpr.status = 'overridden'{scope}{_extend_filter_sql('d', rf, params)}
        ORDER BY d.strategy_id, d.created_at, d.id
    """, params)

    return {
        "decisions": decisions,
        "due": due,
        "missing_source_thesis": missing_source_thesis,
        "open_forecast": open_forecast,
        "override": override,
    }


def _strategy_group(
    row: sqlite3.Row | tuple[Any, ...],
    rf: ReportFilter,
    signals: dict[str, dict[str, list[str]]],
    *,
    min_sample: int,
) -> dict[str, Any]:
    sid, slug, name, status = row[0], row[1], row[2], row[3]

    decision_ids = signals["decisions"].get(sid, [])
    due_ids = signals["due"].get(sid, [])
    missing_source_thesis_ids = signals["missing_source_thesis"].get(sid, [])
    open_forecast_ids = signals["open_forecast"].get(sid, [])
    override_ids = signals["override"].get(sid, [])
    repeated_override_ids = override_ids if len(override_ids) >= 2 else []

    caveats: list[str] = []
    if len(decision_ids) < min_sample:
        caveats.append("low_n_decisions")
    if missing_source_thesis_ids:
        caveats.append("thesis_source_coverage_only_missing_refs")
    caveats.append("policy_candidates_unsupported_local_surface")

    sections = {
        "decisions": _id_section(decision_ids),
        "review_due": _id_section(due_ids),
        "open_unresolved_forecasts": _id_section(open_forecast_ids),
        "source_quality_issues": _id_section(missing_source_thesis_ids),
        "repeated_overrides": _id_section(repeated_override_ids),
        "policy_candidates": _id_section([]),
    }
    signal_count = sum(sections[k]["count"] for k in ("review_due", "open_unresolved_forecasts", "source_quality_issues", "repeated_overrides"))
    if sections["repeated_overrides"]["count"] < 2:
        sections["repeated_overrides"]["caveat"] = "fewer_than_two_overrides"

    return {
        "key": sid,
        "label": f"Strategy health for {slug}",
        "metrics": {
            "strategy_id": sid,
            "slug": slug,
            "name": name,
            "status": status,
            "decision_count": len(decision_ids),
            "low_n": len(decision_ids) < min_sample,
            "review_priority": 1 if due_ids else 2,
            "signal_count": signal_count,
        },
        "filter": process_filter(rf, report=REPORT_NAME),
        "record_ids": {"strategies": [sid], **{k: v["record_ids"] for k, v in sections.items()}},
        "sections": sections,
        "caveats": sorted(set(caveats)),
        "sample_size": len(decision_ids),
        "sample_warning": "low_n_decisions" if len(decision_ids) < min_sample else None,
        "truncated": False,
    }


def report_strategy_health(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    status: str = "active",
    as_of: str | None = None,
    min_sample: int = DEFAULT_HEALTH_MIN_SAMPLE,
) -> dict[str, Any]:
    """Return local-only process health signals across strategies."""
    if status not in {"active", "archived", "all"}:
        raise ValueError("status must be one of active, archived, all")
    if not isinstance(min_sample, int) or min_sample < 1:
        raise ValueError("min_sample must be a positive integer")
    resolved_as_of = _iso(_parse_ts(as_of or now_iso()))
    rf = ReportFilter.model_validate(raw_filter or {})
    filter_view = process_filter(rf, report=REPORT_NAME)
    # Pin a single read snapshot so per-strategy SELECTs and the top-level
    # strategies SELECT can't disagree under concurrent writes
    # (trade-trace-d8lu).
    with read_snapshot(conn):
        strategy_value = _resolve_strategy_filter(conn, rf.strategy.strategy_id)
        if strategy_value == STRATEGY_NONE_SENTINEL:
            raise ValueError("report.strategy_health requires concrete strategy rows; strategy_id='__none__' is unsupported")

        sql = "SELECT id, slug, name, status FROM strategies WHERE 1=1"
        params: list[Any] = []
        if status != "all":
            sql += " AND status = ?"
            params.append(status)
        if strategy_value is not None:
            sql += " AND id = ?"
            params.append(strategy_value)
        sql += " ORDER BY status, slug, id"
        strategies = conn.execute(sql, tuple(params)).fetchall()
        strategy_ids = [row[0] for row in strategies]
        signals = _batch_signals(conn, strategy_ids, rf, as_of=resolved_as_of)
        groups = [_strategy_group(row, rf, signals, min_sample=min_sample) for row in strategies]
    groups.sort(key=lambda g: (g["metrics"]["review_priority"], g["metrics"]["slug"], g["key"]))

    totals = {"review_due": 0, "low_n": 0, "open_unresolved_forecasts": 0, "source_quality_issues": 0, "repeated_overrides": 0, "policy_candidates": 0}
    for group in groups:
        totals["low_n"] += 1 if group["metrics"]["low_n"] else 0
        for key in totals:
            if key != "low_n":
                totals[key] += group["sections"][key]["count"]
    caveats = ["source_quality_checks_limited_to_thesis_source_refs", "policy_candidates_unsupported_local_surface"]
    return standard_report_result(
        summary={
            "sample_size": len(groups),
            "sample_warning": "no_strategies" if not groups else None,
            "filter": {**filter_view, "status": status},
            "metrics": {"strategy_count": len(groups), **totals},
            "as_of": resolved_as_of,
            "min_sample": min_sample,
            "ordering": "review_due_first_then_slug_id",
            "caveats": caveats,
        },
        groups=groups,
    )


__all__ = ["DEFAULT_HEALTH_MIN_SAMPLE", "report_strategy_health"]
