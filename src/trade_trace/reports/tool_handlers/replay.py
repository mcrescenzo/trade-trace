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
    db_path,
    evaluate_output,
    export_case_bundle,
    resolve_home,
    sqlite3,
)


def _replay_case_bundle(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`replay.case_bundle` — deterministic point-in-time local case export."""
    try:
        home = resolve_home(args.get("home"))
        path = db_path(home)
        if not path.exists():
            raise ToolError(ErrorCode.STORAGE_ERROR, "journal not initialized; run `tt journal init` first", details={"home": str(home), "db_path": str(path)})
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            data = export_case_bundle(connection, args)
        finally:
            connection.close()
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
