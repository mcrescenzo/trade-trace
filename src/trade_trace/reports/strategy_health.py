"""Deterministic read-only strategy health report.

Aggregates local process-health signals across strategies. This report does not
rank performance, fetch external data, or provide trading advice.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from trade_trace.contracts.report_filter import STRATEGY_NONE_SENTINEL, ReportFilter
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import process_filter
from trade_trace.storage.database import read_snapshot
from trade_trace.tools._helpers import now_iso

REPORT_NAME = "report.strategy_health"
DEFAULT_HEALTH_MIN_SAMPLE = 5


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


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


def _resolve_strategy_filter(conn: sqlite3.Connection, value: str | None) -> str | None:
    if value in (None, STRATEGY_NONE_SENTINEL):
        return value
    row = conn.execute("SELECT id FROM strategies WHERE id = ? OR slug = ? ORDER BY id LIMIT 1", (value, value)).fetchone()
    return row[0] if row else value


def _ids(conn: sqlite3.Connection, sql: str, params: list[Any]) -> list[str]:
    return [row[0] for row in conn.execute(sql, tuple(params)).fetchall()]


def _strategy_group(conn: sqlite3.Connection, row: sqlite3.Row | tuple[Any, ...], rf: ReportFilter, *, as_of: str, min_sample: int) -> dict[str, Any]:
    sid, slug, name, status = row[0], row[1], row[2], row[3]

    params: list[Any] = [sid]
    decision_filter = _extend_filter_sql("d", rf, params)
    decision_ids = _ids(conn, f"SELECT d.id FROM decisions d WHERE d.strategy_id = ?{decision_filter} ORDER BY d.created_at, d.id", params)

    params = [sid, as_of]
    due_ids = _ids(conn, f"""
        SELECT d.id FROM decisions d
        WHERE d.strategy_id = ? AND d.type IN ('watch','hold','review')
          AND d.review_by IS NOT NULL AND d.review_by <= ?
          {_extend_filter_sql('d', rf, params)}
        ORDER BY d.review_by, d.created_at, d.id
    """, params)

    params = [sid]
    thesis_filter = _extend_filter_sql("t", rf, params)
    missing_source_thesis_ids = _ids(conn, f"""
        SELECT t.id FROM theses t
        WHERE t.strategy_id = ? AND NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE ((e.source_kind = 'thesis' AND e.source_id = t.id)
                OR (e.target_kind = 'thesis' AND e.target_id = t.id))
              AND (e.source_kind = 'source' OR e.target_kind = 'source')
        ){thesis_filter}
        ORDER BY t.created_at, t.id
    """, params)

    params = [sid]
    forecast_filter = _extend_filter_sql("f", rf, params)
    open_forecast_ids = _ids(conn, f"""
        SELECT f.id FROM forecasts f JOIN theses t ON t.id = f.thesis_id
        WHERE t.strategy_id = ? AND f.scoring_state IN ('pending','failed')
          AND f.invalidated_at IS NULL{forecast_filter}
        ORDER BY f.created_at, f.id
    """, params)

    params = [sid]
    override_ids = _ids(conn, f"""
        SELECT DISTINCT d.id FROM decisions d
        JOIN decision_playbook_rules dpr ON dpr.decision_id = d.id
        WHERE d.strategy_id = ? AND dpr.status = 'overridden'{_extend_filter_sql('d', rf, params)}
        ORDER BY d.created_at, d.id
    """, params)
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
        groups = [_strategy_group(conn, row, rf, as_of=resolved_as_of, min_sample=min_sample) for row in strategies]
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
