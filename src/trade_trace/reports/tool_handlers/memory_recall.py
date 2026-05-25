"""Family-oriented report tool handlers.

Mechanical extraction from trade_trace.tools.reports; keep behavior stable.
"""
from __future__ import annotations

from .common import (
    Any,
    ErrorCode,
    ToolContext,
    ToolError,
    _propagate_report_meta,
    db_path,
    report_memory_usefulness,
    report_recall_receipts,
    resolve_home,
    sqlite3,
)


def _report_recall_receipts(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.recall_receipts` — computed memory recall receipts, read-only."""

    limit = args.get("limit", 100)
    if not isinstance(limit, int) or limit < 1:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "limit must be a positive integer", details={"field": "limit", "value": limit})
    for field in ("recall_id", "node_id", "consumer_kind", "consumer_id", "run_id", "agent_id", "model_id", "environment", "instrument_id", "strategy_id", "as_of"):
        if args.get(field) is not None and not isinstance(args[field], str):
            raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be a string", details={"field": field, "value": args[field]})
    try:
        home = resolve_home(args.get("home"))
        path = db_path(home)
        if not path.exists():
            raise ToolError(ErrorCode.STORAGE_ERROR, "journal not initialized; run `tt journal init` first", details={"home": str(home), "db_path": str(path)})
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            data = report_recall_receipts(
                connection,
                recall_id=args.get("recall_id"),
                node_id=args.get("node_id"),
                consumer_kind=args.get("consumer_kind"),
                consumer_id=args.get("consumer_id"),
                run_id=args.get("run_id"),
                agent_id=args.get("agent_id"),
                model_id=args.get("model_id"),
                environment=args.get("environment"),
                instrument_id=args.get("instrument_id"),
                strategy_id=args.get("strategy_id"),
                as_of=args.get("as_of"),
                limit=limit,
            )
        finally:
            connection.close()
        _propagate_report_meta(ctx, data)
        return data
    except ValueError as exc:
        raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc


def _report_memory_usefulness(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.memory_usefulness` — diagnostic memory usefulness with controls."""

    limit = args.get("limit", 100)
    if not isinstance(limit, int) or limit < 1:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "limit must be a positive integer", details={"field": "limit", "value": limit})
    for field in ("recall_id", "node_id", "consumer_kind", "consumer_id", "run_id", "agent_id", "model_id", "environment", "instrument_id", "strategy_id", "memory_kind", "as_of"):
        if args.get(field) is not None and not isinstance(args[field], str):
            raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be a string", details={"field": field, "value": args[field]})
    try:
        home = resolve_home(args.get("home"))
        path = db_path(home)
        if not path.exists():
            raise ToolError(ErrorCode.STORAGE_ERROR, "journal not initialized; run `tt journal init` first", details={"home": str(home), "db_path": str(path)})
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            data = report_memory_usefulness(
                connection,
                recall_id=args.get("recall_id"),
                node_id=args.get("node_id"),
                consumer_kind=args.get("consumer_kind"),
                consumer_id=args.get("consumer_id"),
                run_id=args.get("run_id"),
                agent_id=args.get("agent_id"),
                model_id=args.get("model_id"),
                environment=args.get("environment"),
                instrument_id=args.get("instrument_id"),
                strategy_id=args.get("strategy_id"),
                memory_kind=args.get("memory_kind"),
                as_of=args.get("as_of"),
                limit=limit,
            )
        finally:
            connection.close()
        _propagate_report_meta(ctx, data)
        return data
    except ValueError as exc:
        raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc



__all__ = [name for name in globals() if not name.startswith("__")]
