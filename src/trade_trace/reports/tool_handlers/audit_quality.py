"""Family-oriented report tool handlers.

Mechanical extraction from trade_trace.tools.reports; keep behavior stable.
"""
from __future__ import annotations

from trade_trace.reports.autonomy_readiness import report_autonomy_readiness
from trade_trace.reports.phase_gate_readiness import (
    CRITERION_KEYS,
    report_phase_gate_readiness,
)

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


def _validate_thresholds(thresholds: Any) -> None:
    if thresholds is None:
        return
    if not isinstance(thresholds, dict):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "thresholds must be an object keyed by criterion",
            details={"field": "thresholds"},
        )
    unknown = sorted(set(thresholds) - set(CRITERION_KEYS))
    if unknown:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "thresholds contains unknown criterion key(s)",
            details={
                "field": "thresholds",
                "unknown": unknown,
                "allowed": list(CRITERION_KEYS),
            },
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
    """Internal source-quality provenance hygiene panel (bead trade-trace-l9q).

    Five diagnostics over the source attachment graph: missing sources
    on actual_enter decisions, stale sources, contradictory same-kind
    sources, duplicated content_hashes, and sensitive-redaction-status
    sources. Optional `stale_threshold_days` overrides the default 7.
    """

    stale_threshold_days = args.get("stale_threshold_days", 7)
    if (
        not isinstance(stale_threshold_days, int)
        or isinstance(stale_threshold_days, bool)
        or stale_threshold_days < 0
    ):
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
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
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


def _report_phase_gate_readiness(
    args: dict[str, Any], ctx: ToolContext,
) -> dict[str, Any]:
    """`report.phase_gate_readiness` — measurable VISION Phase-2 -> Phase-3
    gate criteria (bead trade-trace-q04o).

    `thresholds` is an optional object keyed by criterion (resolved_n, brier,
    skill_vs_market, reconciliation_cleanliness, audit_readiness,
    paper_fill_coverage). Numeric thresholds are an OWNER decision: any unset
    threshold yields pass=None and the gate is NEVER `ready`. The agent must
    not self-grant a wallet.
    """

    thresholds = args.get("thresholds")
    _validate_thresholds(thresholds)

    min_sample = args.get("min_sample", 1)
    if not isinstance(min_sample, int) or isinstance(min_sample, bool) or min_sample < 1:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "min_sample must be an integer >= 1",
            details={"field": "min_sample", "value": min_sample},
        )

    with db_for_args(args) as db:
        data = report_phase_gate_readiness(
            db.connection,
            thresholds=thresholds,
            min_sample=min_sample,
        )
    _propagate_report_meta(ctx, data)
    return data


def _report_autonomy_readiness(
    args: dict[str, Any], ctx: ToolContext,
) -> dict[str, Any]:
    """`report.autonomy_readiness` — earned-autonomy readiness EVIDENCE bundle
    (bead trade-trace-r91l).

    Composes the OWNER-thresholded `report.phase_gate_readiness` verdict with a
    longitudinal calibration trend, an expectancy series, and audit/hygiene
    diagnostics. EVIDENCE-ONLY: it renders no verdict of its own and the trend
    can never make a not-ready gate ready. `thresholds` validation mirrors
    report.phase_gate_readiness; `min_sample`/`window_days`/`max_windows` tune
    the longitudinal windows only and never gate readiness.
    """

    thresholds = args.get("thresholds")
    _validate_thresholds(thresholds)

    min_sample = args.get("min_sample", 1)
    if not isinstance(min_sample, int) or isinstance(min_sample, bool) or min_sample < 1:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "min_sample must be an integer >= 1",
            details={"field": "min_sample", "value": min_sample},
        )

    window_days = args.get("window_days", 30)
    if not isinstance(window_days, int) or isinstance(window_days, bool) or window_days < 1:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "window_days must be an integer >= 1",
            details={"field": "window_days", "value": window_days},
        )

    max_windows = args.get("max_windows", 12)
    if not isinstance(max_windows, int) or isinstance(max_windows, bool) or max_windows < 1:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "max_windows must be an integer >= 1",
            details={"field": "max_windows", "value": max_windows},
        )

    with db_for_args(args) as db:
        data = report_autonomy_readiness(
            db.connection,
            thresholds=thresholds,
            min_sample=min_sample,
            window_days=window_days,
            max_windows=max_windows,
        )
    _propagate_report_meta(ctx, data)
    return data


__all__ = [name for name in globals() if not name.startswith("__")]
