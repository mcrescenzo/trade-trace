"""Family-oriented report tool handlers.

Mechanical extraction from trade_trace.tools.reports; keep behavior stable.
"""
from __future__ import annotations

from .common import (
    Any,
    ErrorCode,
    ToolContext,
    ToolError,
    UnsupportedFilterError,
    ValidationError,
    _compat_report_calibration,
    _propagate_report_meta,
    _unsupported_filter_to_tool_error,
    open_db_for_args,
    report_calibration_advisory,
    report_calibration_anchored,
    report_calibration_integrity,
    report_calibration_terminal,
    report_decision_velocity,
    report_filter_validation_to_tool_error,
    report_forecast_diagnostics,
    report_market_lifecycle,
    report_mistake_tripwire,
    report_process_quality,
    report_resolution_quality,
    report_time_decay_sharpening,
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
    db = open_db_for_args(args)
    try:
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
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_calibration_advisory(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.calibration_advisory` — decision-time recalibration for a
    candidate forecast probability (trade-trace-4kec.7)."""

    db = open_db_for_args(args)
    try:
        try:
            min_sample = args.get("min_sample")
            data = report_calibration_advisory(
                db.connection,
                probability=args.get("probability"),
                raw_filter=args.get("filter"),
                min_sample=int(min_sample) if min_sample is not None else 20,
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
        except (ValueError, TypeError) as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                str(exc),
                details={"field": "probability"},
            ) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_mistake_tripwire(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.mistake_tripwire` — decision-time recurring-mistake trip-wire
    (trade-trace-4kec.10)."""

    db = open_db_for_args(args)
    try:
        try:
            min_sample = args.get("min_sample")
            brier_threshold = args.get("brier_threshold")
            data = report_mistake_tripwire(
                db.connection,
                tags=args.get("tags") or [],
                instrument_id=args.get("instrument_id"),
                min_sample=int(min_sample) if min_sample is not None else 10,
                brier_threshold=float(brier_threshold) if brier_threshold is not None else 0.25,
            )
        except (ValueError, TypeError) as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR, str(exc), details={"field": "tags"}
            ) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_process_quality(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.process_quality` — bet-sizing vs declared edge (Kelly-consistency),
    outcome-independent (trade-trace-4kec.11)."""

    db = open_db_for_args(args)
    try:
        try:
            min_sample = args.get("min_sample")
            data = report_process_quality(
                db.connection,
                instrument_id=args.get("instrument_id"),
                min_sample=int(min_sample) if min_sample is not None else 5,
            )
        except (ValueError, TypeError) as exc:
            raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc), details={"field": "min_sample"}) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_calibration_anchored(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    db = open_db_for_args(args)
    try:
        try:
            min_sample = args.get("min_sample")
            data = report_calibration_anchored(
                db.connection,
                raw_filter=args.get("filter"),
                min_sample=int(min_sample) if min_sample is not None else 20,
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_calibration_terminal(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    db = open_db_for_args(args)
    try:
        try:
            min_sample = args.get("min_sample")
            data = report_calibration_terminal(
                db.connection,
                raw_filter=args.get("filter"),
                min_sample=int(min_sample) if min_sample is not None else 20,
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _pm_native_report_handler(func):
    def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        db = open_db_for_args(args)
        try:
            try:
                data = func(db.connection, raw_filter=args.get("filter"))
            except ValidationError as exc:
                raise report_filter_validation_to_tool_error(exc) from exc
            except UnsupportedFilterError as exc:
                raise _unsupported_filter_to_tool_error(exc) from exc
        finally:
            db.close()
        _propagate_report_meta(ctx, data)
        return data
    return _handler


_report_market_lifecycle = _pm_native_report_handler(report_market_lifecycle)
_report_resolution_quality = _pm_native_report_handler(report_resolution_quality)


def _report_time_decay_sharpening(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    db = open_db_for_args(args)
    try:
        try:
            min_sample = args.get("min_sample")
            data = report_time_decay_sharpening(
                db.connection,
                raw_filter=args.get("filter"),
                min_sample=int(min_sample) if min_sample is not None else 20,
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_forecast_diagnostics(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    raw_filter = args.get("filter")
    min_sample = args.get("min_sample")
    db = open_db_for_args(args)
    try:
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


__all__ = [name for name in globals() if not name.startswith("__")]
