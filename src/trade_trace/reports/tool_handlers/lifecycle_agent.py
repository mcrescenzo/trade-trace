"""Family-oriented report tool handlers.

Mechanical extraction from trade_trace.tools.reports; keep behavior stable.
"""
from __future__ import annotations

from .common import (
    BOOTSTRAP_CONTRACT_VERSION,
    Any,
    ErrorCode,
    TimestampValidationError,
    ToolContext,
    ToolError,
    UnsupportedFilterError,
    ValidationError,
    _propagate_report_meta,
    _unsupported_filter_to_tool_error,
    agent_next_actions,
    compose_bootstrap_packet,
    db_path,
    open_db_for_args,
    report_filter_validation_to_tool_error,
    report_lifecycle,
    report_policy_candidates,
    report_strategy_health,
    report_work_queue,
    resolve_home,
    sqlite3,
    to_utc_iso8601,
)


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


def _report_strategy_health(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.strategy_health` — deterministic local strategy health."""

    status = args.get("status", "active")
    if status not in {"active", "archived", "all"}:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "status must be one of active, archived, all", details={"field": "status", "value": status})
    min_sample = args.get("min_sample", 5)
    if not isinstance(min_sample, int) or min_sample < 1:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "min_sample must be a positive integer", details={"field": "min_sample", "value": min_sample})
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
            data = report_strategy_health(connection, raw_filter=args.get("filter"), status=status, as_of=as_of_raw, min_sample=min_sample)
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



def _report_policy_candidates(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.policy_candidates` — read-only policy candidate report."""

    limit = args.get("limit", 100)
    if not isinstance(limit, int) or limit < 1:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "limit must be a positive integer", details={"field": "limit", "value": limit})
    for field in ("status", "strategy_id", "playbook_id", "as_of"):
        if args.get(field) is not None and not isinstance(args[field], str):
            raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be a string", details={"field": field, "value": args[field]})
    as_of = args.get("as_of")
    if as_of is not None:
        try:
            as_of = to_utc_iso8601(as_of, field="as_of")
        except TimestampValidationError as exc:
            raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc), details={"field": "as_of", "value": args.get("as_of")}) from exc
    try:
        home = resolve_home(args.get("home"))
        path = db_path(home)
        if not path.exists():
            raise ToolError(ErrorCode.STORAGE_ERROR, "journal not initialized; run `tt journal init` first", details={"home": str(home), "db_path": str(path)})
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            data = report_policy_candidates(connection, status=args.get("status"), strategy_id=args.get("strategy_id"), playbook_id=args.get("playbook_id"), as_of=as_of, limit=limit)
        finally:
            connection.close()
        _propagate_report_meta(ctx, data)
        return data
    except ValueError as exc:
        raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc



def _work_queue_common(args: dict[str, Any], ctx: ToolContext, *, surface: str) -> dict[str, Any]:
    stale_threshold_days = args.get("stale_threshold_days", 14)
    if not isinstance(stale_threshold_days, int) or stale_threshold_days < 0:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "stale_threshold_days must be a non-negative integer", details={"field": "stale_threshold_days", "value": stale_threshold_days})
    kinds = args.get("kinds")
    kind = args.get("kind")
    if kind is not None:
        if not isinstance(kind, str):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "kind must be a string", details={"field": "kind", "value": kind})
        kinds = [*(kinds or []), kind]
    if kinds is not None and (not isinstance(kinds, list) or not all(isinstance(item, str) for item in kinds)):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "kinds must be a list of strings", details={"field": "kinds", "value": kinds})
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
            fn = agent_next_actions if surface == "agent.next_actions" else report_work_queue
            data = fn(connection, raw_filter=args.get("filter"), as_of=as_of_raw, stale_threshold_days=stale_threshold_days, kinds=kinds)
        finally:
            connection.close()
        _propagate_report_meta(ctx, data)
        return data
    except ValidationError as exc:
        raise report_filter_validation_to_tool_error(exc) from exc
    except UnsupportedFilterError as exc:
        raise _unsupported_filter_to_tool_error(exc) from exc
    except (ValueError, TimestampValidationError) as exc:
        raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc


def _report_work_queue(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.work_queue` — derived read-only process obligations."""

    return _work_queue_common(args, ctx, surface="report.work_queue")


def _agent_next_actions(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`agent.next_actions` — projection/alias over report.work_queue."""

    return _work_queue_common(args, ctx, surface="agent.next_actions")

def _report_bootstrap(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.bootstrap` / `agent.bootstrap` — JSON-first bootstrap packet surface."""

    db = open_db_for_args(args)
    try:
        try:
            data = compose_bootstrap_packet(
                db.connection,
                as_of=args.get("as_of"),
                raw_filter=args.get("filter"),
                sections=args.get("sections"),
                budgets=args.get("budgets"),
                kind="agent.bootstrap",
            )
        except (ValueError, TimestampValidationError) as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                str(exc),
                details={"tool": ctx.tool, "field": "bootstrap_request"},
            ) from exc
    finally:
        db.close()

    from trade_trace.version import __version__

    metadata = data.get("metadata", {})
    ctx.meta_hints["generated_at"] = metadata.get("generated_at")
    ctx.meta_hints["package_version"] = __version__
    ctx.meta_hints["bootstrap_contract_version"] = BOOTSTRAP_CONTRACT_VERSION
    ctx.meta_hints["truncated"] = bool(data.get("truncation", {}).get("is_partial"))
    ctx.meta_hints["normalized_filter"] = data.get("filter")
    ctx.meta_hints["bootstrap_kind"] = data.get("kind")
    return data


__all__ = [name for name in globals() if not name.startswith("__")]
