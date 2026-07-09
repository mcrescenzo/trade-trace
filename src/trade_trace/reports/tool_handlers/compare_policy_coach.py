"""Family-oriented report tool handlers.

Mechanical extraction from trade_trace.tools.reports; keep behavior stable.
"""
from __future__ import annotations

from .common import (
    Any,
    ErrorCode,
    ToolContext,
    ToolError,
    TradingAdvicePhraseError,
    UnsupportedFilterError,
    ValidationError,
    _propagate_report_meta,
    _unsupported_filter_to_tool_error,
    db_for_args,
    report_coach,
    report_filter_validation_to_tool_error,
    report_opportunity,
)


def _report_opportunity(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.opportunity` — path-dependent decision/outcome diagnostics."""
    with db_for_args(args) as db:
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
    _propagate_report_meta(ctx, data)
    return data



def _report_coach(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.coach` — synthesized decision-support packet. No LLM, no
    network, no trade advice."""

    raw_filter = args.get("filter")
    stale_threshold_days = args.get("stale_threshold_days", 14)
    with db_for_args(args) as db:
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
    _propagate_report_meta(ctx, data)
    return data


__all__ = [name for name in globals() if not name.startswith("__")]
