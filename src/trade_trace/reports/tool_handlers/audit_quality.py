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
    _propagate_report_meta,
    _unsupported_filter_to_tool_error,
    db_for_args,
    report_audit_readiness,
    report_filter_validation_to_tool_error,
    report_playbook_adherence,
    report_source_quality,
)


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
    with db_for_args(args) as db:
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
    with db_for_args(args) as db:
        data = report_source_quality(
            db.connection, stale_threshold_days=stale_threshold_days,
        )
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
    with db_for_args(args) as db:
        data = report_audit_readiness(
            db.connection,
            stale_snapshot_threshold_days=stale_snapshot_threshold_days,
            stale_source_threshold_days=stale_source_threshold_days,
        )
    _propagate_report_meta(ctx, data)
    return data




__all__ = [name for name in globals() if not name.startswith("__")]
