"""`report.*` tool surface per docs/architecture/reports.md.

This module ships the contract-grade pieces an agent needs to introspect
the report system before the full 7-report implementation lands:

- `report.filter_schema` (trade-trace-fo7): canonical JSON Schema for the
  ReportFilter shape. Agents call this to discover valid fields and enum
  values without reading the docs.

The 7 deterministic reports (calibration, mistakes, strengths, pnl,
watchlist, unscored_forecasts, decision_velocity) land in
trade-trace-77z; the coach lands in trade-trace-2g2.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.reports import (
    TradingAdvicePhraseError,
    report_calibration,
    report_calibration_integrity,
    report_coach,
    report_compare,
    report_decision_velocity,
    report_mistakes,
    report_opportunity,
    report_playbook_adherence,
    report_pnl,
    report_risk,
    report_source_quality,
    report_strategy_performance,
    report_strengths,
    report_unscored_forecasts,
    report_watchlist,
)
from trade_trace.reports._filter_support import (
    SUPPORTED_FILTER_FIELDS,
    UnsupportedFilterError,
)
from trade_trace.tools._helpers import open_db_for_args
from trade_trace.tools.errors import ToolError


_EMPTY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "description": "No tool-specific arguments are accepted.",
}


def _schema(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
    description: str = "",
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "description": description,
    }


_FILTER_PROP = {
    "type": "object",
    "description": (
        "ReportFilter object; call report.filter_schema for the canonical "
        "nested schema and supported fields."
    ),
}


_REPORT_SCHEMAS: dict[str, dict[str, Any]] = {
    "report.filter_schema": _schema(
        {"mode": {"type": "string", "enum": ["validation", "serialization"]}},
        description=(
            "Optional mode selects validation (accepted input) or "
            "serialization (emitted echo) ReportFilter schema."
        ),
    ),
    "report.calibration": _schema(
        {"filter": _FILTER_PROP, "min_sample": {"type": "integer", "minimum": 1}},
        description="Optional ReportFilter and low-N warning threshold; defaults min_sample=20.",
    ),
    "report.playbook_adherence": _schema(
        {
            "filter": _FILTER_PROP,
            "playbook_id": {"type": "string"},
            "strategy_id": {"type": "string"},
        },
        description="Optional ReportFilter plus top-level playbook_id/strategy_id scoping.",
    ),
    "report.source_quality": _schema({"stale_threshold_days": {"type": "integer", "minimum": 0}}),
    "report.calibration_integrity": _EMPTY_SCHEMA,
    "report.unscored_forecasts": _schema({"filter": _FILTER_PROP}),
    "report.decision_velocity": _schema(
        {"filter": _FILTER_PROP, "bucket": {"type": "string", "enum": ["day", "week"]}},
        description="bucket defaults to day; only day/week are accepted.",
    ),
    "report.mistakes": _schema({"filter": _FILTER_PROP}),
    "report.strengths": _schema({"filter": _FILTER_PROP}),
    "report.pnl": _schema({"filter": _FILTER_PROP}),
    "report.risk": _schema({"filter": _FILTER_PROP}),
    "report.opportunity": _schema(
        {
            "filter": _FILTER_PROP,
            "minimum_coverage": {"type": "string", "enum": ["sparse", "partial", "full"]},
            "max_records": {"type": "integer", "minimum": 1},
            "include_labels": {"type": "boolean"},
            "min_sample": {"type": "integer", "minimum": 1},
        }
    ),
    "report.compare": _schema(
        {
            "base_report": {"type": "string", "enum": ["calibration", "pnl"]},
            "group_by": {
                "type": "string",
                "description": (
                    "Allowlisted by base_report; common values include "
                    "strategy_id, instrument_id, tag."
                ),
            },
            "filter": _FILTER_PROP,
            "min_sample": {"type": "integer", "minimum": 1},
        }
    ),
    "report.strategy_performance": _schema(
        {
            "strategy_id": {"type": "string"},
            "filter": _FILTER_PROP,
            "min_sample": {"type": "integer", "minimum": 1},
        }
    ),
    "report.watchlist": _schema(
        {
            "filter": _FILTER_PROP,
            "mode": {"type": "string", "enum": ["all", "stale"]},
            "stale_threshold_days": {"type": "integer", "minimum": 0},
        }
    ),
    "report.coach": _schema(
        {"filter": _FILTER_PROP, "stale_threshold_days": {"type": "integer", "minimum": 0}}
    ),
}


def _unsupported_filter_to_tool_error(exc: UnsupportedFilterError) -> ToolError:
    """Translate a typed UnsupportedFilterError into a VALIDATION_ERROR
    envelope. The agent gets the offending leaf paths and the supported
    set so it can prune its input and retry."""

    return ToolError(
        ErrorCode.VALIDATION_ERROR,
        str(exc),
        details={
            "field": "filter",
            "report": exc.report,
            "unsupported_filter_paths": exc.paths,
            "supported_filter_paths": sorted(
                SUPPORTED_FILTER_FIELDS.get(exc.report, frozenset())
            ),
        },
    )


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
            data = report_calibration(
                db.connection,
                raw_filter=raw_filter,
                min_sample=min_sample if min_sample is not None else 20,
            )
        except ValidationError as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"ReportFilter validation failed: {exc.errors()}",
                details={"field": "filter", "validation_errors": exc.errors()},
            ) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
        # Embed integrity diagnostics in the panel so the panel can never
        # be read without the denominator/hygiene context.
        data["integrity_diagnostics"] = report_calibration_integrity(db.connection)
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


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
    db = open_db_for_args(args)
    try:
        try:
            data = report_playbook_adherence(
                db.connection, raw_filter=raw_filter,
                playbook_id=playbook_id, strategy_id=strategy_id,
            )
        except ValidationError as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"ReportFilter validation failed: {exc.errors()}",
                details={"field": "filter", "validation_errors": exc.errors()},
            ) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    finally:
        db.close()
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
    db = open_db_for_args(args)
    try:
        data = report_source_quality(
            db.connection, stale_threshold_days=stale_threshold_days,
        )
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
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"ReportFilter validation failed: {exc.errors()}",
                details={"field": "filter", "validation_errors": exc.errors()},
            ) from exc
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
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"ReportFilter validation failed: {exc.errors()}",
                details={"field": "filter", "validation_errors": exc.errors()},
            ) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_compare(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.compare` — compute a base report per deterministic group."""
    db = open_db_for_args(args)
    try:
        try:
            data = report_compare(
                db.connection,
                base_report=args.get("base_report", "calibration"),
                group_by=args.get("group_by", "strategy_id"),
                raw_filter=args.get("filter"),
                min_sample=args.get("min_sample"),
            )
        except ValidationError as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"ReportFilter validation failed: {exc.errors()}",
                details={"field": "filter", "validation_errors": exc.errors()},
            ) from exc
        except (UnsupportedFilterError, ValueError) as exc:
            if isinstance(exc, UnsupportedFilterError):
                raise _unsupported_filter_to_tool_error(exc) from exc
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                str(exc),
                details={"field": "base_report/group_by"},
            ) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_strategy_performance(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.strategy_performance` — wrapper over `report.compare`.

    trade-trace-4md decision: implemented as a convenience wrapper around
    `report.compare(base_report='pnl', group_by='strategy_id')` rather than a
    separate metric stack.
    """
    db = open_db_for_args(args)
    try:
        try:
            data = report_strategy_performance(
                db.connection,
                strategy_id=args.get("strategy_id"),
                raw_filter=args.get("filter"),
                min_sample=args.get("min_sample"),
            )
        except ValidationError as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"ReportFilter validation failed: {exc.errors()}",
                details={"field": "filter", "validation_errors": exc.errors()},
            ) from exc
        except (UnsupportedFilterError, ValueError) as exc:
            if isinstance(exc, UnsupportedFilterError):
                raise _unsupported_filter_to_tool_error(exc) from exc
            raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_opportunity(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.opportunity` — path-dependent decision/outcome diagnostics."""
    db = open_db_for_args(args)
    try:
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
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"ReportFilter validation failed: {exc.errors()}",
                details={"field": "filter", "validation_errors": exc.errors()},
            ) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
        except ValueError as exc:
            raise ToolError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _make_filter_only_report(fn):
    """Wrap a report function whose only optional arg is `filter` into a tool
    handler that validates and dispatches it."""

    def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        db = open_db_for_args(args)
        try:
            try:
                data = fn(db.connection, raw_filter=args.get("filter"))
            except ValidationError as exc:
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    f"ReportFilter validation failed: {exc.errors()}",
                    details={"field": "filter", "validation_errors": exc.errors()},
                ) from exc
            except UnsupportedFilterError as exc:
                raise _unsupported_filter_to_tool_error(exc) from exc
        finally:
            db.close()
        _propagate_report_meta(ctx, data)
        return data

    return _handler


def _report_watchlist(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.watchlist` — list open watch decisions. `mode='stale'` opts in
    to the stale subset; `stale_threshold_days` overrides the default 14."""

    raw_filter = args.get("filter")
    mode = args.get("mode", "all")
    if mode not in ("all", "stale"):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"mode must be 'all' or 'stale'; got {mode!r}",
            details={"field": "mode", "value": mode, "allowed": ["all", "stale"]},
        )
    stale_threshold_days = args.get("stale_threshold_days", 14)
    db = open_db_for_args(args)
    try:
        try:
            data = report_watchlist(
                db.connection, raw_filter=raw_filter,
                stale=(mode == "stale"),
                stale_threshold_days=stale_threshold_days,
            )
        except ValidationError as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"ReportFilter validation failed: {exc.errors()}",
                details={"field": "filter", "validation_errors": exc.errors()},
            ) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_coach(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.coach` — synthesized decision-support packet. No LLM, no
    network, no trade advice."""

    raw_filter = args.get("filter")
    stale_threshold_days = args.get("stale_threshold_days", 14)
    db = open_db_for_args(args)
    try:
        try:
            data = report_coach(
                db.connection, raw_filter=raw_filter,
                stale_threshold_days=stale_threshold_days,
            )
        except ValidationError as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"ReportFilter validation failed: {exc.errors()}",
                details={"field": "filter", "validation_errors": exc.errors()},
            ) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
        except TradingAdvicePhraseError as exc:
            raise ToolError(
                ErrorCode.INVARIANT_VIOLATION,
                str(exc),
                details={"forbidden_matches": exc.matches},
            ) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _report_filter_schema(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Return the canonical Pydantic-generated JSON Schema for ReportFilter.

    Optional `mode` arg: `"validation"` (default) or `"serialization"`.
    Validation mode reflects what the server accepts on a tool call;
    serialization mode reflects what the server emits on echo (e.g. in
    a `ReportResult.summary.filter` field). For ReportFilter the two
    differ only in `Optional` handling — both shapes are useful for
    agents building UIs over the surface.
    """

    mode = args.get("mode", "validation")
    if mode not in ("validation", "serialization"):
        from trade_trace.contracts.errors import ErrorCode
        from trade_trace.tools.errors import ToolError

        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"mode must be 'validation' or 'serialization'; got {mode!r}",
            details={"field": "mode", "value": mode,
                     "allowed": ["validation", "serialization"]},
        )

    schema = ReportFilter.model_json_schema(mode=mode)
    return {
        "schema": schema,
        "mode": mode,
        "strategy_id_sentinel": {
            "value": "__none__",
            "meaning": "Select rows where strategy_id IS NULL.",
        },
    }


def register_report_tools(registry: ToolRegistry) -> None:
    """Register `report.*` tools on the supplied registry.

    Currently registers only `report.filter_schema`; the 7 deterministic
    reports + the coach are wired in their dedicated beads."""

    registry.register(
        "report.filter_schema",
        _report_filter_schema,
        description=(
            "Return the canonical JSON Schema for ReportFilter (the shared "
            "input shape for every report.* tool). Optional `mode` arg "
            "(`validation` default or `serialization`). Surfaces the "
            "`__none__` sentinel meaning for `strategy.strategy_id` so "
            "agents can build filter UIs without reading the docs."
        ),
        json_schema=_REPORT_SCHEMAS["report.filter_schema"],
    )
    registry.register(
        "report.calibration",
        _report_calibration,
        description=(
            "Calibration metric panel over scored binary forecasts: Brier, "
            "log score, ECE (equal-width 0.1 bins), sharpness, baseline + "
            "skill, plus reliability bins (scoring.md §7). Excludes "
            "late-recorded forecasts by default per dogfood-protocol §2.2 "
            "(opt in via filter.outcome.include_late_recorded). Emits a "
            "sample_warning when N < min_sample (default 20). Embeds the "
            "six anti-goodhart hygiene diagnostics from "
            "report.calibration_integrity under data.integrity_diagnostics."
        ),
        json_schema=_REPORT_SCHEMAS["report.calibration"]
    )
    registry.register(
        "report.playbook_adherence",
        _report_playbook_adherence,
        description=(
            "Playbook adherence aggregate from decision_playbook_rules "
            "(no JSON parsing). Per-group metrics: counts of considered / "
            "followed / overridden / not_applicable. Optional scoping: "
            "playbook_id (single playbook), strategy_id (single strategy "
            "across decisions). Per bead fbq."
        ),
        json_schema=_REPORT_SCHEMAS["report.playbook_adherence"]
    )
    registry.register(
        "report.source_quality",
        _report_source_quality,
        description=(
            "Provenance hygiene diagnostics over attached sources "
            "(bead trade-trace-l9q): missing_sources_on_actual_enter, "
            "stale_sources, contradictory_sources, duplicated_sources, "
            "sensitive_sources. Each emits {count,sample_ids,samples,"
            "truncated}. stale_threshold_days defaults to 7. No external "
            "fetching, no credibility scoring."
        ),
        example_minimal={"stale_threshold_days": 7},
        optional_keys=("stale_threshold_days",),
        json_schema=_REPORT_SCHEMAS["report.source_quality"]
    )
    registry.register(
        "report.calibration_integrity",
        _report_calibration_integrity,
        description=(
            "Anti-goodhart hygiene diagnostics for the calibration panel "
            "(bead trade-trace-jzn): forecast_coverage, unsupported_rate, "
            "ambiguous_rate, disputed_rate, void_cancelled_rate, "
            "suspicious_late_rate. Each diagnostic returns "
            "{count,total,rate_pct,sample_ids,truncated}; the summary "
            "carries denominator context (total_decisions, total_forecasts, "
            "scored_forecasts, denominator_coverage_pct). Empty DBs surface "
            "sample_warning='no_data'."
        ),
        json_schema=_REPORT_SCHEMAS["report.calibration_integrity"]
    )
    registry.register(
        "report.unscored_forecasts",
        _report_unscored_forecasts,
        description=(
            "List pending binary forecasts past resolution_at whose "
            "instrument has no resolved_final (non-superseded) outcome. "
            "Mirrors signal.scan kind=unscored_forecast (trade-trace-2ry) "
            "but returns the rows for direct action."
        ),
        example_minimal={"filter": {}},
        optional_keys=("filter",),
        json_schema=_REPORT_SCHEMAS["report.unscored_forecasts"]
    )
    registry.register(
        "report.decision_velocity",
        _report_decision_velocity,
        description=(
            "Decision counts bucketed by day or week over the filter's "
            "decision_at_* window. Bucket boundaries are UTC-aligned; "
            "groups[] are ordered by bucket key ascending."
        ),
        json_schema=_REPORT_SCHEMAS["report.decision_velocity"]
    )
    registry.register(
        "report.mistakes",
        _make_filter_only_report(report_mistakes),
        description=(
            "Tag-aggregated recurring patterns ranked by mean Brier of "
            "associated scored forecasts (worst first). Per-group metrics: "
            "decision_count, scored_forecast_count, mean_brier."
        ),
        json_schema=_REPORT_SCHEMAS["report.mistakes"]
    )
    registry.register(
        "report.strengths",
        _make_filter_only_report(report_strengths),
        description=(
            "Tag-aggregated patterns ranked by mean Brier (best first). "
            "Mirror of report.mistakes."
        ),
        json_schema=_REPORT_SCHEMAS["report.strengths"]
    )
    registry.register(
        "report.pnl",
        _make_filter_only_report(report_pnl),
        description=(
            "Realized + unrealized + mark-to-market P&L over the positions "
            "projection. Per-instrument groups; summary carries "
            "open_mark_coverage (open positions with marks / open positions). "
            "Reads the rebuildable positions "
            "projection (trade-trace-5zg)."
        ),
        json_schema=_REPORT_SCHEMAS["report.pnl"]
    )
    registry.register(
        "report.risk",
        _make_filter_only_report(report_risk),
        description=(
            "R-multiple aggregate over decisions that declared a risk "
            "budget (risk-units.md / bead trade-trace-8z2). Reports mean/"
            "median R, expectancy in R, win rate, payoff ratio, best/worst R, "
            "histogram bins, and counts of win/loss/breakeven. Decisions "
            "without declared_risk_amount are excluded from the aggregate and "
            "counted in caveats so the agent can chase the gap. Pending "
            "positions (declared risk but not closed) are surfaced separately "
            "in metrics.n_pending_with_risk."
        ),
        json_schema=_REPORT_SCHEMAS["report.risk"]
    )
    registry.register(
        "report.opportunity",
        _report_opportunity,
        description=(
            "Path-dependent opportunity diagnostics over supplied snapshots: "
            "reconstructs post-decision paths, emits max favorable/adverse "
            "moves, exit-efficiency, data_coverage, sparse/missing snapshot "
            "caveats, and documented labels such as missed_positive_edge, "
            "good_skip, right_thesis_wrong_timing, bad_process_good_outcome, "
            "and good_process_bad_outcome. No external price fetching. All "
            "arguments are optional; defaults apply for omitted keys per bead "
            "trade-trace-4zbk."
        ),
        example_minimal={
            "filter": {},
            "minimum_coverage": "sparse",
            "max_records": 100,
            "include_labels": True,
            "min_sample": 20,
        },
        optional_keys=(
            "filter",
            "minimum_coverage",
            "max_records",
            "include_labels",
            "min_sample",
        ),
        json_schema=_REPORT_SCHEMAS["report.opportunity"]
    )
    registry.register(
        "report.compare",
        _report_compare,
        description=(
            "Compare base report metrics across one allowlisted group_by. "
            "Supported base_report values: calibration and pnl. Supported "
            "group_by depends on base_report and is validated via fixed SQL "
            "allowlists for injection safety. Per-group sample_warning is "
            "emitted; summary.sample_warning is set when any group is low-N."
        ),
        example_minimal={"base_report": "calibration", "group_by": "strategy_id", "filter": {}},
        json_schema=_REPORT_SCHEMAS["report.compare"]
    )
    registry.register(
        "report.strategy_performance",
        _report_strategy_performance,
        description=(
            "Convenience wrapper implemented as report.compare with "
            "base_report='pnl' and group_by='strategy_id'. Optional "
            "strategy_id narrows to a single strategy; omitted compares all "
            "strategies including the __none__ no-strategy bucket."
        ),
        example_minimal={"strategy_id": "strat_example", "filter": {}},
        json_schema=_REPORT_SCHEMAS["report.strategy_performance"]
    )
    registry.register(
        "report.watchlist",
        _report_watchlist,
        description=(
            "List `watch`-type decisions. mode='all' (default) returns every "
            "watch; mode='stale' returns watches older than "
            "stale_threshold_days (default 14)."
        ),
        example_minimal={"filter": {}, "mode": "all", "stale_threshold_days": 14},
        optional_keys=("filter", "mode", "stale_threshold_days"),
        json_schema=_REPORT_SCHEMAS["report.watchlist"]
    )
    registry.register(
        "report.coach",
        _report_coach,
        description=(
            "Synthesized decision-support packet aggregating recurring "
            "mistake/strength tags, unscored forecasts, stale watches, and "
            "sample-size warnings. Deterministic; no LLM, no network, no "
            "trading recommendations. Output is enforced free of the "
            "forbidden trade-advice phrases (positive grep gate)."
        ),
        example_minimal={"filter": {}, "stale_threshold_days": 14},
        optional_keys=("filter", "stale_threshold_days"),
        json_schema=_REPORT_SCHEMAS["report.coach"]
    )
