"""`report.*` tool surface per docs/architecture/reports.md.

This module ships the contract-grade pieces an agent needs to introspect
the report system before the full 7-report implementation lands:

- `report.filter_schema` (trade-trace-fo7): canonical JSON Schema for the
  ReportFilter shape. Agents call this to discover valid fields and enum
  values without reading the docs.

The 7 deterministic reports (calibration, mistakes, strengths, pnl,
watchlist, unscored_forecasts, decision_velocity) land in
trade-trace-77z; the coach lands in trade-trace-2g2.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.reports import (
    TradingAdvicePhraseError,
    report_audit_readiness,
    report_calibration,
    report_calibration_integrity,
    report_coach,
    report_compare,
    report_decision_velocity,
    report_lifecycle,
    report_mistakes,
    report_opportunity,
    report_playbook_adherence,
    report_pnl,
    report_risk,
    report_source_quality,
    report_strategy_performance,
    report_strengths,
    report_unscored_forecasts,
    report_watchlist,
)
from trade_trace.reports._filter_support import UnsupportedFilterError
from trade_trace.storage import resolve_home
from trade_trace.storage.paths import db_path
from trade_trace.timestamps import TimestampValidationError, to_utc_iso8601
from trade_trace.tools._helpers import open_db_for_args
from trade_trace.tools._report_filter_errors import (
    report_filter_validation_to_tool_error,
    unsupported_filter_to_tool_error,
)
from trade_trace.tools.errors import ToolError

_EMPTY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "description": "No tool-specific arguments are accepted.",
}


def _schema(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
    description: str = "",
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "description": description,
    }


_FILTER_PROP = {
    "type": "object",
    "description": (
        "ReportFilter object; call report.filter_schema for the canonical "
        "nested schema and supported fields."
    ),
}


_REPORT_SCHEMAS: dict[str, dict[str, Any]] = {
    "report.filter_schema": _schema(
        {"mode": {"type": "string", "enum": ["validation", "serialization"]}},
        description=(
            "Optional mode selects validation (accepted input) or "
            "serialization (emitted echo) ReportFilter schema."
        ),
    ),
    "report.calibration": _schema(
        {"filter": _FILTER_PROP, "min_sample": {"type": "integer", "minimum": 1}},
        description="Optional ReportFilter and low-N warning threshold; defaults min_sample=20.",
    ),
    "report.playbook_adherence": _schema(
        {
            "filter": _FILTER_PROP,
            "playbook_id": {"type": "string"},
            "strategy_id": {"type": "string"},
        },
        description="Optional ReportFilter plus top-level playbook_id/strategy_id scoping.",
    ),
    "report.source_quality": _schema(
        {
            "stale_threshold_days": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Age threshold in days for stale_sources. The diagnostic "
                    "compares sources.freshness_at to the linked decision.created_at; "
                    "sources without freshness_at are skipped, and retrieved_at is "
                    "not used as a fallback."
                ),
            }
        },
        description=(
            "Global source provenance hygiene report. stale_sources is driven by "
            "sources.freshness_at (evidence-current time) versus decision.created_at; "
            "retrieved_at is retrieval/provenance time only and does not trigger stale diagnostics."
        ),
    ),
    "report.audit_readiness": _schema(
        {
            "stale_snapshot_threshold_days": {"type": "integer", "minimum": 0},
            "stale_source_threshold_days": {"type": "integer", "minimum": 0},
        },
        description="Read-only local prediction/event-market audit-readiness diagnostics; no network, no advice.",
    ),
    "report.calibration_integrity": _EMPTY_SCHEMA,
    "report.unscored_forecasts": _schema({"filter": _FILTER_PROP}),
    "report.decision_velocity": _schema(
        {"filter": _FILTER_PROP, "bucket": {"type": "string", "enum": ["day", "week"]}},
        description="bucket defaults to day; only day/week are accepted.",
    ),
    "report.mistakes": _schema({"filter": _FILTER_PROP}),
    "report.strengths": _schema({"filter": _FILTER_PROP}),
    "report.pnl": _schema(
        {"filter": _FILTER_PROP},
        description=(
            "Lower-level P&L report over the local positions projection. Use for realized/unrealized/MTM P&L, "
            "not as the first answer to 'open trades' or 'current exposure'. For open trades/current exposure, "
            "start with report.current_exposure; for row-level open-position detail use report.open_positions. "
            "If summary.metrics.open_position_count > 0, run report.current_exposure or report.open_positions before "
            "answering exposure questions. Trade Trace records local journal/projection state only; it does not execute trades "
            "or prove broker portfolio truth."
        ),
    ),
    "report.risk": _schema({"filter": _FILTER_PROP}),
    "report.opportunity": _schema(
        {
            "filter": _FILTER_PROP,
            "minimum_coverage": {"type": "string", "enum": ["sparse", "partial", "full"]},
            "max_records": {"type": "integer", "minimum": 1},
            "include_labels": {"type": "boolean"},
            "min_sample": {"type": "integer", "minimum": 1},
        }
    ),
    "report.compare": _schema(
        {
            "base_report": {"type": "string", "enum": ["calibration", "pnl"]},
            "group_by": {
                "type": "string",
                "description": (
                    "Allowlisted by base_report; common values include "
                    "strategy_id, instrument_id, tag."
                ),
            },
            "filter": _FILTER_PROP,
            "min_sample": {"type": "integer", "minimum": 1},
        }
    ),
    "report.strategy_performance": _schema(
        {
            "strategy_id": {"type": "string"},
            "filter": _FILTER_PROP,
            "min_sample": {"type": "integer", "minimum": 1},
        }
    ),
    "report.watchlist": _schema(
        {
            "filter": _FILTER_PROP,
            "mode": {"type": "string", "enum": ["all", "stale"]},
            "stale_threshold_days": {"type": "integer", "minimum": 0},
        }
    ),
    "report.lifecycle": _schema(
        {
            "filter": _FILTER_PROP,
            "states": {"type": "array", "items": {"type": "string"}},
            "status": {"type": "string"},
            "as_of": {"type": "string", "format": "date-time"},
            "stale_threshold_days": {"type": "integer", "minimum": 0},
        },
        description="Read-only derived lifecycle cases; filter by ReportFilter plus states/status, as_of, and stale threshold.",
    ),
    "report.open_positions": _schema(
        {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum open-position rows to return; defaults to the positions page default.",
            },
            "cursor": {
                "type": "string",
                "description": "Opaque pagination cursor from a previous report.open_positions response.",
            },
            "kind": {
                "type": "string",
                "enum": ["paper", "actual", "simulation"],
                "description": "Optional position kind filter. Omit to include all open exposure kinds.",
            },
            "instrument_id": {"type": "string"},
            "strategy_id": {"type": "string"},
            "stale_mark_threshold_days": {
                "type": "integer",
                "minimum": 0,
                "description": "Age threshold in days for latest snapshot/mark caveats; defaults to 14.",
            },
            "as_of": {
                "type": "string",
                "format": "date-time",
                "description": "Optional ISO timestamp used to evaluate stale latest marks; defaults to current UTC.",
            },
        },
        description=(
            "Read-only current-exposure report: canonical row-level open positions "
            "from the positions projection/position_events lineage. Defaults to open "
            "and partial positions only; closed positions and unclosed decisions are not "
            "current exposure. Includes latest snapshot mark metadata when available and "
            "flags stale marks by stale_mark_threshold_days. Do not infer open trades from "
            "decisions or watches."
        ),
    ),
    "report.exposure_anomalies": _schema(
        {
            "stale_mark_threshold_days": {
                "type": "integer",
                "minimum": 0,
                "description": "Age threshold in days for latest snapshot/mark anomalies; defaults to 14.",
            },
            "as_of": {
                "type": "string",
                "format": "date-time",
                "description": "Optional ISO timestamp used to evaluate stale latest marks; defaults to current UTC.",
            },
        },
        description=(
            "Read-only current-exposure ambiguity/data-quality caveat report. "
            "Returns projection_anomalies with stable codes including "
            "ENTRY_DECISION_WITHOUT_POSITION_EVENT, DUPLICATE_DECISIONS, "
            "RECORD_ONLY_ACTUAL, MISSING_MARK, STALE_MARK, PROJECTION_MISSING, "
            "and PROJECTION_STALE. This reports local journal/projection data quality, "
            "not market risk or broker truth."
        ),
    ),
    "report.current_exposure": _schema(
        {
            "recent_limit": {"type": "integer", "minimum": 0, "description": "Maximum recent trade-typed decision rows to return; defaults to 10."},
            "include_watchlist": {"type": "boolean", "description": "Include watchlist bucket; defaults true. Watches are WATCH_ONLY_IDEA and never exposure."},
            "include_anomalies": {"type": "boolean", "description": "Include projection_anomalies bucket; defaults true."},
            "kind": {"type": "string", "enum": ["paper", "actual", "simulation"]},
            "instrument_id": {"type": "string"},
            "strategy_id": {"type": "string"},
            "stale_mark_threshold_days": {"type": "integer", "minimum": 0},
            "as_of": {"type": "string", "format": "date-time"},
        },
        description=(
            "Recommended trader-agent entry point for open trades/current exposure/recent trading activity. "
            "Returns open_positions, watchlist, recent_trade_activity, and projection_anomalies in one packet. "
            "Current exposure comes from positions/position_events; watchlist rows are WATCH_ONLY_IDEA; recent_trade_activity "
            "is journal activity and not canonical exposure by itself."
        ),
    ),
    "report.coach": _schema(
        {"filter": _FILTER_PROP, "stale_threshold_days": {"type": "integer", "minimum": 0}}
    ),
}

_CURRENT_EXPOSURE_CAVEAT_MAP = {"open_no_mark": "MISSING_MARK"}


def _position_current_exposure_codes(row: Any) -> list[str]:
    codes: list[str] = []
    if row.kind == "paper":
        codes.append("OPEN_PAPER_POSITION")
    elif row.kind == "actual":
        codes.append("OPEN_ACTUAL_RECORDED_POSITION")
    for caveat in row.caveats:
        mapped = _CURRENT_EXPOSURE_CAVEAT_MAP.get(caveat)
        if mapped is not None and mapped not in codes:
            codes.append(mapped)
    return codes


def _parse_report_timestamp(value: str, *, field: str) -> datetime:
    try:
        normalized = to_utc_iso8601(value, field=field)
    except TimestampValidationError as exc:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            str(exc),
            details={"field": field, "value": value},
        ) from exc
    return datetime.fromisoformat(normalized.replace("Z", "+00:00"))


def _snapshot_latest_mark(snapshot: Any) -> dict[str, Any]:
    fields = {
        "id": snapshot[0],
        "captured_at": snapshot[1],
        "source": snapshot[2],
        "source_url": snapshot[3],
        "price": snapshot[4],
        "bid": snapshot[5],
        "ask": snapshot[6],
        "mid": snapshot[7],
        "implied_probability": snapshot[8],
    }
    value_type = None
    value = None
    for candidate in ("price", "mid", "bid", "ask", "implied_probability"):
        candidate_value = fields[candidate]
        if candidate_value is not None:
            value_type = candidate
            value = candidate_value
            break
    return {
        "snapshot_id": fields["id"],
        "captured_at": fields["captured_at"],
        "source": fields["source"],
        "source_url": fields["source_url"],
        "value_type": value_type,
        "value": value,
        "price": fields["price"],
        "bid": fields["bid"],
        "ask": fields["ask"],
        "mid": fields["mid"],
        "implied_probability": fields["implied_probability"],
    }


def _latest_snapshot_mark_by_instrument(connection: Any, instrument_ids: set[str]) -> dict[str, dict[str, Any]]:
    marks: dict[str, dict[str, Any]] = {}
    for instrument_id in instrument_ids:
        snapshot = connection.execute(
            """
            SELECT id, captured_at, source, source_url, price, bid, ask, mid, implied_probability
            FROM snapshots
            WHERE instrument_id = ?
              AND (price IS NOT NULL OR bid IS NOT NULL OR ask IS NOT NULL
                   OR mid IS NOT NULL OR implied_probability IS NOT NULL)
            ORDER BY captured_at DESC, id DESC
            LIMIT 1
            """,
            (instrument_id,),
        ).fetchone()
        if snapshot is not None:
            marks[instrument_id] = _snapshot_latest_mark(snapshot)
    return marks


def _position_row_payload(row: Any, latest_mark: dict[str, Any] | None, *, stale_cutoff: datetime) -> dict[str, Any]:
    caveat_codes = _position_current_exposure_codes(row)
    mark_state = "missing"
    if latest_mark is not None:
        captured_at = _parse_report_timestamp(latest_mark["captured_at"], field="snapshots.captured_at")
        mark_state = "stale" if captured_at < stale_cutoff else "available"
        if mark_state == "stale" and "STALE_MARK" not in caveat_codes:
            caveat_codes.append("STALE_MARK")
        if "MISSING_MARK" in caveat_codes:
            caveat_codes.remove("MISSING_MARK")
    elif "MISSING_MARK" not in caveat_codes:
        mark_state = "missing"
    return {
        "position_id": row.position_id,
        "instrument_id": row.instrument_id,
        "instrument_symbol": row.instrument_symbol,
        "instrument_title": row.instrument_title,
        "venue_id": row.venue_id,
        "venue_kind": row.venue_kind,
        "kind": row.kind,
        "side": row.side,
        "status": row.status,
        "outcome": row.outcome,
        "net_quantity": row.net_quantity,
        "avg_entry_price": row.avg_entry_price,
        "opened_at": row.opened_at,
        "updated_at": row.updated_at,
        "closed_at": row.closed_at,
        "realized_pnl": row.realized_pnl,
        "unrealized_pnl": row.unrealized_pnl,
        "realized_r_multiple": row.realized_r_multiple,
        "unrealized_r_multiple": row.unrealized_r_multiple,
        "initial_risk_amount": row.initial_risk_amount,
        "opening_decision_id": row.opening_decision_id,
        "opening_strategy_id": row.opening_strategy_id,
        "opening_strategy_slug": row.opening_strategy_slug,
        "opening_playbook_version_id": row.opening_playbook_version_id,
        "event_counts": {
            "add": row.add_count,
            "reduce": row.reduce_count,
            "total": row.event_count,
        },
        "latest_mark": latest_mark,
        "mark_state": mark_state,
        "caveat_codes": caveat_codes,
        "read_model_caveats": list(row.caveats),
        "caveats": [
            {"code": entry.code, "label": entry.label, "summary": entry.summary, "severity": entry.severity}
            for entry in row.caveat_entries
        ],
    }


def _open_position_hints(count: int, caveat_codes: list[str]) -> list[str]:
    if count == 0:
        return ["Canonical open positions: zero."]
    hints = [
        f"Canonical open positions: {count} row(s) from positions projection, not inferred from decisions.",
    ]
    if "MISSING_MARK" in caveat_codes:
        hints.append("Some open positions are missing mark/P&L data; avoid summarizing unrealized P&L as complete.")
    if "STALE_MARK" in caveat_codes:
        hints.append("Some open positions have stale latest snapshot marks; treat mark-dependent exposure/P&L as caveated.")
    if "OPEN_ACTUAL_RECORDED_POSITION" in caveat_codes:
        hints.append("Actual-recorded rows are current exposure only because they have linked position projection/events.")
    return hints


def _unsupported_filter_to_tool_error(exc: UnsupportedFilterError) -> ToolError:
    """Translate a typed UnsupportedFilterError into a VALIDATION_ERROR
    envelope. The agent gets the offending leaf paths and the supported
    set so it can prune its input and retry."""

    return unsupported_filter_to_tool_error(exc)


def _propagate_report_meta(ctx: ToolContext, data: dict[str, Any]) -> None:
    """Promote standard report-meta fields off the data envelope onto
    `ctx.meta_hints` per contracts.md §3.2 / bead trade-trace-u5s.

    - `bin_policy`: emitted by `report.calibration`; null for every other
      report.
    - `truncated` / `next_cursor`: surfaced from any report that paginates
      groups.
    - `sample_warning`: the *summary*-level warning string (per-group
      warnings live in `data.groups[].sample_warning`).
    - Reproducibility (bead trade-trace-64q): `generated_at`,
      `schema_version`, `package_version`, `normalized_filter` populate
      so the agent can branch on stable run metadata.
    """

    summary = data.get("summary") or {}
    sample_warning = summary.get("sample_warning")
    if sample_warning is not None:
        ctx.meta_hints["sample_warning"] = sample_warning
    bin_policy = data.get("bin_policy")
    if bin_policy is not None:
        ctx.meta_hints["bin_policy"] = bin_policy
    if data.get("truncated"):
        ctx.meta_hints["truncated"] = True
    next_cursor = data.get("next_cursor")
    if next_cursor is not None:
        ctx.meta_hints["next_cursor"] = next_cursor
    # Reproducibility surface — populated for every report.* call.
    from trade_trace.tools._helpers import now_iso
    from trade_trace.version import __version__

    ctx.meta_hints["generated_at"] = now_iso()
    ctx.meta_hints["package_version"] = __version__
    # Normalized filter: the report functions echo it under
    # `summary.filter`; surface it on meta too so callers can read it
    # without parsing summary.
    if isinstance(summary.get("filter"), dict):
        ctx.meta_hints["normalized_filter"] = summary["filter"]


def _run_report_data(
    args: dict[str, Any],
    ctx: ToolContext,
    build: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    """Open/close the DB and propagate standard report meta for a tool call."""

    db = open_db_for_args(args)
    try:
        data = build(db.connection)
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _call_filter_report(
    fn: Callable[..., dict[str, Any]],
    connection: Any,
    *,
    raw_filter: dict[str, Any] | None,
) -> dict[str, Any]:
    """Call a report and preserve shared filter-error translation."""

    try:
        return fn(connection, raw_filter=raw_filter)
    except ValidationError as exc:
        raise report_filter_validation_to_tool_error(exc) from exc
    except UnsupportedFilterError as exc:
        raise _unsupported_filter_to_tool_error(exc) from exc


def _report_calibration(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.calibration` — Brier, log score, ECE, sharpness, baseline +
    skill, reliability bins over scored binary forecasts in the filtered
    set. Per scoring.md §7 / reports.md §4.1.

    Also embeds the anti-goodhart integrity diagnostics (bead trade-trace-jzn)
    under `data.integrity_diagnostics` so an agent reading the calibration
    panel sees the denominator coverage and hygiene signals (ambiguous /
    disputed / unsupported / suspicious_late) in the same envelope.
    """

    raw_filter = args.get("filter")
    min_sample = args.get("min_sample")
    db = open_db_for_args(args)
    try:
        try:
            data = report_calibration(
                db.connection,
                raw_filter=raw_filter,
                min_sample=min_sample if min_sample is not None else 20,
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
        # Embed integrity diagnostics in the panel so the panel can never
        # be read without the denominator/hygiene context.
        data["integrity_diagnostics"] = report_calibration_integrity(db.connection)
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_playbook_adherence(
    args: dict[str, Any], ctx: ToolContext,
) -> dict[str, Any]:
    """`report.playbook_adherence` — adherence aggregate from
    `decision_playbook_rules` (bead fbq). Optional top-level scoping
    knobs `playbook_id` and `strategy_id`; standard ReportFilter is
    accepted on the `filter` arg."""

    raw_filter = args.get("filter")
    playbook_id = args.get("playbook_id")
    strategy_id = args.get("strategy_id")
    db = open_db_for_args(args)
    try:
        if playbook_id is not None:
            pb_row = db.connection.execute(
                "SELECT 1 FROM playbooks WHERE id = ?", (playbook_id,),
            ).fetchone()
            if pb_row is None:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"playbook {playbook_id!r} not found",
                    details={
                        "entity_kind": "playbook",
                        "playbook_id": playbook_id,
                    },
                )
        try:
            data = report_playbook_adherence(
                db.connection, raw_filter=raw_filter,
                playbook_id=playbook_id, strategy_id=strategy_id,
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_source_quality(
    args: dict[str, Any], ctx: ToolContext,
) -> dict[str, Any]:
    """`report.source_quality` — provenance hygiene panel (bead trade-trace-l9q).

    Five diagnostics over the source attachment graph: missing sources
    on actual_enter decisions, stale sources, contradictory same-kind
    sources, duplicated content_hashes, and sensitive-redaction-status
    sources. Optional `stale_threshold_days` overrides the default 7.
    """

    stale_threshold_days = args.get("stale_threshold_days", 7)
    if not isinstance(stale_threshold_days, int) or stale_threshold_days < 0:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "stale_threshold_days must be a non-negative integer",
            details={"field": "stale_threshold_days",
                     "value": stale_threshold_days},
        )
    db = open_db_for_args(args)
    try:
        data = report_source_quality(
            db.connection, stale_threshold_days=stale_threshold_days,
        )
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_audit_readiness(
    args: dict[str, Any], ctx: ToolContext,
) -> dict[str, Any]:
    stale_snapshot_threshold_days = args.get("stale_snapshot_threshold_days", 1)
    stale_source_threshold_days = args.get("stale_source_threshold_days", 7)
    for field, value in (
        ("stale_snapshot_threshold_days", stale_snapshot_threshold_days),
        ("stale_source_threshold_days", stale_source_threshold_days),
    ):
        if not isinstance(value, int) or value < 0:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{field} must be a non-negative integer",
                details={"field": field, "value": value},
            )
    db = open_db_for_args(args)
    try:
        data = report_audit_readiness(
            db.connection,
            stale_snapshot_threshold_days=stale_snapshot_threshold_days,
            stale_source_threshold_days=stale_source_threshold_days,
        )
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_calibration_integrity(
    args: dict[str, Any], ctx: ToolContext,
) -> dict[str, Any]:
    """`report.calibration_integrity` — standalone surface for the six
    anti-goodhart diagnostics (bead trade-trace-jzn). Useful when an agent
    wants the hygiene panel without computing the calibration metrics
    (cheaper, and explicitly framed as "is the data clean enough to
    trust the calibration numbers?")."""

    db = open_db_for_args(args)
    try:
        data = report_calibration_integrity(db.connection)
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_unscored_forecasts(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.unscored_forecasts` — list pending binary forecasts past
    `resolution_at` with no resolved_final outcome on their instrument."""

    raw_filter = args.get("filter")
    db = open_db_for_args(args)
    try:
        try:
            data = report_unscored_forecasts(db.connection, raw_filter=raw_filter)
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_decision_velocity(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.decision_velocity` — bucketed decision counts (day or week)."""

    raw_filter = args.get("filter")
    bucket = args.get("bucket", "day")
    if bucket not in ("day", "week"):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"bucket must be 'day' or 'week'; got {bucket!r}",
            details={"field": "bucket", "value": bucket,
                     "allowed": ["day", "week"]},
        )
    db = open_db_for_args(args)
    try:
        try:
            data = report_decision_velocity(
                db.connection, raw_filter=raw_filter, bucket=bucket,
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_compare(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.compare` — compute a base report per deterministic group."""
    db = open_db_for_args(args)
    try:
        try:
            data = report_compare(
                db.connection,
                base_report=args.get("base_report", "calibration"),
                group_by=args.get("group_by", "strategy_id"),
                raw_filter=args.get("filter"),
                min_sample=args.get("min_sample"),
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except (UnsupportedFilterError, ValueError) as exc:
            if isinstance(exc, UnsupportedFilterError):
                raise _unsupported_filter_to_tool_error(exc) from exc
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                str(exc),
                details={"field": "base_report/group_by"},
            ) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_strategy_performance(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.strategy_performance` — wrapper over `report.compare`.

    trade-trace-4md decision: implemented as a convenience wrapper around
    `report.compare(base_report='pnl', group_by='strategy_id')` rather than a
    separate metric stack.
    """
    db = open_db_for_args(args)
    try:
        try:
            data = report_strategy_performance(
                db.connection,
                strategy_id=args.get("strategy_id"),
                raw_filter=args.get("filter"),
                min_sample=args.get("min_sample"),
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except (UnsupportedFilterError, ValueError) as exc:
            if isinstance(exc, UnsupportedFilterError):
                raise _unsupported_filter_to_tool_error(exc) from exc
            raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_opportunity(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.opportunity` — path-dependent decision/outcome diagnostics."""
    db = open_db_for_args(args)
    try:
        try:
            data = report_opportunity(
                db.connection,
                raw_filter=args.get("filter"),
                minimum_coverage=args.get("minimum_coverage", "sparse"),
                max_records=args.get("max_records", 100),
                include_labels=args.get("include_labels", True),
                min_sample=args.get("min_sample", 20),
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
        except ValueError as exc:
            raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _make_filter_only_report(fn):
    """Wrap a report function whose only optional arg is `filter` into a tool
    handler that validates and dispatches it."""

    def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        return _run_report_data(
            args,
            ctx,
            lambda connection: _call_filter_report(
                fn, connection, raw_filter=args.get("filter"),
            ),
        )

    return _handler


def _report_watchlist(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.watchlist` — list open watch decisions. `mode='stale'` opts in
    to the stale subset; `stale_threshold_days` overrides the default 14."""

    raw_filter = args.get("filter")
    mode = args.get("mode", "all")
    if mode not in ("all", "stale"):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"mode must be 'all' or 'stale'; got {mode!r}",
            details={"field": "mode", "value": mode, "allowed": ["all", "stale"]},
        )
    stale_threshold_days = args.get("stale_threshold_days", 14)
    db = open_db_for_args(args)
    try:
        try:
            data = report_watchlist(
                db.connection, raw_filter=raw_filter,
                stale=(mode == "stale"),
                stale_threshold_days=stale_threshold_days,
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_lifecycle(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.lifecycle` — derived lifecycle gaps/cases, read-only."""

    stale_threshold_days = args.get("stale_threshold_days", 14)
    if not isinstance(stale_threshold_days, int) or stale_threshold_days < 0:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "stale_threshold_days must be a non-negative integer", details={"field": "stale_threshold_days", "value": stale_threshold_days})
    states = args.get("states")
    status = args.get("status")
    if status is not None:
        if not isinstance(status, str):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "status must be a string", details={"field": "status", "value": status})
        states = [*(states or []), status]
    if states is not None and (not isinstance(states, list) or not all(isinstance(item, str) for item in states)):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "states must be a list of strings", details={"field": "states", "value": states})
    as_of_raw = args.get("as_of")
    if as_of_raw is not None and not isinstance(as_of_raw, str):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "as_of must be an ISO timestamp string", details={"field": "as_of", "value": as_of_raw})
    try:
        home = resolve_home(args.get("home"))
        path = db_path(home)
        if not path.exists():
            raise ToolError(ErrorCode.STORAGE_ERROR, "journal not initialized; run `tt journal init` first", details={"home": str(home), "db_path": str(path)})
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            data = report_lifecycle(
                connection,
                raw_filter=args.get("filter"),
                states=states,
                as_of=as_of_raw,
                stale_threshold_days=stale_threshold_days,
            )
        finally:
            connection.close()
        _propagate_report_meta(ctx, data)
        return data
    except ValidationError as exc:
        raise report_filter_validation_to_tool_error(exc) from exc
    except UnsupportedFilterError as exc:
        raise _unsupported_filter_to_tool_error(exc) from exc
    except ValueError as exc:
        raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc


def _report_open_positions(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.open_positions` — row-level current open exposure."""

    limit = args.get("limit")
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "limit must be a positive integer",
            details={"field": "limit", "value": limit},
        )
    kind = args.get("kind")
    if kind is not None and kind not in ("paper", "actual", "simulation"):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "kind must be one of: paper, actual, simulation",
            details={"field": "kind", "value": kind, "allowed": ["paper", "actual", "simulation"]},
        )
    stale_mark_threshold_days = args.get("stale_mark_threshold_days", 14)
    if not isinstance(stale_mark_threshold_days, int) or stale_mark_threshold_days < 0:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "stale_mark_threshold_days must be a non-negative integer",
            details={"field": "stale_mark_threshold_days", "value": stale_mark_threshold_days},
        )
    as_of_raw = args.get("as_of")
    if as_of_raw is None:
        as_of = datetime.now(UTC)
    elif isinstance(as_of_raw, str):
        as_of = _parse_report_timestamp(as_of_raw, field="as_of")
    else:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "as_of must be an ISO timestamp string",
            details={"field": "as_of", "value": as_of_raw},
        )
    stale_cutoff = as_of - timedelta(days=stale_mark_threshold_days)
    db = open_db_for_args(args)
    try:
        from trade_trace.reporting.position_rows import list_positions

        page = list_positions(
            db.connection,
            cursor=args.get("cursor"),
            limit=limit if limit is not None else 100,
            status=("open", "partial"),
            kind=kind,
            instrument_id=args.get("instrument_id"),
            strategy_id=args.get("strategy_id"),
        )
        latest_marks = _latest_snapshot_mark_by_instrument(
            db.connection,
            {row.instrument_id for row in page.rows},
        )
    finally:
        db.close()

    rows = [
        _position_row_payload(
            row,
            latest_marks.get(row.instrument_id),
            stale_cutoff=stale_cutoff,
        )
        for row in page.rows
    ]
    caveat_codes = sorted({code for row in rows for code in row["caveat_codes"]})
    if not rows:
        caveat_codes = ["NO_OPEN_POSITIONS"]
    hints = _open_position_hints(len(rows), caveat_codes)
    data = {
        "summary": {
            "bucket": "open_positions",
            "count": len(rows),
            "open_position_count": len(rows),
            "filter": {
                "status": ["open", "partial"],
                "kind": kind,
                "instrument_id": args.get("instrument_id"),
                "strategy_id": args.get("strategy_id"),
                "limit": page.limit,
                "cursor": args.get("cursor"),
                "stale_mark_threshold_days": stale_mark_threshold_days,
                "as_of": to_utc_iso8601(as_of),
            },
            "caveat_codes": caveat_codes,
            "agent_answer_hints": hints,
        },
        "groups": [],
        "open_positions": rows,
        "agent_answer_hints": hints,
        "truncated": page.next_cursor is not None,
        "next_cursor": page.next_cursor,
    }
    _propagate_report_meta(ctx, data)
    return data


_RECORD_ONLY_TERMS = (
    "record-only",
    "record only",
    "not external",
    "not externally executed",
    "journal-only",
    "journal only",
    "manual record",
    "dogfood",
    "simulated",
)


def _exposure_anomaly(code: str, summary: str, affected_ids: dict[str, list[str]], evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "category": "data_quality",
        "severity": "warning",
        "summary": summary,
        "affected_ids": affected_ids,
        "evidence": evidence,
    }


def _report_exposure_anomalies(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.exposure_anomalies` — current-exposure ambiguity caveats."""

    stale_mark_threshold_days = args.get("stale_mark_threshold_days", 14)
    if not isinstance(stale_mark_threshold_days, int) or stale_mark_threshold_days < 0:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "stale_mark_threshold_days must be a non-negative integer",
            details={"field": "stale_mark_threshold_days", "value": stale_mark_threshold_days},
        )
    as_of_raw = args.get("as_of")
    if as_of_raw is None:
        as_of = datetime.now(UTC)
    elif isinstance(as_of_raw, str):
        as_of = _parse_report_timestamp(as_of_raw, field="as_of")
    else:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "as_of must be an ISO timestamp string",
            details={"field": "as_of", "value": as_of_raw},
        )
    stale_cutoff = as_of - timedelta(days=stale_mark_threshold_days)
    anomalies: list[dict[str, Any]] = []

    db = open_db_for_args(args)
    try:
        connection = db.connection
        decisions = connection.execute(
            """
            SELECT d.id, d.instrument_id, d.type, d.side, d.quantity, d.price,
                   d.run_id, d.reason, d.metadata_json, d.created_at,
                   COUNT(pe.id) AS event_count
            FROM decisions d
            LEFT JOIN position_events pe ON pe.decision_id = d.id
            WHERE d.type IN ('paper_enter','actual_enter','actual_exit','add','reduce')
            GROUP BY d.id
            ORDER BY d.created_at, d.id
            """
        ).fetchall()
        for row in decisions:
            payload = {
                "decision_id": row[0], "instrument_id": row[1], "type": row[2],
                "side": row[3], "quantity": row[4], "price": row[5],
                "run_id": row[6], "created_at": row[9], "linked_position_event_count": row[10],
            }
            if row[2] in ("paper_enter", "actual_enter", "add") and row[10] == 0:
                anomalies.append(_exposure_anomaly(
                    "ENTRY_DECISION_WITHOUT_POSITION_EVENT",
                    "Entry decision lacks linked position_events row; do not count as exposure.",
                    {"decisions": [row[0]], "instruments": [row[1]]},
                    payload,
                ))
            if row[2] in ("actual_enter", "actual_exit", "add", "reduce") and row[10] == 0:
                text = f"{row[7] or ''} {row[8] or ''}".lower()
                matched = [term for term in _RECORD_ONLY_TERMS if term in text]
                evidence = {**payload, "record_only_phrase_matches": matched}
                anomalies.append(_exposure_anomaly(
                    "RECORD_ONLY_ACTUAL",
                    "Actual-recorded/add/reduce/exit decision has no linked position_event/projection lineage; treat as journal activity, not open exposure.",
                    {"decisions": [row[0]], "instruments": [row[1]]},
                    evidence,
                ))

        dupes = connection.execute(
            """
            SELECT instrument_id, type, COALESCE(side,''), COALESCE(quantity,''), COALESCE(price,''),
                   COALESCE(run_id,''), COUNT(*) AS n, GROUP_CONCAT(id), MIN(created_at), MAX(created_at)
            FROM decisions
            WHERE type IN ('paper_enter','actual_enter','add')
            GROUP BY instrument_id, type, COALESCE(side,''), COALESCE(quantity,''), COALESCE(price,''), COALESCE(run_id,'')
            HAVING COUNT(*) > 1
            ORDER BY MIN(created_at), instrument_id, type
            """
        ).fetchall()
        for row in dupes:
            decision_ids = row[7].split(",") if row[7] else []
            anomalies.append(_exposure_anomaly(
                "DUPLICATE_DECISIONS",
                "Duplicate entry-like journal decisions found; exposure should be based only on linked position projection/events.",
                {"decisions": decision_ids, "instruments": [row[0]]},
                {"instrument_id": row[0], "type": row[1], "side": row[2] or None,
                 "quantity": row[3] or None, "price": row[4] or None, "run_id": row[5] or None,
                 "count": row[6], "first_created_at": row[8], "last_created_at": row[9]},
            ))

        open_positions = connection.execute(
            """
            SELECT id, instrument_id, kind, side, status, unrealized_pnl, updated_at
            FROM positions
            WHERE status IN ('open','partial')
            ORDER BY updated_at, id
            """
        ).fetchall()
        latest_marks = _latest_snapshot_mark_by_instrument(connection, {row[1] for row in open_positions})
        for row in open_positions:
            mark = latest_marks.get(row[1])
            base = {"position_id": row[0], "instrument_id": row[1], "kind": row[2], "side": row[3], "status": row[4], "updated_at": row[6]}
            if row[5] is None and mark is None:
                anomalies.append(_exposure_anomaly(
                    "MISSING_MARK",
                    "Open/partial position has no unrealized P&L and no latest snapshot/mark.",
                    {"positions": [row[0]], "instruments": [row[1]]},
                    base,
                ))
            elif mark is not None:
                captured_at = _parse_report_timestamp(mark["captured_at"], field="snapshots.captured_at")
                if captured_at < stale_cutoff:
                    anomalies.append(_exposure_anomaly(
                        "STALE_MARK",
                        "Open/partial position latest snapshot/mark is stale as of the report threshold.",
                        {"positions": [row[0]], "instruments": [row[1]], "snapshots": [mark["snapshot_id"]]},
                        {**base, "latest_mark": mark},
                    ))

        stale_projection = connection.execute(
            """
            SELECT p.id, p.instrument_id, p.updated_at, MAX(pe.created_at) AS latest_event_at
            FROM positions p
            JOIN position_events pe ON pe.position_id = p.id
            GROUP BY p.id
            HAVING latest_event_at > p.updated_at
            ORDER BY latest_event_at, p.id
            """
        ).fetchall()
        for row in stale_projection:
            anomalies.append(_exposure_anomaly(
                "PROJECTION_STALE",
                "positions projection predates later position_events; rebuild/check projections before relying on exposure.",
                {"positions": [row[0]], "instruments": [row[1]]},
                {"position_id": row[0], "instrument_id": row[1], "position_updated_at": row[2], "latest_event_at": row[3]},
            ))

        missing_projection = connection.execute(
            """
            SELECT pe.position_id, pe.instrument_id, GROUP_CONCAT(pe.id), MIN(pe.created_at), MAX(pe.created_at)
            FROM position_events pe
            LEFT JOIN positions p ON p.id = pe.position_id
            WHERE p.id IS NULL
            GROUP BY pe.position_id, pe.instrument_id
            ORDER BY MIN(pe.created_at), pe.position_id
            """
        ).fetchall()
        for row in missing_projection:
            anomalies.append(_exposure_anomaly(
                "PROJECTION_MISSING",
                "position_events exist for a position_id with no readable positions projection row.",
                {"positions": [row[0]], "instruments": [row[1]], "position_events": row[2].split(",") if row[2] else []},
                {"position_id": row[0], "instrument_id": row[1], "first_event_at": row[3], "latest_event_at": row[4]},
            ))
    finally:
        db.close()

    codes = sorted({item["code"] for item in anomalies})
    if anomalies:
        hints = [
            "Projection/data-quality caveats found; do not infer open trades from decisions-only evidence.",
            "These anomalies are local journal/projection caveats, not market risk or broker truth.",
        ]
    else:
        hints = [
            "No projection anomalies detected; use canonical position reports for current exposure.",
            "Clean result does not query brokers or prove external market risk.",
        ]
    data = {
        "summary": {
            "bucket": "projection_anomalies",
            "count": len(anomalies),
            "anomaly_count": len(anomalies),
            "codes": codes,
            "severity_counts": {"data_quality": len(anomalies), "market_risk": 0},
            "agent_answer_hints": hints,
            "filter": {"stale_mark_threshold_days": stale_mark_threshold_days, "as_of": to_utc_iso8601(as_of)},
        },
        "groups": [],
        "projection_anomalies": anomalies,
        "agent_answer_hints": hints,
    }
    _propagate_report_meta(ctx, data)
    return data


def _watchlist_rows_for_current_exposure(watch_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in watch_data.get("groups", []):
        record_ids = group.get("record_ids") or {}
        examples = group.get("examples") or []
        metrics = group.get("metrics") or {}
        rows.append({
            "decision_id": (record_ids.get("decisions") or [group.get("key")])[0],
            "instrument_id": (record_ids.get("instruments") or [None])[0],
            "reason": examples[0].get("summary") if examples else None,
            "created_at": metrics.get("created_at"),
            "review_by": metrics.get("review_by"),
            "overdue": metrics.get("overdue"),
            "age_days": metrics.get("age_days"),
            "caveat_codes": ["WATCH_ONLY_IDEA"],
            "exposure_hint": "Watch idea only; not counted as exposure.",
        })
    return rows


def _watchlist_for_current_exposure(
    connection: Any,
    *,
    instrument_id: str | None,
    strategy_id: str | None,
    kind: str | None,
) -> list[dict[str, Any]]:
    """Return watch rows scoped to current_exposure's packet-level filters."""

    # Watch rows are explicitly not exposure and have no paper/actual/simulation kind.
    # When a caller asks for a kind-scoped exposure packet, omitting watch rows is
    # safer than leaking unkinded ideas into a supposedly scoped answer.
    if kind is not None:
        return []

    clauses = ["d.type = 'watch'"]
    params: list[Any] = []
    if instrument_id is not None:
        clauses.append("d.instrument_id = ?")
        params.append(instrument_id)
    if strategy_id is not None:
        clauses.append("d.strategy_id = ?")
        params.append(strategy_id)

    rows = connection.execute(
        f"""
        SELECT d.id, d.instrument_id, d.strategy_id, d.reason, d.created_at, d.review_by
        FROM decisions d
        WHERE {' AND '.join(clauses)}
        ORDER BY d.created_at DESC, d.id DESC
        """,
        tuple(params),
    ).fetchall()
    return [
        {
            "decision_id": row[0],
            "instrument_id": row[1],
            "strategy_id": row[2],
            "reason": row[3],
            "created_at": row[4],
            "review_by": row[5],
            "overdue": False,
            "age_days": None,
            "caveat_codes": ["WATCH_ONLY_IDEA"],
            "exposure_hint": "Watch idea only; not counted as exposure.",
        }
        for row in rows
    ]


def _kind_decision_types(kind: str | None) -> tuple[str, ...]:
    if kind == "paper":
        return ("paper_enter", "paper_exit")
    if kind == "actual":
        return ("actual_enter", "actual_exit", "add", "reduce")
    if kind == "simulation":
        return ()
    return ("paper_enter", "paper_exit", "actual_enter", "actual_exit", "add", "reduce")


def _recent_trade_activity(
    connection: Any,
    *,
    recent_limit: int,
    instrument_id: str | None = None,
    strategy_id: str | None = None,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    if recent_limit == 0:
        return []
    decision_types = _kind_decision_types(kind)
    if not decision_types:
        return []
    clauses = [f"d.type IN ({','.join('?' for _ in decision_types)})"]
    params: list[Any] = list(decision_types)
    if instrument_id is not None:
        clauses.append("d.instrument_id = ?")
        params.append(instrument_id)
    if strategy_id is not None:
        clauses.append("d.strategy_id = ?")
        params.append(strategy_id)
    params.append(recent_limit)

    rows = connection.execute(
        f"""
        SELECT d.id, d.instrument_id, d.thesis_id, d.forecast_id, d.snapshot_id,
               d.type, d.side, d.quantity, d.price, d.created_at, d.reason,
               d.strategy_id, d.run_id, COUNT(pe.id) AS event_count
        FROM decisions d
        LEFT JOIN position_events pe ON pe.decision_id = d.id
        WHERE {' AND '.join(clauses)}
        GROUP BY d.id
        ORDER BY d.created_at DESC, d.id DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    activity = []
    for row in rows:
        caveat_codes = ["JOURNAL_ACTIVITY_NOT_CANONICAL_EXPOSURE"]
        if row[5] in ("actual_enter", "actual_exit", "add", "reduce") and row[13] == 0:
            caveat_codes.append("RECORD_ONLY_ACTUAL")
        activity.append({
            "decision_id": row[0],
            "instrument_id": row[1],
            "thesis_id": row[2],
            "forecast_id": row[3],
            "snapshot_id": row[4],
            "type": row[5],
            "side": row[6],
            "quantity": row[7],
            "price": row[8],
            "created_at": row[9],
            "reason": row[10],
            "strategy_id": row[11],
            "run_id": row[12],
            "linked_position_event_count": row[13],
            "caveat_codes": caveat_codes,
            "exposure_hint": "Recent journal activity is not canonical open exposure by itself; use open_positions for exposure.",
        })
    return activity


def _filter_current_exposure_anomalies(
    connection: Any,
    anomalies: list[dict[str, Any]],
    *,
    instrument_id: str | None,
    strategy_id: str | None,
    kind: str | None,
) -> list[dict[str, Any]]:
    """Scope anomaly rows to current_exposure's packet-level filters."""

    if instrument_id is None and strategy_id is None and kind is None:
        return anomalies

    decision_rows = connection.execute("SELECT id, instrument_id, strategy_id, type FROM decisions").fetchall()
    decision_info = {row[0]: {"instrument_id": row[1], "strategy_id": row[2], "type": row[3]} for row in decision_rows}
    position_rows = connection.execute(
        """
        SELECT p.id, p.instrument_id, p.kind, d.strategy_id
        FROM positions p
        LEFT JOIN position_events pe ON pe.position_id = p.id AND pe.event_type = 'open'
        LEFT JOIN decisions d ON d.id = pe.decision_id
        GROUP BY p.id
        """
    ).fetchall()
    position_info = {row[0]: {"instrument_id": row[1], "kind": row[2], "strategy_id": row[3]} for row in position_rows}

    def matches(anomaly: dict[str, Any]) -> bool:
        affected = anomaly.get("affected_ids") or {}
        evidence = anomaly.get("evidence") or {}
        insts = set(affected.get("instruments") or [])
        if evidence.get("instrument_id") is not None:
            insts.add(evidence["instrument_id"])
        decisions = set(affected.get("decisions") or [])
        if evidence.get("decision_id") is not None:
            decisions.add(evidence["decision_id"])
        positions = set(affected.get("positions") or [])
        if evidence.get("position_id") is not None:
            positions.add(evidence["position_id"])

        if instrument_id is not None:
            related_insts = set(insts)
            related_insts.update(info["instrument_id"] for did, info in decision_info.items() if did in decisions)
            related_insts.update(info["instrument_id"] for pid, info in position_info.items() if pid in positions)
            if instrument_id not in related_insts:
                return False
        if strategy_id is not None:
            related_strategies = {info["strategy_id"] for did, info in decision_info.items() if did in decisions}
            related_strategies.update(info["strategy_id"] for pid, info in position_info.items() if pid in positions)
            if strategy_id not in related_strategies:
                return False
        if kind is not None:
            related_kinds = {info["kind"] for pid, info in position_info.items() if pid in positions}
            related_types = {info["type"] for did, info in decision_info.items() if did in decisions}
            if not related_kinds and related_types:
                if related_types <= {"paper_enter", "paper_exit"}:
                    related_kinds.add("paper")
                elif related_types <= {"actual_enter", "actual_exit", "add", "reduce"}:
                    related_kinds.add("actual")
            if kind not in related_kinds:
                return False
        return True

    return [anomaly for anomaly in anomalies if matches(anomaly)]


def _current_exposure_hints(open_count: int, watch_count: int, recent_count: int, anomaly_count: int) -> list[str]:
    hints = [f"Canonical open positions: {open_count}."]
    if open_count == 0 and recent_count:
        hints[0] = "Canonical open positions: zero; recent journal entries exist but are not open exposure."
    if watch_count:
        hints.append("Watchlist rows are WATCH_ONLY_IDEA; do not count them as exposure.")
    if recent_count:
        hints.append("Recent trade activity is an audit/journal trail; it can explain trading but does not define current exposure.")
    if anomaly_count:
        hints.append("Projection anomalies caveat the answer; do not infer open trades from decisions-only evidence.")
    if open_count == 0 and watch_count == 0 and recent_count == 0 and anomaly_count == 0:
        hints.append("No watch ideas, recent trade activity, or projection anomalies found in the local journal.")
    hints.append("Trade Trace reports local journal/projection state only; it does not assert broker or external portfolio truth.")
    return hints


def _report_current_exposure(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.current_exposure` — trader-agent packet for exposure questions."""

    recent_limit = args.get("recent_limit", 10)
    if not isinstance(recent_limit, int) or recent_limit < 0:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "recent_limit must be a non-negative integer", details={"field": "recent_limit", "value": recent_limit})
    include_watchlist = args.get("include_watchlist", True)
    include_anomalies = args.get("include_anomalies", True)
    if not isinstance(include_watchlist, bool):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "include_watchlist must be a boolean", details={"field": "include_watchlist", "value": include_watchlist})
    if not isinstance(include_anomalies, bool):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "include_anomalies must be a boolean", details={"field": "include_anomalies", "value": include_anomalies})

    open_args = {k: v for k, v in args.items() if k in {"home", "limit", "kind", "instrument_id", "strategy_id", "stale_mark_threshold_days", "as_of"}}
    open_data = _report_open_positions(open_args, ctx)
    anomaly_args = {k: v for k, v in args.items() if k in {"home", "stale_mark_threshold_days", "as_of"}}
    anomaly_data = _report_exposure_anomalies(anomaly_args, ctx) if include_anomalies else None

    db = open_db_for_args(args)
    try:
        watchlist = _watchlist_for_current_exposure(
            db.connection,
            instrument_id=args.get("instrument_id"),
            strategy_id=args.get("strategy_id"),
            kind=args.get("kind"),
        ) if include_watchlist else []
        recent_activity = _recent_trade_activity(
            db.connection,
            recent_limit=recent_limit,
            instrument_id=args.get("instrument_id"),
            strategy_id=args.get("strategy_id"),
            kind=args.get("kind"),
        )
        anomalies = _filter_current_exposure_anomalies(
            db.connection,
            anomaly_data.get("projection_anomalies", []) if anomaly_data is not None else [],
            instrument_id=args.get("instrument_id"),
            strategy_id=args.get("strategy_id"),
            kind=args.get("kind"),
        )
    finally:
        db.close()

    open_positions = open_data.get("open_positions", [])
    hints = _current_exposure_hints(len(open_positions), len(watchlist), len(recent_activity), len(anomalies))
    data = {
        "summary": {
            "bucket": "current_exposure",
            "buckets": ["open_positions", "watchlist", "recent_trade_activity", "projection_anomalies"],
            "open_position_count": open_data.get("summary", {}).get("open_position_count", len(open_positions)),
            "watch_count": len(watchlist),
            "recent_trade_decision_count": len(recent_activity),
            "anomaly_count": len(anomalies),
            "filter": {
                "kind": args.get("kind"),
                "instrument_id": args.get("instrument_id"),
                "strategy_id": args.get("strategy_id"),
                "recent_limit": recent_limit,
                "include_watchlist": include_watchlist,
                "include_anomalies": include_anomalies,
                "stale_mark_threshold_days": args.get("stale_mark_threshold_days", 14),
                "as_of": args.get("as_of"),
            },
            "agent_answer_hints": hints,
        },
        "groups": [],
        "open_positions": open_positions,
        "watchlist": watchlist,
        "recent_trade_activity": recent_activity,
        "projection_anomalies": anomalies,
        "agent_answer_hints": hints,
        "lower_level_reports": {
            "open_positions": "report.open_positions",
            "watchlist": "report.watchlist",
            "projection_anomalies": "report.exposure_anomalies",
        },
    }
    _propagate_report_meta(ctx, data)
    return data


def _report_coach(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.coach` — synthesized decision-support packet. No LLM, no
    network, no trade advice."""

    raw_filter = args.get("filter")
    stale_threshold_days = args.get("stale_threshold_days", 14)
    db = open_db_for_args(args)
    try:
        try:
            data = report_coach(
                db.connection, raw_filter=raw_filter,
                stale_threshold_days=stale_threshold_days,
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
        except TradingAdvicePhraseError as exc:
            raise ToolError(
                ErrorCode.INVARIANT_VIOLATION,
                str(exc),
                details={"forbidden_matches": exc.matches},
            ) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_filter_schema(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Return the canonical Pydantic-generated JSON Schema for ReportFilter.

    Optional `mode` arg: `"validation"` (default) or `"serialization"`.
    Validation mode reflects what the server accepts on a tool call;
    serialization mode reflects what the server emits on echo (e.g. in
    a `ReportResult.summary.filter` field). For ReportFilter the two
    differ only in `Optional` handling — both shapes are useful for
    agents building UIs over the surface.
    """

    mode = args.get("mode", "validation")
    if mode not in ("validation", "serialization"):
        from trade_trace.contracts.errors import ErrorCode
        from trade_trace.tools.errors import ToolError

        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"mode must be 'validation' or 'serialization'; got {mode!r}",
            details={"field": "mode", "value": mode,
                     "allowed": ["validation", "serialization"]},
        )

    schema = ReportFilter.model_json_schema(mode=mode)
    return {
        "schema": schema,
        "mode": mode,
        "strategy_id_sentinel": {
            "value": "__none__",
            "meaning": "Select rows where strategy_id IS NULL.",
        },
    }


def register_report_tools(registry: ToolRegistry) -> None:
    """Register `report.*` tools on the supplied registry.

    Currently registers only `report.filter_schema`; the 7 deterministic
    reports + the coach are wired in their dedicated beads."""

    registry.register(
        "report.filter_schema",
        _report_filter_schema,
        description=(
            "Return the canonical JSON Schema for ReportFilter (the shared "
            "input shape for every report.* tool). Optional `mode` arg "
            "(`validation` default or `serialization`). Surfaces the "
            "`__none__` sentinel meaning for `strategy.strategy_id` so "
            "agents can build filter UIs without reading the docs."
        ),
        json_schema=_REPORT_SCHEMAS["report.filter_schema"],
    )
    registry.register(
        "report.calibration",
        _report_calibration,
        description=(
            "Calibration metric panel over scored binary forecasts: Brier, "
            "log score, ECE (equal-width 0.1 bins), sharpness, baseline + "
            "skill, plus reliability bins (scoring.md §7). Excludes "
            "late-recorded forecasts by default per dogfood-protocol §2.2 "
            "(opt in via filter.outcome.include_late_recorded). Emits a "
            "sample_warning when N < min_sample (default 20). Embeds the "
            "six anti-goodhart hygiene diagnostics from "
            "report.calibration_integrity under data.integrity_diagnostics."
        ),
        json_schema=_REPORT_SCHEMAS["report.calibration"]
    )
    registry.register(
        "report.playbook_adherence",
        _report_playbook_adherence,
        description=(
            "Playbook adherence aggregate from decision_playbook_rules "
            "(no JSON parsing). Per-group metrics: counts of considered / "
            "followed / overridden / not_applicable. Optional scoping: "
            "playbook_id (single playbook), strategy_id (single strategy "
            "across decisions). Per bead fbq."
        ),
        json_schema=_REPORT_SCHEMAS["report.playbook_adherence"]
    )
    registry.register(
        "report.source_quality",
        _report_source_quality,
        description=(
            "Provenance hygiene diagnostics over attached sources "
            "(bead trade-trace-l9q): missing_sources_on_actual_enter, "
            "stale_sources, contradictory_sources, duplicated_sources, "
            "sensitive_sources. Each emits {count,sample_ids,samples,"
            "truncated}. stale_threshold_days defaults to 7. No external "
            "fetching, no credibility scoring."
        ),
        example_minimal={"stale_threshold_days": 7},
        optional_keys=("stale_threshold_days",),
        json_schema=_REPORT_SCHEMAS["report.source_quality"]
    )
    registry.register(
        "report.audit_readiness",
        _report_audit_readiness,
        description=(
            "Read-only prediction/event-market audit-readiness diagnostics: "
            "resolution-rule provenance, snapshot age, market microstructure, "
            "source freshness/contradictions, and decision provenance. "
            "Deterministic local report; no network and no trading advice."
        ),
        example_minimal={"stale_snapshot_threshold_days": 1, "stale_source_threshold_days": 7},
        optional_keys=("stale_snapshot_threshold_days", "stale_source_threshold_days"),
        json_schema=_REPORT_SCHEMAS["report.audit_readiness"],
    )
    registry.register(
        "report.calibration_integrity",
        _report_calibration_integrity,
        description=(
            "Anti-goodhart hygiene diagnostics for the calibration panel "
            "(bead trade-trace-jzn): forecast_coverage, unsupported_rate, "
            "ambiguous_rate, disputed_rate, void_cancelled_rate, "
            "suspicious_late_rate. Each diagnostic returns "
            "{count,total,rate_pct,sample_ids,truncated}; the summary "
            "carries denominator context (total_decisions, total_forecasts, "
            "scored_forecasts, denominator_coverage_pct). Empty DBs surface "
            "sample_warning='no_data'."
        ),
        json_schema=_REPORT_SCHEMAS["report.calibration_integrity"]
    )
    registry.register(
        "report.unscored_forecasts",
        _report_unscored_forecasts,
        description=(
            "List pending binary forecasts past resolution_at whose "
            "instrument has no resolved_final (non-superseded) outcome. "
            "Mirrors signal.scan kind=unscored_forecast (trade-trace-2ry) "
            "but returns the rows for direct action."
        ),
        example_minimal={"filter": {}},
        optional_keys=("filter",),
        json_schema=_REPORT_SCHEMAS["report.unscored_forecasts"]
    )
    registry.register(
        "report.decision_velocity",
        _report_decision_velocity,
        description=(
            "Decision counts bucketed by day or week over the filter's "
            "decision_at_* window. Bucket boundaries are UTC-aligned; "
            "groups[] are ordered by bucket key ascending."
        ),
        json_schema=_REPORT_SCHEMAS["report.decision_velocity"]
    )
    registry.register(
        "report.mistakes",
        _make_filter_only_report(report_mistakes),
        description=(
            "Tag-aggregated recurring patterns ranked by mean Brier of "
            "associated scored forecasts (worst first). Per-group metrics: "
            "decision_count, scored_forecast_count, mean_brier."
        ),
        json_schema=_REPORT_SCHEMAS["report.mistakes"]
    )
    registry.register(
        "report.strengths",
        _make_filter_only_report(report_strengths),
        description=(
            "Tag-aggregated patterns ranked by mean Brier (best first). "
            "Mirror of report.mistakes."
        ),
        json_schema=_REPORT_SCHEMAS["report.strengths"]
    )
    registry.register(
        "report.pnl",
        _make_filter_only_report(report_pnl),
        description=(
            "Realized + unrealized + mark-to-market P&L over the positions "
            "projection. Per-instrument groups; summary carries "
            "open_mark_coverage (open positions with marks / open positions). "
            "Reads the rebuildable positions projection (trade-trace-5zg). "
            "This is a lower-level P&L report: for open trades/current exposure, "
            "start with report.current_exposure; for row-level open-position detail, "
            "use report.open_positions. Trade Trace records local journal/projection "
            "state only; it does not execute trades or prove broker portfolio truth."
        ),
        json_schema=_REPORT_SCHEMAS["report.pnl"],
        usage_summary=(
            "Use for realized/unrealized/MTM P&L over local projection rows. Do not use as the first source for "
            "open trades/current exposure; start with report.current_exposure or report.open_positions."
        ),
        examples=(
            "tt report pnl --home <journal-home>",
            "tt report current_exposure --home <journal-home>",
            "tt report open_positions --home <journal-home>",
        ),
        next_actions=(
            "If summary.metrics.open_position_count > 0, run report.current_exposure for the recommended agent packet or report.open_positions for row-level open-position detail.",
            "State that P&L/open-position rows are local journal/projection records; Trade Trace does not execute trades or prove broker portfolio truth.",
        ),
    )
    registry.register(
        "report.risk",
        _make_filter_only_report(report_risk),
        description=(
            "R-multiple aggregate over decisions that declared a risk "
            "budget (risk-units.md / bead trade-trace-8z2). Reports mean/"
            "median R, expectancy in R, win rate, payoff ratio, best/worst R, "
            "histogram bins, and counts of win/loss/breakeven. Decisions "
            "without declared_risk_amount are excluded from the aggregate and "
            "counted in caveats so the agent can chase the gap. Pending "
            "positions (declared risk but not closed) are surfaced separately "
            "in metrics.n_pending_with_risk."
        ),
        json_schema=_REPORT_SCHEMAS["report.risk"]
    )
    registry.register(
        "report.opportunity",
        _report_opportunity,
        description=(
            "Path-dependent opportunity diagnostics over supplied snapshots: "
            "reconstructs post-decision paths, emits max favorable/adverse "
            "moves, exit-efficiency, data_coverage, sparse/missing snapshot "
            "caveats, and documented labels such as missed_positive_edge, "
            "good_skip, right_thesis_wrong_timing, bad_process_good_outcome, "
            "and good_process_bad_outcome. No external price fetching. All "
            "arguments are optional; defaults apply for omitted keys per bead "
            "trade-trace-4zbk."
        ),
        example_minimal={
            "filter": {},
            "minimum_coverage": "sparse",
            "max_records": 100,
            "include_labels": True,
            "min_sample": 20,
        },
        optional_keys=(
            "filter",
            "minimum_coverage",
            "max_records",
            "include_labels",
            "min_sample",
        ),
        json_schema=_REPORT_SCHEMAS["report.opportunity"]
    )
    registry.register(
        "report.compare",
        _report_compare,
        description=(
            "Compare base report metrics across one allowlisted group_by. "
            "Supported base_report values: calibration and pnl. Supported "
            "group_by depends on base_report and is validated via fixed SQL "
            "allowlists for injection safety. Per-group sample_warning is "
            "emitted; summary.sample_warning is set when any group is low-N."
        ),
        example_minimal={"base_report": "calibration", "group_by": "strategy_id", "filter": {}},
        json_schema=_REPORT_SCHEMAS["report.compare"],
        usage_summary="Compare calibration or pnl metrics across one allowlisted dimension using optional shared report filters.",
        examples=("tt report compare --base-report calibration --group-by strategy_id --filter-json '{}'",),
        enum_notes={"base_report": "calibration or pnl", "group_by": "Allowed values depend on base_report and are validated by the report schema."},
        common_failures=("group_by is not allowed for the selected base_report.",),
        next_actions=("Use report.filter_schema to build the filter object before calling report.compare.",),
    )
    registry.register(
        "report.strategy_performance",
        _report_strategy_performance,
        description=(
            "Convenience wrapper implemented as report.compare with "
            "base_report='pnl' and group_by='strategy_id'. Optional "
            "strategy_id narrows to a single strategy; omitted compares all "
            "strategies including the __none__ no-strategy bucket."
        ),
        example_minimal={"strategy_id": "strat_example", "filter": {}},
        json_schema=_REPORT_SCHEMAS["report.strategy_performance"]
    )
    registry.register(
        "report.watchlist",
        _report_watchlist,
        description=(
            "List `watch`-type decisions. mode='all' (default) returns every "
            "watch; mode='stale' returns watches older than "
            "stale_threshold_days (default 14)."
        ),
        example_minimal={"filter": {}, "mode": "all", "stale_threshold_days": 14},
        optional_keys=("filter", "mode", "stale_threshold_days"),
        json_schema=_REPORT_SCHEMAS["report.watchlist"]
    )
    registry.register(
        "report.lifecycle",
        _report_lifecycle,
        description=(
            "Read-only derived lifecycle report for local decision, forecast, and material non-action cases. "
            "Returns lifecycle_cases and groups with stable states/status, reason/caveat codes, source_refs, "
            "record_ids, due_at, thresholds, and timestamps. Supports ReportFilter strategy/instrument/run/date "
            "plus states/status, as_of, and stale_threshold_days. No writes, no scheduling, no recommendations."
        ),
        example_minimal={"filter": {}, "states": ["pending_review"], "as_of": "2026-01-20T00:00:00Z", "stale_threshold_days": 14},
        optional_keys=("filter", "states", "status", "as_of", "stale_threshold_days"),
        json_schema=_REPORT_SCHEMAS["report.lifecycle"],
    )
    registry.register(
        "report.open_positions",
        _report_open_positions,
        description=(
            "Row-level open trades/current exposure from the canonical "
            "positions projection and position_events lineage. Defaults to "
            "open/partial positions only; closed positions are excluded. "
            "Agents must not infer current exposure from unclosed decisions, "
            "watch decisions, or record-only actual decisions without a linked "
            "position projection/event. Returns positive empty results with "
            "count=0 and NO_OPEN_POSITIONS."
        ),
        example_minimal={"limit": 100},
        optional_keys=(
            "limit",
            "cursor",
            "kind",
            "instrument_id",
            "strategy_id",
            "stale_mark_threshold_days",
            "as_of",
        ),
        json_schema=_REPORT_SCHEMAS["report.open_positions"],
        usage_summary="List canonical row-level open positions/current exposure; do not query or infer from decisions.",
        examples=("tt report open_positions --home <journal-home>",),
        next_actions=("Use these rows directly to summarize open exposure; do not run raw SQLite for open positions.",),
    )
    registry.register(
        "report.exposure_anomalies",
        _report_exposure_anomalies,
        description=(
            "Read-only current-exposure ambiguity/data-quality caveat report. "
            "Surfaces projection_anomalies with stable codes for duplicate entry "
            "decisions, decisions without linked position_events, record-only actual "
            "journal rows, missing/stale marks, and missing/stale projections. "
            "This is not market risk and does not assert broker truth."
        ),
        example_minimal={"stale_mark_threshold_days": 14},
        optional_keys=("stale_mark_threshold_days", "as_of"),
        json_schema=_REPORT_SCHEMAS["report.exposure_anomalies"],
        usage_summary="List local journal/projection anomalies that caveat current-exposure answers; do not treat them as open trades.",
        examples=("tt report exposure_anomalies --home <journal-home>",),
        next_actions=("Use report.open_positions for canonical exposure rows; mention these caveats separately.",),
    )
    registry.register(
        "report.current_exposure",
        _report_current_exposure,
        description=(
            "Recommended trader-agent entry point for open trades/current exposure/recent trading activity. "
            "Composes canonical open_positions, WATCH_ONLY_IDEA watchlist rows, recent_trade_activity journal rows, "
            "and projection_anomalies in one read-only packet. Decisions are activity/audit trail, not canonical exposure; "
            "actual-recorded rows are record-only without linked position_events/projection. Does not assert broker truth."
        ),
        example_minimal={"recent_limit": 10, "include_watchlist": True, "include_anomalies": True},
        optional_keys=("recent_limit", "include_watchlist", "include_anomalies", "kind", "instrument_id", "strategy_id", "stale_mark_threshold_days", "as_of"),
        json_schema=_REPORT_SCHEMAS["report.current_exposure"],
        usage_summary="Recommended trader-agent entry point for answering open trades/current exposure and recently traded questions without raw queries.",
        examples=("tt report current_exposure --home <journal-home> --recent-limit 10",),
        next_actions=("Use open_positions for canonical exposure; mention watchlist/recent activity/anomalies separately as caveats/context.",),
    )
    registry.register(
        "report.coach",
        _report_coach,
        description=(
            "Synthesized decision-support packet aggregating recurring "
            "mistake/strength tags, unscored forecasts, stale watches, and "
            "sample-size warnings. Deterministic; no LLM, no network, no "
            "trading recommendations. Output is enforced free of the "
            "forbidden trade-advice phrases (positive grep gate)."
        ),
        example_minimal={"filter": {}, "stale_threshold_days": 14},
        optional_keys=("filter", "stale_threshold_days"),
        json_schema=_REPORT_SCHEMAS["report.coach"]
    )
