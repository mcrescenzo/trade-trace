"""PM-native report suite for v0.0.2.

These reports are deterministic read-only projections over the local SQLite
journal. They never fetch external market data, never execute trades, and never
rank opportunities; they summarize caller-recorded market/forecast/decision
state for agent continuity and calibration review.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import (
    _placeholders,
    applied_filter_view,
    enforce_supported_filter,
)
from trade_trace.reports.calibration import (
    DEFAULT_BIN_POLICY,
    DEFAULT_MIN_SAMPLE,
    _compute_metrics,
    _empty_metrics,
    _load_scored_rows,
)
from trade_trace.tools.ledger._finality import (
    finality_uncertain_for_outcome,
    is_auto_scoreable_final,
)


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


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
               m.created_at, m.metadata_json,
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
    event_grouping_rollups: dict[str, dict[str, Any]] = {}
    outcome_token_mappings: list[dict[str, Any]] = []
    now_dt = _parse_ts(_now_iso())
    resolution_due_markets: list[str] = []
    finality_uncertain_markets: list[str] = []
    for row in conn.execute(sql, params).fetchall():
        (
            market_id, source, external_id, title, state, mechanism,
            opened_at, close_at, closed_for_trading_at, resolving_at,
            resolved_at, voided_at, ambiguous_at, created_at, metadata_json,
            snapshot_count, decision_count, forecast_count,
        ) = row
        try:
            market_metadata = json.loads(metadata_json or "{}")
        except json.JSONDecodeError:
            market_metadata = {}
        state_counts[state] = state_counts.get(state, 0) + 1
        event_grouping = market_metadata.get("event_grouping") or {}
        identity = market_metadata.get("polymarket_identity") or {}
        resolution_rule = market_metadata.get("resolution_rule") or {}
        event_key = str(event_grouping.get("event_id") or event_grouping.get("event_slug") or "ungrouped")
        rollup = event_grouping_rollups.setdefault(
            event_key,
            {
                "event_id": event_grouping.get("event_id"),
                "event_slug": event_grouping.get("event_slug"),
                "event_title": event_grouping.get("event_title"),
                "market_count": 0,
                "markets": [],
                "resolution_rule_provenance": {},
            },
        )
        rollup["market_count"] += 1
        rollup["markets"].append(market_id)
        provenance = resolution_rule.get("provenance")
        if provenance:
            rollup["resolution_rule_provenance"][provenance] = rollup["resolution_rule_provenance"].get(provenance, 0) + 1
        tokens_by_label = identity.get("outcome_token_ids_by_label") or {}
        if tokens_by_label:
            outcome_token_mappings.append({
                "market_id": market_id,
                "event_id": event_grouping.get("event_id"),
                "outcome_token_ids_by_label": tokens_by_label,
                "resolution_rule": resolution_rule,
            })
        terminal_at = resolved_at or voided_at or ambiguous_at
        durations = {
            "open_to_close_hours": _hours_between(opened_at or created_at, closed_for_trading_at or close_at),
            "close_to_resolving_hours": _hours_between(closed_for_trading_at or close_at, resolving_at),
            "resolving_to_terminal_hours": _hours_between(resolving_at, terminal_at),
            "open_to_terminal_hours": _hours_between(opened_at or created_at, terminal_at),
        }
        latest_status_row = conn.execute(
            """
            SELECT status, confidence, outcome_label FROM outcomes
            WHERE instrument_id = ?
            ORDER BY resolved_at DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (market_id,),
        ).fetchone()
        latest_resolution_status = latest_status_row[0] if latest_status_row else None
        latest_is_safe_final = bool(
            latest_status_row
            and is_auto_scoreable_final(
                status=latest_status_row[0],
                confidence=latest_status_row[1],
                outcome_label=latest_status_row[2],
            )
        )
        close_dt = _parse_ts(close_at)
        resolution_due = bool(
            close_dt is not None
            and now_dt is not None
            and close_dt <= now_dt
            and state not in {"resolved", "voided", "ambiguous"}
            and not latest_is_safe_final
        )
        finality_uncertain = (
            state in {"closed_for_trading", "resolving", "voided", "ambiguous"}
            or bool(latest_status_row and not latest_is_safe_final)
            or resolution_due
        )
        if resolution_due:
            resolution_due_markets.append(market_id)
        if finality_uncertain:
            finality_uncertain_markets.append(market_id)
        caveat_codes = [
            code for code, enabled in (
                ("resolution_due", resolution_due),
                ("finality_uncertain", finality_uncertain),
            ) if enabled
        ]
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
                "polymarket_identity": identity or None,
                "event_grouping": event_grouping or None,
                "resolution_rule": resolution_rule or None,
                "latest_resolution_status": latest_resolution_status,
                "resolution_due": resolution_due,
                "finality_uncertain": finality_uncertain,
                "negative_risk": market_metadata.get("negative_risk"),
                "market_microstructure": market_metadata.get("market_microstructure"),
            },
            "filter": applied_filter_view(rf, report=report),
            "record_ids": {"markets": [market_id]},
            "caveat_codes": caveat_codes,
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
            "event_groupings": list(event_grouping_rollups.values()),
            "outcome_token_mappings": outcome_token_mappings,
            "resolution_due_market_ids": resolution_due_markets,
            "finality_uncertain_market_ids": finality_uncertain_markets,
        },
        "caveats": [
            code for code, enabled in (
                ("resolution_due", bool(resolution_due_markets)),
                ("finality_uncertain", bool(finality_uncertain_markets)),
            ) if enabled
        ],
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
        SELECT m.id, m.title, m.state, m.ambiguity_kind, m.metadata_json,
               o.id, o.status, o.outcome_label, o.resolved_at, o.source,
               o.confidence, o.created_at, o.metadata_json,
               COUNT(DISTINCT d.id) AS touched_decisions,
               COUNT(DISTINCT f.id) AS touched_forecasts,
               SUM(CASE WHEN lower(COALESCE(d.reason, '')) LIKE '%uncertain%'
                         OR lower(COALESCE(d.reason, '')) LIKE '%ambiguous%'
                         OR lower(COALESCE(d.reason, '')) LIKE '%dispute%'
                    THEN 1 ELSE 0 END) AS uncertainty_flags
        FROM outcomes o
        JOIN markets m ON m.id = o.instrument_id
        LEFT JOIN decisions d ON d.instrument_id = m.id
             AND (m.resolving_at IS NULL OR d.created_at <= m.resolving_at)
        LEFT JOIN forecasts f ON f.market_id = m.id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY m.id, o.id ORDER BY o.resolved_at, m.id"
    status_counts: dict[str, int] = {}
    groups: list[dict[str, Any]] = []
    for row in conn.execute(sql, params).fetchall():
        (
            market_id, title, market_state, ambiguity_kind, market_metadata_json,
            outcome_id, status, label, resolved_at, source, confidence,
            created_at, outcome_metadata_json, touched, touched_forecasts, uncertainty,
        ) = row
        try:
            market_metadata = json.loads(market_metadata_json or "{}")
        except json.JSONDecodeError:
            market_metadata = {}
        try:
            outcome_metadata = json.loads(outcome_metadata_json or "{}")
        except json.JSONDecodeError:
            outcome_metadata = {}
        resolution_rule = market_metadata.get("resolution_rule") or outcome_metadata.get("resolution_rule") or {}
        finality_uncertain = finality_uncertain_for_outcome(
            status=status,
            confidence=confidence,
            outcome_label=label,
        )
        caveat_codes = ["finality_uncertain"] if finality_uncertain else []
        status_counts[status] = status_counts.get(status, 0) + 1
        groups.append({
            "key": market_id,
            "label": title or market_id,
            "metrics": {
                "touched_decision_count": touched,
                "touched_forecast_count": touched_forecasts,
                "pre_resolution_uncertainty_flag_count": uncertainty or 0,
                "resolution_status": status,
                "finality_uncertain": finality_uncertain,
            },
            "resolution": {
                "outcome_id": outcome_id,
                "outcome_label": label,
                "resolved_at": resolved_at,
                "created_at": created_at,
                "source": source,
                "confidence": confidence,
                "market_state": market_state,
                "ambiguity_kind": ambiguity_kind,
                "resolution_rule": resolution_rule or None,
                "provenance": outcome_metadata.get("provenance") or outcome_metadata.get("source_provenance"),
                "timestamps": {
                    "as_of": outcome_metadata.get("as_of"),
                    "retrieved_at": outcome_metadata.get("retrieved_at"),
                    "imported_at": outcome_metadata.get("imported_at"),
                },
                "caveat_codes": caveat_codes,
            },
            "filter": applied_filter_view(rf, report=report),
            "record_ids": {"markets": [market_id], "outcomes": [outcome_id]},
            "caveat_codes": caveat_codes,
            "examples": [],
            "sample_size": 1,
            "sample_warning": None,
            "truncated": False,
        })
    ambiguous_like = sum(status_counts.get(s, 0) for s in ("ambiguous", "disputed", "void", "cancelled"))
    finality_uncertain_count = sum(1 for group in groups if group.get("caveat_codes"))
    summary: dict[str, Any] = {
        "sample_size": len(groups),
        "sample_warning": None if groups else "no resolved outcomes matched filter",
        "filter": applied_filter_view(rf, report=report),
        "metrics": {
            "resolved_market_count": len(groups),
            "status_counts": status_counts,
            "ambiguous_void_disputed_cancelled_count": ambiguous_like,
            "finality_uncertain_count": finality_uncertain_count,
        },
        "caveats": ["finality_uncertain"] if finality_uncertain_count else [],
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
    "report_market_lifecycle",
    "report_resolution_quality",
    "report_time_decay_sharpening",
]
