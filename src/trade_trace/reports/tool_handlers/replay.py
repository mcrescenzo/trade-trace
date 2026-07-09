"""Family-oriented report tool handlers.

Mechanical extraction from trade_trace.tools.reports; keep behavior stable.
"""
from __future__ import annotations

from .common import (
    Any,
    ErrorCode,
    TimestampValidationError,
    ToolContext,
    ToolError,
    evaluate_output,
    export_case_bundle,
    ro_db_for_args,
)


def _replay_case_bundle(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`replay.case_bundle` — deterministic point-in-time local case export."""
    try:
        with ro_db_for_args(args) as db:
            data = export_case_bundle(db.connection, args)
    except (ValueError, TimestampValidationError) as exc:
        raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc), details={"tool": ctx.tool, "field": "replay.case_bundle_request"}) from exc
    ctx.meta_hints["replay_contract_version"] = data.get("contract_version")
    ctx.meta_hints["bundle_id"] = data.get("bundle_id")
    ctx.meta_hints["truncated"] = bool(data.get("truncation", {}).get("is_partial"))
    return data


def _replay_evaluate_output(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`replay.evaluate_output` — deterministic candidate process checker."""
    try:
        data = evaluate_output(args)
    except ValueError as exc:
        raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc), details={"tool": ctx.tool, "field": "replay.evaluate_output_request"}) from exc
    ctx.meta_hints["replay_contract_version"] = data.get("contract_version")
    ctx.meta_hints["evaluation_id"] = data.get("evaluation_id")
    ctx.meta_hints["overall_status"] = (data.get("summary") or {}).get("overall_status")
    return data


__all__ = [name for name in globals() if not name.startswith("__")]
