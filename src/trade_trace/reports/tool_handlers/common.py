"""Shared plumbing for report tool handlers.

Mechanical extraction from trade_trace.tools.reports; keep behavior stable.
"""
# ruff: noqa: F401,I001
from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.reports import (
    BOOTSTRAP_CONTRACT_VERSION,
    TradingAdvicePhraseError,
    agent_next_actions,
    compose_bootstrap_packet,
    evaluate_output,
    export_case_bundle,
    report_audit_readiness,
    report_calibration,
    report_calibration_advisory,
    report_calibration_anchored,
    report_calibration_integrity,
    report_calibration_terminal,
    report_market_lifecycle,
    report_resolution_quality,
    report_time_decay_sharpening,
    report_coach,
    report_compare,
    report_decision_velocity,
    report_forecast_diagnostics,
    report_lifecycle,
    report_memory_usefulness,
    report_mistake_tripwire,
    report_mistakes,
    report_opportunity,
    report_playbook_adherence,
    report_pnl,
    report_policy_candidates,
    report_process_analytics,
    report_process_quality,
    report_recall_receipts,
    report_resolution_misreads,
    report_risk,
    report_source_quality,
    report_strategy_health,
    report_strengths,
    report_unscored_forecasts,
    report_watchlist,
    report_work_queue,
)
from trade_trace.reports._filter_support import UnsupportedFilterError
from trade_trace.storage import resolve_home
from trade_trace.storage.paths import db_path
from trade_trace.timestamps import TimestampValidationError, to_utc_iso8601
from trade_trace.tools._helpers import db_for_args
from trade_trace.tools._report_filter_errors import (
    report_filter_validation_to_tool_error,
    unsupported_filter_to_tool_error,
)
from trade_trace.tools.errors import ToolError

from trade_trace.reports.tool_schemas import _EMPTY_SCHEMA, _REPORT_SCHEMAS
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
    if not instrument_ids:
        return {}
    placeholders = ", ".join("?" for _ in instrument_ids)
    rows = connection.execute(
        f"""
        WITH ranked_snapshots AS (
            SELECT instrument_id, id, captured_at, source, source_url, price, bid, ask, mid, implied_probability,
                   ROW_NUMBER() OVER (
                       PARTITION BY instrument_id
                       ORDER BY captured_at DESC, id DESC
                   ) AS rn
            FROM snapshots
            WHERE instrument_id IN ({placeholders})
              AND (price IS NOT NULL OR bid IS NOT NULL OR ask IS NOT NULL
                   OR mid IS NOT NULL OR implied_probability IS NOT NULL)
        )
        SELECT instrument_id, id, captured_at, source, source_url, price, bid, ask, mid, implied_probability
        FROM ranked_snapshots
        WHERE rn = 1
        """,
        tuple(instrument_ids),
    ).fetchall()
    marks: dict[str, dict[str, Any]] = {}
    for row in rows:
        instrument_id = row[0]
        marks[instrument_id] = _snapshot_latest_mark(row[1:])
    return marks


def _position_row_payload(row: Any, latest_mark: dict[str, Any] | None, *, stale_cutoff: datetime) -> dict[str, Any]:
    from trade_trace.projections import _unrealized_pnl
    from trade_trace.reporting.position_rows import CAVEAT_OPEN_NO_MARK

    caveat_codes = _position_current_exposure_codes(row)
    read_model_caveats = list(row.caveats)
    caveat_entries = list(row.caveat_entries)
    unrealized_pnl = row.unrealized_pnl
    mark_state = "missing"
    if latest_mark is not None:
        captured_at = _parse_report_timestamp(latest_mark["captured_at"], field="snapshots.captured_at")
        mark_state = "stale" if captured_at < stale_cutoff else "available"
        if mark_state == "stale" and "STALE_MARK" not in caveat_codes:
            caveat_codes.append("STALE_MARK")
        if "MISSING_MARK" in caveat_codes:
            caveat_codes.remove("MISSING_MARK")
        # Re-mark an open position whose stored projection PnL predates this
        # snapshot. The positions projection only marks unrealized_pnl at
        # rebuild time, so a position opened before its first snapshot keeps
        # unrealized_pnl=None and an `open_no_mark` caveat even once a live
        # mark is available — contradicting the mark_state/latest_mark on the
        # very same row. Recompute from the latest mark's YES-contract price
        # using the canonical side-aware convention (trade-trace-ctvb) and
        # drop the now-false caveat so the row is self-consistent.
        mark_price = latest_mark.get("price")
        if (
            row.status == "open"
            and unrealized_pnl is None
            and mark_price is not None
            and row.avg_entry_price is not None
            and row.net_quantity is not None
        ):
            unrealized_pnl = _unrealized_pnl(
                row.side, float(mark_price), float(row.avg_entry_price), float(row.net_quantity)
            )
            read_model_caveats = [code for code in read_model_caveats if code != CAVEAT_OPEN_NO_MARK]
            caveat_entries = [entry for entry in caveat_entries if entry.code != CAVEAT_OPEN_NO_MARK]
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
        "unrealized_pnl": unrealized_pnl,
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
        "read_model_caveats": read_model_caveats,
        "caveats": [
            {"code": entry.code, "label": entry.label, "summary": entry.summary, "severity": entry.severity}
            for entry in caveat_entries
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

    with db_for_args(args) as db:
        data = build(db.connection)
    _propagate_report_meta(ctx, data)
    return data


def _compat_report_calibration(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Resolve report_calibration through the legacy module when monkey-patched.

    A few historical tests patch ``trade_trace.tools.reports.report_calibration``;
    keep that private compatibility behavior while handlers live in this package.
    """

    legacy = sys.modules.get("trade_trace.tools.reports")
    fn = getattr(legacy, "report_calibration", report_calibration) if legacy is not None else report_calibration
    return fn(*args, **kwargs)


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


def _make_request_report(fn):
    """Wrap a report function that validates its full request object."""

    def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        def _build(connection: Any) -> dict[str, Any]:
            try:
                request = {k: v for k, v in args.items() if k != "home"}
                return fn(connection, request=request)
            except ValidationError as exc:
                raise report_filter_validation_to_tool_error(exc) from exc
            except UnsupportedFilterError as exc:
                raise _unsupported_filter_to_tool_error(exc) from exc

        return _run_report_data(args, ctx, _build)

    return _handler



__all__ = [name for name in globals() if not name.startswith("__")]
