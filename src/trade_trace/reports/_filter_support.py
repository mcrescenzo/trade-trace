"""Per-report supported ReportFilter declarations + rejection helper.

Each `report.*` tool validates the agent's input against `ReportFilter`
(extra=`forbid`), but until this module landed, several reports validated
the filter and then computed metrics over the global table. That
combination produced silently-broadened reports whose `summary.filter`
field misled callers into thinking a scoped report had been returned.

This module fixes that by pinning, for each report, the exact set of
`ReportFilter` leaf paths the report actually consults at SQL time:

- `enforce_supported_filter(rf, report=...)` walks the validated filter
  and rejects any non-default value in a path the report does not
  support. The error carries `unsupported_filter_paths` so the agent
  can prune its input and retry.
- `SUPPORTED_FILTER_FIELDS` is the per-report contract; new reports
  must register here before accepting any non-default filter field.
- `applied_filter_view(rf, report=...)` returns the subset of the
  validated filter the report actually applies, so `summary.filter`
  can echo only the slice that influenced the result instead of the
  full echo that callers were misreading.

The dispatcher catches `UnsupportedFilterError` and surfaces it as a
typed `VALIDATION_ERROR` envelope.
"""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.report_filter import ReportFilter


class UnsupportedFilterError(ValueError):
    """A report saw a non-default value in a path it does not support."""

    def __init__(self, report: str, paths: list[str]) -> None:
        self.report = report
        self.paths = sorted(paths)
        super().__init__(
            f"report {report!r} does not support filter field(s) {self.paths!r}; "
            f"remove them or use a report that supports them"
        )


SUPPORTED_FILTER_FIELDS: dict[str, frozenset[str]] = {
    # Calibration scopes scored forecasts through the forecast/thesis/
    # instrument chain for these public/security-contract filters, and
    # consults `outcome.include_late_recorded` to swap the dogfood default.
    "report.calibration": frozenset({
        "actors.actor_id",
        "actors.agent_id",
        "actors.model_id",
        "actors.environment",
        "actors.run_id",
        "instrument.venue_id",
        "strategy.strategy_id",
        "outcome.include_late_recorded",
    }),
    "report.calibration_anchored": frozenset({
        "actors.actor_id",
        "actors.agent_id",
        "actors.model_id",
        "actors.environment",
        "actors.run_id",
        "instrument.venue_id",
        "strategy.strategy_id",
        "outcome.include_late_recorded",
    }),
    "report.calibration_terminal": frozenset({
        "actors.actor_id",
        "actors.agent_id",
        "actors.model_id",
        "actors.environment",
        "actors.run_id",
        "instrument.venue_id",
        "strategy.strategy_id",
        "outcome.include_late_recorded",
    }),
    "report.calibration_trajectory": frozenset({
        "actors.actor_id",
        "actors.agent_id",
        "actors.model_id",
        "actors.environment",
        "actors.run_id",
        "instrument.venue_id",
        "strategy.strategy_id",
        "outcome.include_late_recorded",
    }),
    "report.market_lifecycle": frozenset({
        "actors.actor_id",
        "instrument.instrument_id",
        "time_window.created_at_gte",
        "time_window.created_at_lt",
    }),
    "report.resolution_quality": frozenset({
        "actors.actor_id",
        "instrument.instrument_id",
        "time_window.created_at_gte",
        "time_window.created_at_lt",
        "time_window.resolved_at_gte",
        "time_window.resolved_at_lt",
        "outcome.resolution_status",
    }),
    "report.amm_slippage": frozenset({
        "actors.actor_id",
        "actors.agent_id",
        "actors.model_id",
        "actors.environment",
        "actors.run_id",
        "instrument.instrument_id",
        "decision.decision_type",
        "strategy.strategy_id",
        "time_window.decision_at_gte",
        "time_window.decision_at_lt",
    }),
    "report.time_decay_sharpening": frozenset({
        "actors.actor_id",
        "actors.agent_id",
        "actors.model_id",
        "actors.environment",
        "actors.run_id",
        "instrument.venue_id",
        "strategy.strategy_id",
        "outcome.include_late_recorded",
    }),
    # decision_velocity wires three filter leaves into its SQL today.
    "report.decision_velocity": frozenset({
        "time_window.decision_at_gte",
        "time_window.decision_at_lt",
        "decision.decision_type",
    }),
    # The remaining reports validate the filter shape but do not yet
    # join it into their SQL. Until they do, only the empty filter is
    # accepted so the agent sees a clean rejection instead of a silently
    # global result.
    "report.mistakes": frozenset(),
    "report.strengths": frozenset(),
    "report.process_analytics": frozenset({
        "decision.tags_any",
        "decision.tags_all",
        "strategy.strategy_id",
        "time_window.decision_at_gte",
        "time_window.decision_at_lt",
    }),
    "report.pnl": frozenset(),
    "report.watchlist": frozenset(),
    "report.lifecycle": frozenset({
        "actors.run_id",
        "instrument.instrument_id",
        "strategy.strategy_id",
        "time_window.created_at_gte",
        "time_window.created_at_lt",
        "time_window.decision_at_gte",
        "time_window.decision_at_lt",
    }),
    "report.work_queue": frozenset({
        "actors.run_id",
        "instrument.instrument_id",
        "strategy.strategy_id",
    }),
    "report.unscored_forecasts": frozenset(),
    "report.playbook_adherence": frozenset(),
    "report.strategy_health": frozenset({
        "actors.actor_id",
        "actors.agent_id",
        "actors.model_id",
        "actors.environment",
        "actors.run_id",
        "strategy.strategy_id",
        "time_window.created_at_gte",
        "time_window.created_at_lt",
    }),
    "report.operational_health": frozenset({
        "actors.run_id",
        "strategy.strategy_id",
        "instrument.instrument_id",
        "time_window.created_at_gte",
        "time_window.created_at_lt",
    }),
    "report.forecast_diagnostics": frozenset({
        "actors.actor_id",
        "actors.agent_id",
        "actors.model_id",
        "actors.environment",
        "actors.run_id",
        "instrument.instrument_id",
        "instrument.venue_id",
        "strategy.strategy_id",
        "decision.decision_type",
        "outcome.include_late_recorded",
    }),
    # The coach composes other reports; it inherits their support
    # contract by composition. Direct callers may only pass the empty
    # filter shape today.
    "report.coach": frozenset(),
    # report.risk has no filter leaves wired into its SQL today; only
    # the empty filter is accepted so the agent sees a clean rejection
    # instead of a silently broadened result.
    "report.risk": frozenset(),
    # report.opportunity currently reconstructs paths globally and rejects
    # non-empty filters until filter predicates are wired into the decision /
    # snapshot path query.
    "report.opportunity": frozenset(),
    # review.bundle scopes its decision selection through the same
    # actor/instrument/strategy spine as calibration, plus the
    # decision_at time window (the selection ordering uses
    # decisions.created_at).
    "review.bundle": frozenset({
        "actors.actor_id",
        "instrument.venue_id",
        "strategy.strategy_id",
        "time_window.decision_at_gte",
        "time_window.decision_at_lt",
    }),
}


