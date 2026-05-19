"""`report.compare` and `report.strategy_performance`.

The compare report is intentionally allowlist-driven: public `group_by` values map
to fixed SQL expressions, never interpolated from caller input. Metric calculation
reuses the existing base-report kernels (`report_calibration` private metric
helpers and `report_pnl` row aggregation helper) so grouped output stays aligned
with the standalone reports.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, cast

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.reports._filter_support import applied_filter_view, enforce_supported_filter
from trade_trace.reports.calibration import (
    DEFAULT_MIN_SAMPLE,
    _apply_scored_row_filters,
    _build_examples,
    _compute_metrics,
    _empty_metrics,
    _materialize_scored_row,
    _scored_row_base_where,
    _ScoredRow,
)
from trade_trace.reports.calibration import (
    REPORT_NAME as CALIBRATION_REPORT_NAME,
)
from trade_trace.reports.pnl import DEFAULT_PNL_MIN_SAMPLE, _pnl_metrics_for_rows

CALIBRATION_GROUP_SQL: dict[str, str] = {
    "agent_id": "f.actor_id",
    "model_id": "f.model_id",
    "strategy_id": "t.strategy_id",
    "decision_type": "d.type",
    "venue_id": "i.venue_id",
    "asset_class": "i.asset_class",
    "environment": "f.environment",
    "instrument_id": "i.id",
    "outcome_status": "o.status",
    "status": "o.status",
}

PNL_GROUP_SQL: dict[str, str] = {
    "instrument_id": "p.instrument_id",
    "status": "p.status",
    "venue_id": "i.venue_id",
    "asset_class": "i.asset_class",
}

# Per trade-trace-cs0r: this set used to advertise group_by values
# that the runtime allowlists rejected. It now reflects the actual
# union of `CALIBRATION_GROUP_SQL` and `PNL_GROUP_SQL`. Per-base-report
# subsets live below so an agent can pick a group_by that matches the
# base it's about to compare. `playbook_version_id`, `liquidity_bucket`,
# and `confidence_bucket` are P1+ design surfaces (PRD §4 lists them as
# the broader analytic ambition); promoting them here requires landing
# the SQL mapping AND a regression test first.
DOCUMENTED_GROUP_BY: set[str] = (
    set(CALIBRATION_GROUP_SQL) | set(PNL_GROUP_SQL)
)
SUPPORTED_GROUP_BY_BY_BASE_REPORT: dict[str, set[str]] = {
    "calibration": set(CALIBRATION_GROUP_SQL),
    "pnl": set(PNL_GROUP_SQL),
}

SUPPORTED_BASE_REPORTS = {"calibration", "pnl"}


def report_compare(
    conn: sqlite3.Connection,
    *,
    base_report: str = "calibration",
    group_by: str = "strategy_id",
    raw_filter: dict[str, Any] | None = None,
    min_sample: int | None = None,
) -> dict[str, Any]:
    base_report = base_report.strip().lower()
    group_by = group_by.strip().lower()
    if base_report not in SUPPORTED_BASE_REPORTS:
        raise ValueError(
            "report.compare base_report currently supports "
            f"{sorted(SUPPORTED_BASE_REPORTS)!r}; got {base_report!r}"
        )
    if base_report == "calibration":
        return _compare_calibration(conn, group_by=group_by, raw_filter=raw_filter, min_sample=min_sample or DEFAULT_MIN_SAMPLE)
    return _compare_pnl(conn, group_by=group_by, raw_filter=raw_filter, min_sample=min_sample or DEFAULT_PNL_MIN_SAMPLE)


def report_strategy_performance(
    conn: sqlite3.Connection,
    *,
    strategy_id: str | None = None,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int | None = None,
) -> dict[str, Any]:
    """Convenience wrapper over `report.compare`.

    Decision for trade-trace-4md: implement, not supersede. The wrapper returns
    P&L grouped by strategy. If `strategy_id` is supplied, it narrows the result
    to that strategy; when omitted it compares all strategies, including the
    `__none__` no-strategy bucket.
    """
    merged = dict(raw_filter or {})
    if strategy_id is not None:
        strategy = dict(merged.get("strategy") or {})
        strategy["strategy_id"] = strategy_id
        merged["strategy"] = strategy
    return report_compare(
        conn,
        base_report="pnl",
        group_by="strategy_id",
        raw_filter=merged,
        min_sample=min_sample,
    )


def _compare_calibration(conn: sqlite3.Connection, *, group_by: str, raw_filter: dict[str, Any] | None, min_sample: int) -> dict[str, Any]:
    if group_by not in CALIBRATION_GROUP_SQL:
        raise ValueError(f"unsupported group_by for calibration compare: {group_by!r}")
    rf = ReportFilter.model_validate(raw_filter or {})
    enforce_supported_filter(rf, report=CALIBRATION_REPORT_NAME)
    rows_by_group: dict[str, list[_ScoredRow]] = defaultdict(list)
    labels: dict[str, str] = {}
    for key, label, row in _load_grouped_scored_rows(conn, rf, CALIBRATION_GROUP_SQL[group_by]):
        rows_by_group[key].append(row)
        labels[key] = label
    groups = []
    any_warning = False
    for key in sorted(rows_by_group, key=lambda k: (k == "__none__", k)):
        rows = rows_by_group[key]
        warning = None
        if len(rows) < min_sample:
            warning = f"only {len(rows)} scored forecasts; calibration is unreliable below {min_sample}"
            any_warning = True
        metrics = _compute_metrics(rows) if rows else _empty_metrics()
        groups.append({
            "key": key,
            "label": labels[key],
            "metrics": metrics,
            "filter": _group_filter_view(rf, group_by, key, report="report.calibration"),
            "record_ids": {
                "forecasts": sorted({r.forecast_id for r in rows}),
                "forecast_scores": sorted({r.score_id for r in rows}),
                "outcomes": sorted({r.outcome_id for r in rows}),
            },
            "examples": _build_examples(conn, rows, max_examples=3),
            "sample_size": len(rows),
            "sample_warning": warning,
            "truncated": False,
        })
    total = sum(cast("int", g["sample_size"]) for g in groups)
    return {
        "summary": {
            "base_report": "calibration",
            "group_by": group_by,
            "sample_size": total,
            "sample_warning": "one_or_more_groups_below_min_sample" if any_warning else None,
            "filter": applied_filter_view(rf, report=CALIBRATION_REPORT_NAME),
            "metrics": {"group_count": len(groups), "min_sample": min_sample},
            "caveats": [],
        },
        "groups": groups,
        "truncated": False,
        "next_cursor": None,
    }


def _compare_pnl(conn: sqlite3.Connection, *, group_by: str, raw_filter: dict[str, Any] | None, min_sample: int) -> dict[str, Any]:
    if group_by == "strategy_id":
        group_expr = "t.strategy_id"
    elif group_by in PNL_GROUP_SQL:
        group_expr = PNL_GROUP_SQL[group_by]
    else:
        raise ValueError(f"unsupported group_by for pnl compare: {group_by!r}")
    rf = ReportFilter.model_validate(raw_filter or {})
    # report.pnl standalone accepts only empty filters today; compare adds safe
    # strategy slicing for its wrapper, handled below via parameters.
    if rf.strategy.strategy_id is None:
        enforce_supported_filter(rf, report="report.pnl")
    where: list[str] = []
    params: list[Any] = []
    if rf.strategy.strategy_id is not None:
        if rf.strategy.strategy_id == "__none__":
            where.append("t.strategy_id IS NULL")
        else:
            where.append("t.strategy_id = ?")
            params.append(rf.strategy.strategy_id)
    sql = f"""
        SELECT p.id, p.instrument_id, p.kind, p.status, p.realized_pnl, p.unrealized_pnl,
               {group_expr} AS group_value
        FROM positions p
        LEFT JOIN instruments i ON i.id = p.instrument_id
        LEFT JOIN position_events pe ON pe.id = (
            SELECT pe2.id FROM position_events pe2
            WHERE pe2.position_id = p.id AND pe2.decision_id IS NOT NULL
            ORDER BY pe2.created_at ASC, pe2.id ASC LIMIT 1
        )
        LEFT JOIN decisions d ON d.id = pe.decision_id
        LEFT JOIN theses t ON t.id = d.thesis_id
        {('WHERE ' + ' AND '.join(where)) if where else ''}
    """
    buckets: dict[str, list[tuple]] = defaultdict(list)
    for row in conn.execute(sql, params).fetchall():
        key = row[6] if row[6] is not None else "__none__"
        buckets[str(key)].append(row[:6])
    groups = []
    any_warning = False
    for key in sorted(buckets, key=lambda k: (k == "__none__", k)):
        rows = buckets[key]
        metrics = _pnl_metrics_for_rows(rows)
        closed = metrics["closed_count"]
        warning = None
        if 0 < closed < min_sample:
            warning = f"only {closed} closed positions; pnl trend is unreliable below {min_sample}"
            any_warning = True
        groups.append({
            "key": key,
            "label": f"{group_by}={key}",
            "metrics": metrics,
            "filter": _group_filter_view(rf, group_by, key, report="report.pnl"),
            "record_ids": {"positions": [r[0] for r in rows]},
            "examples": [{"kind": "position", "id": r[0], "summary": f"{r[3]} on {r[1]}"} for r in rows[:3]],
            "sample_size": len(rows),
            "sample_warning": warning,
            "truncated": False,
        })
    return {
        "summary": {
            "base_report": "pnl",
            "group_by": group_by,
            "sample_size": sum(g["sample_size"] for g in groups),
            "sample_warning": "one_or_more_groups_below_min_sample" if any_warning else None,
            "filter": applied_filter_view(rf, report="report.pnl") if rf.strategy.strategy_id is None else rf.model_dump(),
            "metrics": {"group_count": len(groups), "min_sample": min_sample},
            "caveats": [],
        },
        "groups": groups,
        "truncated": False,
        "next_cursor": None,
    }


def _load_grouped_scored_rows(conn: sqlite3.Connection, rf: ReportFilter, group_expr: str) -> Iterable[tuple[str, str, _ScoredRow]]:
    where = _scored_row_base_where()
    params: list[Any] = []
    _apply_scored_row_filters(
        rf, where, params, include_late_recorded_predicate=True,
    )
    sql = f"""
        SELECT fs.id, fs.forecast_id, fs.outcome_id, fs.metadata_json, f.yes_label,
               o.outcome_label, {group_expr} AS group_value
        FROM forecast_scores fs
        JOIN forecasts f ON f.id = fs.forecast_id
        JOIN theses t ON t.id = f.thesis_id
        LEFT JOIN decisions d ON d.thesis_id = t.id
        JOIN instruments i ON i.id = t.instrument_id
        JOIN outcomes o ON o.id = fs.outcome_id
        WHERE {' AND '.join(where)}
    """
    for score_id, forecast_id, outcome_id, metadata_json, yes_label, outcome_label, group_value in conn.execute(sql, params).fetchall():
        materialized = _materialize_scored_row(
            conn,
            score_id=score_id,
            forecast_id=forecast_id,
            outcome_id=outcome_id,
            metadata_json=metadata_json,
            yes_label=yes_label,
            outcome_label=outcome_label,
        )
        if materialized is None:
            continue
        key = str(group_value) if group_value is not None else "__none__"
        yield key, f"group_by={key}", materialized


def _group_filter_view(rf: ReportFilter, group_by: str, key: str, *, report: str) -> dict[str, Any]:
    view = applied_filter_view(rf, report=report) if report != "report.pnl" or rf.strategy.strategy_id is None else rf.model_dump()
    if group_by == "strategy_id":
        view.setdefault("strategy", {})["strategy_id"] = key
    elif group_by == "venue_id":
        view.setdefault("instrument", {})["venue_id"] = [key]
    elif group_by == "agent_id":
        view.setdefault("actors", {})["actor_id"] = [key]
    else:
        view.setdefault("compare", {})["group_by"] = group_by
        view["compare"]["group_value"] = key
    return view


__all__ = [
    "DOCUMENTED_GROUP_BY",
    "SUPPORTED_GROUP_BY_BY_BASE_REPORT",
    "report_compare",
    "report_strategy_performance",
]
