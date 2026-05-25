"""PM-native report suite for v0.0.2.

These reports are deterministic read-only projections over the local SQLite
journal. They never fetch external market data, never execute trades, and never
rank opportunities; they summarize caller-recorded market/forecast/decision
state for agent continuity and calibration review.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from trade_trace.contracts.report_filter import STRATEGY_NONE_SENTINEL, ReportFilter
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import applied_filter_view, enforce_supported_filter
from trade_trace.reports.calibration import (
    DEFAULT_BIN_POLICY,
    DEFAULT_MIN_SAMPLE,
    _compute_metrics,
    _empty_metrics,
    _load_scored_rows,
)


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _hours_between(start: str | None, end: str | None) -> float | None:
    start_dt = _parse_ts(start)
    end_dt = _parse_ts(end)
    if start_dt is None or end_dt is None:
        return None
    return (end_dt - start_dt).total_seconds() / 3600.0


def _market_where(rf: ReportFilter, *, alias: str = "m") -> tuple[list[str], list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    if rf.actors.actor_id:
        where.append(f"{alias}.actor_id IN ({_placeholders(len(rf.actors.actor_id))})")
        params.extend(rf.actors.actor_id)
    if rf.instrument.instrument_id:
        where.append(f"{alias}.id IN ({_placeholders(len(rf.instrument.instrument_id))})")
        params.extend(rf.instrument.instrument_id)
    if rf.time_window.created_at_gte:
        where.append(f"{alias}.created_at >= ?")
        params.append(rf.time_window.created_at_gte)
    if rf.time_window.created_at_lt:
        where.append(f"{alias}.created_at < ?")
        params.append(rf.time_window.created_at_lt)
    return where, params


def _decision_where(rf: ReportFilter, *, alias: str = "d") -> tuple[list[str], list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    if rf.actors.actor_id:
        where.append(f"{alias}.actor_id IN ({_placeholders(len(rf.actors.actor_id))})")
        params.extend(rf.actors.actor_id)
    if rf.actors.agent_id:
        where.append(f"{alias}.agent_id IN ({_placeholders(len(rf.actors.agent_id))})")
        params.extend(rf.actors.agent_id)
    if rf.actors.model_id:
        where.append(f"{alias}.model_id IN ({_placeholders(len(rf.actors.model_id))})")
        params.extend(rf.actors.model_id)
    if rf.actors.environment:
        where.append(f"{alias}.environment IN ({_placeholders(len(rf.actors.environment))})")
        params.extend(rf.actors.environment)
    if rf.actors.run_id:
        where.append(f"{alias}.run_id IN ({_placeholders(len(rf.actors.run_id))})")
        params.extend(rf.actors.run_id)
    if rf.instrument.instrument_id:
        where.append(f"{alias}.instrument_id IN ({_placeholders(len(rf.instrument.instrument_id))})")
        params.extend(rf.instrument.instrument_id)
    if rf.decision.decision_type:
        where.append(f"{alias}.type IN ({_placeholders(len(rf.decision.decision_type))})")
        params.extend(rf.decision.decision_type)
    if rf.time_window.decision_at_gte:
        where.append(f"{alias}.created_at >= ?")
        params.append(rf.time_window.decision_at_gte)
    if rf.time_window.decision_at_lt:
        where.append(f"{alias}.created_at < ?")
        params.append(rf.time_window.decision_at_lt)
    if rf.strategy.strategy_id is not None:
        if rf.strategy.strategy_id == STRATEGY_NONE_SENTINEL:
            where.append(f"{alias}.strategy_id IS NULL")
        else:
            where.append(f"{alias}.strategy_id = ?")
            params.append(rf.strategy.strategy_id)
    return where, params


_MARKET_FILTERS = frozenset({
    "actors.actor_id",
    "instrument.instrument_id",
    "time_window.created_at_gte",
    "time_window.created_at_lt",
})

_DECISION_FILTERS = frozenset({
    "actors.actor_id",
    "actors.agent_id",
    "actors.model_id",
    "actors.environment",
    "actors.run_id",
    "instrument.instrument_id",
    "decision.decision_type",
    "strategy.strategy_id",
    "time_window.decision_at_gte",
    "time_window.decision_at_lt",
})

_TIME_DECAY_FILTERS = frozenset({
    "actors.actor_id",
    "actors.agent_id",
    "actors.model_id",
    "actors.environment",
    "actors.run_id",
    "instrument.venue_id",
    "strategy.strategy_id",
    "outcome.include_late_recorded",
})


def report_market_lifecycle(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = "report.market_lifecycle"
    rf = ReportFilter.model_validate(raw_filter or {})
    enforce_supported_filter(rf, report=report)
    where, params = _market_where(rf)
    sql = """
        SELECT m.id, m.source, m.external_id, m.title, m.state, m.mechanism,
               m.opened_at, m.close_at, m.closed_for_trading_at,
               m.resolving_at, m.resolved_at, m.voided_at, m.ambiguous_at,
               m.created_at,
               (SELECT COUNT(*) FROM snapshots s WHERE s.instrument_id = m.id) AS snapshot_count,
               (SELECT COUNT(*) FROM decisions d WHERE d.instrument_id = m.id) AS decision_count,
               (SELECT COUNT(*) FROM forecasts f WHERE f.market_id = m.id) AS forecast_count
        FROM markets m
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(m.opened_at, m.created_at), m.id"
    groups: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    for row in conn.execute(sql, params).fetchall():
        (
            market_id, source, external_id, title, state, mechanism,
            opened_at, close_at, closed_for_trading_at, resolving_at,
            resolved_at, voided_at, ambiguous_at, created_at,
            snapshot_count, decision_count, forecast_count,
        ) = row
        state_counts[state] = state_counts.get(state, 0) + 1
        terminal_at = resolved_at or voided_at or ambiguous_at
        durations = {
            "open_to_close_hours": _hours_between(opened_at or created_at, closed_for_trading_at or close_at),
            "close_to_resolving_hours": _hours_between(closed_for_trading_at or close_at, resolving_at),
            "resolving_to_terminal_hours": _hours_between(resolving_at, terminal_at),
            "open_to_terminal_hours": _hours_between(opened_at or created_at, terminal_at),
        }
        groups.append({
            "key": market_id,
            "label": title or external_id,
            "metrics": {
                "snapshot_count": snapshot_count,
                "decision_count": decision_count,
                "forecast_count": forecast_count,
                **durations,
            },
            "market": {
                "id": market_id,
                "source": source,
                "external_id": external_id,
                "state": state,
                "mechanism": mechanism,
                "opened_at": opened_at,
                "close_at": close_at,
                "closed_for_trading_at": closed_for_trading_at,
                "resolving_at": resolving_at,
                "resolved_at": resolved_at,
                "voided_at": voided_at,
                "ambiguous_at": ambiguous_at,
                "created_at": created_at,
            },
            "filter": applied_filter_view(rf, report=report),
            "record_ids": {"markets": [market_id]},
            "examples": [],
            "sample_size": 1,
            "sample_warning": None,
            "truncated": False,
        })
    summary: dict[str, Any] = {
        "sample_size": len(groups),
        "sample_warning": None if groups else "no markets matched filter",
        "filter": applied_filter_view(rf, report=report),
        "metrics": {
            "market_count": len(groups),
            "state_counts": state_counts,
        },
        "caveats": [],
    }
    return standard_report_result(summary=summary, groups=groups)