def _default_filter_dump() -> dict[str, Any]:
    return ReportFilter().model_dump()


def _diff_paths(
    default: Any, actual: Any, *, prefix: str, out: list[str],
) -> None:
    if isinstance(default, dict) and isinstance(actual, dict):
        for key, default_child in default.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            actual_child = actual.get(key)
            _diff_paths(default_child, actual_child, prefix=child_prefix, out=out)
        return
    if default != actual:
        out.append(prefix)


def _non_default_leaf_paths(rf: ReportFilter) -> list[str]:
    """Return dotted leaf paths whose value differs from the default."""

    default = _default_filter_dump()
    actual = rf.model_dump()
    paths: list[str] = []
    _diff_paths(default, actual, prefix="", out=paths)
    return paths


def enforce_supported_filter(rf: ReportFilter, *, report: str) -> None:
    """Raise `UnsupportedFilterError` if `rf` carries a non-default value in
    a leaf path the named report does not declare as supported."""

    if report not in SUPPORTED_FILTER_FIELDS:
        raise KeyError(
            f"report {report!r} has no SUPPORTED_FILTER_FIELDS entry; "
            "add it to trade_trace.reports._filter_support before "
            "accepting any filter input"
        )
    supported = SUPPORTED_FILTER_FIELDS[report]
    unsupported = [p for p in _non_default_leaf_paths(rf) if p not in supported]
    if unsupported:
        raise UnsupportedFilterError(report, unsupported)


def _read_path(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        cur = cur[part]
    return cur


def _assign_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = data
    for part in parts[:-1]:
        cur = cur[part]
    cur[parts[-1]] = value


def applied_filter_view(rf: ReportFilter, *, report: str) -> dict[str, Any]:
    """Return the subset of `rf` the named report actually applies.

    Used by report functions to populate `summary.filter` and the
    per-group `filter` field. The returned dict starts from the default
    filter shape and only overlays the declared supported leaves so the
    echoed filter cannot claim a field was applied when it was not.
    """

    supported = SUPPORTED_FILTER_FIELDS.get(report, frozenset())
    actual = rf.model_dump()
    result = _default_filter_dump()
    for path in supported:
        _assign_path(result, path, _read_path(actual, path))
    return result


def process_filter(rf: ReportFilter, *, report: str) -> dict[str, Any]:
    """Combined enforce + applied_view helper per trade-trace-x0po
    (SIMP-007). Reports previously called `enforce_supported_filter`
    and `applied_filter_view` back-to-back with the same `report=...`
    string. A typo in either call meant the report and the filter
    declaration could drift silently; this helper takes the name once
    and is the canonical entry point for report bodies."""

    enforce_supported_filter(rf, report=report)
    return applied_filter_view(rf, report=report)


__all__ = [
    "SUPPORTED_FILTER_FIELDS",
    "UnsupportedFilterError",
    "applied_filter_view",
    "enforce_supported_filter",
    "process_filter",
]
