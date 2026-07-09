"""Family-oriented report tool handlers.

Mechanical extraction from trade_trace.tools.reports; keep behavior stable.
"""
from __future__ import annotations

from .common import (
    Any,
    ToolContext,
    UnsupportedFilterError,
    ValidationError,
    _compat_report_calibration,
    _propagate_report_meta,
    _unsupported_filter_to_tool_error,
    db_for_args,
    report_calibration_integrity,
    report_filter_validation_to_tool_error,
    report_forecast_diagnostics,
    report_unscored_forecasts,
)


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
    with db_for_args(args) as db:
        try:
            data = _compat_report_calibration(
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
    _propagate_report_meta(ctx, data)
    return data


def _report_forecast_diagnostics(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    raw_filter = args.get("filter")
    min_sample = args.get("min_sample")
    with db_for_args(args) as db:
        try:
            data = report_forecast_diagnostics(
                db.connection,
                raw_filter=raw_filter,
                min_sample=min_sample if min_sample is not None else 20,
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    _propagate_report_meta(ctx, data)
    return data



def _report_calibration_integrity(
    args: dict[str, Any], ctx: ToolContext,
) -> dict[str, Any]:
    """Internal six-diagnostic anti-goodhart hygiene panel (trade-trace-jzn)."""

    with db_for_args(args) as db:
        data = report_calibration_integrity(db.connection)
    _propagate_report_meta(ctx, data)
    return data


def _report_unscored_forecasts(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.unscored_forecasts` — list pending binary forecasts past
    `resolution_at` with no resolved_final outcome on their instrument."""

    raw_filter = args.get("filter")
    with db_for_args(args) as db:
        try:
            data = report_unscored_forecasts(db.connection, raw_filter=raw_filter)
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    _propagate_report_meta(ctx, data)
    return data

__all__ = [name for name in globals() if not name.startswith("__")]