def report_resolution_quality(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = "report.resolution_quality"
    rf = ReportFilter.model_validate(raw_filter or {})
    enforce_supported_filter(rf, report=report)
    where, params = _market_where(rf)
    if rf.outcome.resolution_status:
        where.append(f"o.status IN ({_placeholders(len(rf.outcome.resolution_status))})")
        params.extend(rf.outcome.resolution_status)
    if rf.time_window.resolved_at_gte:
        where.append("o.resolved_at >= ?")
        params.append(rf.time_window.resolved_at_gte)
    if rf.time_window.resolved_at_lt:
        where.append("o.resolved_at < ?")
        params.append(rf.time_window.resolved_at_lt)
    sql = """
        SELECT m.id, m.title, m.state, m.ambiguity_kind, o.id, o.status,
               o.outcome_label, o.resolved_at,
               COUNT(DISTINCT d.id) AS touched_decisions,
               SUM(CASE WHEN lower(COALESCE(d.reason, '')) LIKE '%uncertain%'
                         OR lower(COALESCE(d.reason, '')) LIKE '%ambiguous%'
                         OR lower(COALESCE(d.reason, '')) LIKE '%dispute%'
                    THEN 1 ELSE 0 END) AS uncertainty_flags
        FROM outcomes o
        JOIN markets m ON m.id = o.instrument_id
        LEFT JOIN decisions d ON d.instrument_id = m.id
             AND (m.resolving_at IS NULL OR d.created_at <= m.resolving_at)
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY m.id, o.id ORDER BY o.resolved_at, m.id"
    status_counts: dict[str, int] = {}
    groups: list[dict[str, Any]] = []
    for row in conn.execute(sql, params).fetchall():
        market_id, title, market_state, ambiguity_kind, outcome_id, status, label, resolved_at, touched, uncertainty = row
        status_counts[status] = status_counts.get(status, 0) + 1
        groups.append({
            "key": market_id,
            "label": title or market_id,
            "metrics": {
                "touched_decision_count": touched,
                "pre_resolution_uncertainty_flag_count": uncertainty or 0,
                "resolution_status": status,
            },
            "resolution": {
                "outcome_id": outcome_id,
                "outcome_label": label,
                "resolved_at": resolved_at,
                "market_state": market_state,
                "ambiguity_kind": ambiguity_kind,
            },
            "filter": applied_filter_view(rf, report=report),
            "record_ids": {"markets": [market_id], "outcomes": [outcome_id]},
            "examples": [],
            "sample_size": 1,
            "sample_warning": None,
            "truncated": False,
        })
    ambiguous_like = sum(status_counts.get(s, 0) for s in ("ambiguous", "disputed", "void", "cancelled"))
    summary: dict[str, Any] = {
        "sample_size": len(groups),
        "sample_warning": None if groups else "no resolved outcomes matched filter",
        "filter": applied_filter_view(rf, report=report),
        "metrics": {
            "resolved_market_count": len(groups),
            "status_counts": status_counts,
            "ambiguous_void_disputed_cancelled_count": ambiguous_like,
        },
        "caveats": [],
    }
    return standard_report_result(summary=summary, groups=groups)


def report_amm_slippage(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = "report.amm_slippage"
    rf = ReportFilter.model_validate(raw_filter or {})
    enforce_supported_filter(rf, report=report)
    where, params = _decision_where(rf)
    where.append("m.mechanism = 'amm'")
    where.append("d.price IS NOT NULL")
    where.append("d.snapshot_id IS NOT NULL")
    sql = """
        SELECT d.id, d.instrument_id, d.type, d.side, d.price, d.created_at,
               s.id, COALESCE(s.mid, s.implied_probability, s.price),
               m.title, m.external_id
        FROM decisions d
        JOIN markets m ON m.id = d.instrument_id
        JOIN snapshots s ON s.id = d.snapshot_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY d.created_at, d.id"
    groups: list[dict[str, Any]] = []
    slippages: list[float] = []
    missing_mark_count = 0
    for row in conn.execute(sql, params).fetchall():
        decision_id, market_id, dtype, side, price, created_at, snapshot_id, mark, title, external_id = row
        if mark is None or float(mark) == 0.0:
            missing_mark_count += 1
            slippage_bps = None
        else:
            slippage_bps = (float(price) - float(mark)) / float(mark) * 10000.0
            slippages.append(slippage_bps)
        groups.append({
            "key": decision_id,
            "label": f"{dtype} on {title or external_id}",
            "metrics": {
                "decision_price": price,
                "snapshot_mark": mark,
                "slippage_bps": slippage_bps,
            },
            "decision": {
                "id": decision_id,
                "market_id": market_id,
                "type": dtype,
                "side": side,
                "created_at": created_at,
                "snapshot_id": snapshot_id,
            },
            "filter": applied_filter_view(rf, report=report),
            "record_ids": {"decisions": [decision_id], "markets": [market_id], "snapshots": [snapshot_id]},
            "examples": [],
            "sample_size": 1,
            "sample_warning": None,
            "truncated": False,
        })
    avg_abs = (sum(abs(x) for x in slippages) / len(slippages)) if slippages else None
    summary = {
        "sample_size": len(groups),
        "sample_warning": None if groups else "no AMM decisions with price and linked snapshot mark matched filter",
        "filter": applied_filter_view(rf, report=report),
        "metrics": {
            "decision_count": len(groups),
            "priced_mark_count": len(slippages),
            "missing_mark_count": missing_mark_count,
            "avg_abs_slippage_bps": avg_abs,
        },
        "caveats": ["Slippage is computed from caller-recorded decision price and linked local snapshot mark only; no external quote lookup."],
    }
    return standard_report_result(summary=summary, groups=groups)


def _time_decay_rows(conn: sqlite3.Connection, rf: ReportFilter) -> list[dict[str, Any]]:
    scored = _load_scored_rows(conn, rf)
    if not rf.outcome.include_late_recorded:
        scored = [r for r in scored if not r.late_recorded]
    if not scored:
        return []
    score_ids = [r.score_id for r in scored]
    rows = conn.execute(
        f"""
        SELECT fs.id, f.created_at, o.resolved_at
        FROM forecast_scores fs
        JOIN forecasts f ON f.id = fs.forecast_id
        JOIN outcomes o ON o.id = fs.outcome_id
        WHERE fs.id IN ({_placeholders(len(score_ids))})
        """,
        score_ids,
    ).fetchall()
    times = {score_id: (created_at, resolved_at) for score_id, created_at, resolved_at in rows}
    out: list[dict[str, Any]] = []
    for r in scored:
        created_at, resolved_at = times.get(r.score_id, (None, None))
        created = _parse_ts(created_at)
        resolved = _parse_ts(resolved_at)
        hours = None
        if created is not None and resolved is not None:
            hours = (resolved - created).total_seconds() / 3600.0
        if hours is None:
            bucket = "unknown"
        elif hours < 24:
            bucket = "0_24h"
        elif hours < 72:
            bucket = "1_3d"
        elif hours < 168:
            bucket = "3_7d"
        else:
            bucket = "7d_plus"
        out.append({"row": r, "bucket": bucket, "hours_to_resolution": hours})
    return out


def report_time_decay_sharpening(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    return _time_decay_report(
        conn,
        raw_filter=raw_filter,
        min_sample=min_sample,
        report="report.time_decay_sharpening",
        label="Forecast calibration by time-to-resolution bucket",
    )


def report_calibration_trajectory(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    return _time_decay_report(
        conn,
        raw_filter=raw_filter,
        min_sample=min_sample,
        report="report.calibration_trajectory",
        label="Trajectory calibration trend by time-to-resolution bucket",
    )


def _time_decay_report(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None,
    min_sample: int,
    report: str,
    label: str,
) -> dict[str, Any]:
    rf = ReportFilter.model_validate(raw_filter or {})
    enforce_supported_filter(rf, report=report)
    decorated = _time_decay_rows(conn, rf)
    by_bucket: dict[str, list[Any]] = {}
    for item in decorated:
        by_bucket.setdefault(item["bucket"], []).append(item)
    groups: list[dict[str, Any]] = []
    for bucket in ("0_24h", "1_3d", "3_7d", "7d_plus", "unknown"):
        items = by_bucket.get(bucket, [])
        if not items:
            continue
        scored_rows = [item["row"] for item in items]
        metrics = _compute_metrics(scored_rows) if scored_rows else _empty_metrics()
        hours = [item["hours_to_resolution"] for item in items if item["hours_to_resolution"] is not None]
        metrics["avg_hours_to_resolution"] = sum(hours) / len(hours) if hours else None
        groups.append({
            "key": bucket,
            "label": bucket,
            "metrics": metrics,
            "filter": applied_filter_view(rf, report=report),
            "record_ids": {
                "forecasts": sorted({r.forecast_id for r in scored_rows}),
                "forecast_scores": sorted({r.score_id for r in scored_rows}),
                "outcomes": sorted({r.outcome_id for r in scored_rows}),
            },
            "examples": [],
            "sample_size": len(scored_rows),
            "sample_warning": None if len(scored_rows) >= min_sample else f"only {len(scored_rows)} scored forecasts in bucket; calibration is unreliable below {min_sample}",
            "truncated": False,
        })
    all_rows = [item["row"] for item in decorated]
    summary_metrics = _compute_metrics(all_rows) if all_rows else _empty_metrics()
    summary: dict[str, Any] = {
        "sample_size": len(all_rows),
        "sample_warning": None if len(all_rows) >= min_sample else f"only {len(all_rows)} scored forecasts; calibration is unreliable below {min_sample}",
        "filter": applied_filter_view(rf, report=report),
        "metrics": summary_metrics,
        "caveats": [],
    }
    return standard_report_result(
        summary=summary,
        groups=groups,
        extra={"bin_policy": DEFAULT_BIN_POLICY, "bucket_axis": "hours_to_resolution", "label": label},
    )


__all__ = [
    "_DECISION_FILTERS",
    "_MARKET_FILTERS",
    "_TIME_DECAY_FILTERS",
    "report_amm_slippage",
    "report_calibration_trajectory",
    "report_market_lifecycle",
    "report_resolution_quality",
    "report_time_decay_sharpening",
]
