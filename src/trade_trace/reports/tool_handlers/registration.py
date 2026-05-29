"""Registration surface for report/agent/replay tools."""
# ruff: noqa: I001
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.reports import (
    report_mistakes, report_pnl, report_process_analytics, report_risk,
    report_strengths,
)
from trade_trace.reports.tool_schemas import _REPORT_SCHEMAS

from .audit_quality import _report_audit_readiness, _report_playbook_adherence, _report_source_quality
from .calibration_diagnostics import (
    _report_calibration, _report_calibration_advisory,
    _report_calibration_anchored, _report_calibration_integrity,
    _report_calibration_terminal, _report_mistake_tripwire, _report_process_quality,
    _report_resolution_misreads,
    _report_market_lifecycle, _report_resolution_quality,
    _report_time_decay_sharpening, _report_decision_velocity,
    _report_forecast_diagnostics, _report_unscored_forecasts,
)
from .common import _make_filter_only_report, _make_request_report
from .compare_policy_coach import (
    _report_coach, _report_compare, _report_filter_schema, _report_opportunity,
)
from trade_trace.reports.execution_quality import report_execution_quality
from trade_trace.reports.operational_health import report_operational_health
from .lifecycle_agent import (
    _agent_next_actions, _report_bootstrap, _report_lifecycle,
    _report_policy_candidates, _report_strategy_health, _report_work_queue,
)
from .memory_recall import _report_memory_usefulness, _report_recall_receipts
from .portfolio_exposure import (
    _report_current_exposure, _report_exposure_anomalies, _report_open_positions,
    _report_watchlist,
)
from .replay import _replay_case_bundle, _replay_evaluate_output

@dataclass(frozen=True)
class ReportToolRegistration:
    name: str
    handler: Any
    description: str = ""
    example_minimal: Mapping[str, Any] | None = None
    example_rich: Mapping[str, Any] | None = None
    json_schema: Mapping[str, Any] | None = None
    optional_keys: tuple[str, ...] | None = None
    usage_summary: str = ""
    examples: tuple[str, ...] | None = None
    enum_notes: Mapping[str, str] | None = None
    common_failures: tuple[str, ...] | None = None
    next_actions: tuple[str, ...] | None = None

    def register(self, registry: ToolRegistry) -> None:
        kwargs: dict[str, Any] = {}
        for key in (
            "description",
            "example_minimal",
            "example_rich",
            "json_schema",
            "optional_keys",
            "usage_summary",
            "examples",
            "enum_notes",
            "common_failures",
            "next_actions",
        ):
            value = getattr(self, key)
            if value is not None:
                kwargs[key] = value
        registry.register(self.name, self.handler, **kwargs)


_REPORT_TOOL_REGISTRATIONS: tuple[ReportToolRegistration, ...] = (
    ReportToolRegistration(
        "report.bootstrap",
        _report_bootstrap,
        description=(
            "Read-only local bootstrap packet for stateless agent continuity/session start. "
            "Composes only caller-supplied local journal state and local reports; no fetch, no market/source/outcome fetching, "
            "no broker/exchange access, no order preparation, no execution, no scheduler/daemon/alert creation, "
            "and no trading advice or market ranking/return-claim semantics. This report.* alias returns "
            "kind='agent.bootstrap' so the bootstrap.v0 contract is not forked."
        ),
        example_minimal={"as_of": "2026-01-20T00:00:00Z", "filter": {}},
        example_rich={
            "as_of": "2026-01-20T00:00:00Z",
            "filter": {"run_id": "run-a", "strategy_ids": ["strat-a"]},
            "sections": ["current_scope", "obligations", "memory_context", "caveats"],
            "budgets": {"max_chars_total": 24000, "default_max_items_per_section": 10, "include_memory_body": False},
        },
        optional_keys=("as_of", "filter", "sections", "budgets"),
        json_schema=_REPORT_SCHEMAS["report.bootstrap"],
        usage_summary="Generate a deterministic JSON bootstrap packet from local read models for agent continuity; no writes, fetches, execution, scheduling, or advice.",
        examples=(
            "tt report bootstrap --home <journal-home> --as-of 2026-01-20T00:00:00Z --filter-json '{}'",
            "tt report bootstrap --home <journal-home> --filter-json '{\"run_id\":\"run-a\",\"strategy_ids\":[\"strat-a\"]}' --budgets-json '{\"max_chars_total\":24000}'",
        ),
        common_failures=(
            "Non-empty unsupported bootstrap filters are rejected with VALIDATION_ERROR instead of being ignored.",
            "strategy_ids must contain exactly one strategy id when supplied.",
            "Too-small max_chars_total returns VALIDATION_ERROR if required metadata cannot fit.",
        ),
        next_actions=(
            "Use source_refs and suggested_process_calls for local drilldowns; callers choose whether to run any follow-up.",
            "Treat partial/truncated sections as absence-unsafe; check truncation and omitted_counts before relying on missing items.",
        ),
    ),
    ReportToolRegistration(
        "agent.bootstrap",
        _report_bootstrap,
        description=(
            "Agent-facing MCP/CLI alias for the same read-only bootstrap.v0 contract as report.bootstrap. "
            "Returns kind='agent.bootstrap' and composes only caller-supplied local journal state and local reports; "
            "no fetch, no market/source/outcome fetching, no broker/exchange access, no order preparation, no execution, "
            "no scheduler/daemon/alert creation, and no trading advice or market ranking/return-claim semantics."
        ),
        example_minimal={"as_of": "2026-01-20T00:00:00Z", "filter": {}},
        example_rich={
            "as_of": "2026-01-20T00:00:00Z",
            "filter": {"run_id": "run-a", "strategy_ids": ["strat-a"]},
            "sections": ["current_scope", "obligations", "memory_context", "caveats"],
            "budgets": {"max_chars_total": 24000, "default_max_items_per_section": 10, "include_memory_body": False},
        },
        optional_keys=("as_of", "filter", "sections", "budgets"),
        json_schema=_REPORT_SCHEMAS["report.bootstrap"],
        usage_summary="Agent-facing alias that generates the same deterministic JSON bootstrap packet as report.bootstrap; no writes, fetches, execution, scheduling, or advice.",
        examples=(
            "tt agent bootstrap --home <journal-home> --as-of 2026-01-20T00:00:00Z --filter-json '{}'",
            "tt agent bootstrap --home <journal-home> --filter-json '{\"run_id\":\"run-a\",\"strategy_ids\":[\"strat-a\"]}' --budgets-json '{\"max_chars_total\":24000}'",
        ),
        common_failures=(
            "Non-empty unsupported bootstrap filters are rejected with VALIDATION_ERROR instead of being ignored.",
            "strategy_ids must contain exactly one strategy id when supplied.",
            "Too-small max_chars_total returns VALIDATION_ERROR if required metadata cannot fit.",
        ),
        next_actions=(
            "Use source_refs and suggested_process_calls for local drilldowns; callers choose whether to run any follow-up.",
            "Treat partial/truncated sections as absence-unsafe; check truncation and omitted_counts before relying on missing items.",
        ),
    ),
    ReportToolRegistration(
        "replay.case_bundle",
        _replay_case_bundle,
        description=(
            "Read-only deterministic local replay.case_bundle export for process regression. Packages only caller-supplied "
            "journal rows available at as_of; hides future outcomes/scores/reflections from candidate context unless "
            "evaluation labels are explicitly requested, and then labels are top-level evaluator-only. No fetch, model runner, "
            "market simulator, backtester, broker/execution path, profit proof, or trading advice."
        ),
        example_minimal={"as_of": "2026-01-20T00:00:00Z", "case_selection": {"max_cases": 10}},
        optional_keys=("kind", "contract_version", "case_selection", "task", "budgets"),
        json_schema=_REPORT_SCHEMAS["replay.case_bundle"],
        usage_summary="Export deterministic local point-in-time replay cases; no writes, fetches, model runs, simulation, or advice.",
    ),
    ReportToolRegistration(
        "replay.evaluate_output",
        _replay_evaluate_output,
        description=(
            "Read-only deterministic replay candidate-output process checker over caller-supplied case_bundle and "
            "candidate_output objects. Returns machine-readable pass/fail/ambiguous/not_applicable criteria. No fetch, "
            "model runner, market simulator, backtester, broker/execution path, profit proof, or trading advice."
        ),
        example_minimal={"case_bundle": {"kind": "replay.case_bundle", "contract_version": "replay.case_bundle.v0", "cases": []}, "candidate_output": {}},
        optional_keys=("kind", "contract_version", "rubric_version"),
        json_schema=_REPORT_SCHEMAS["replay.evaluate_output"],
        usage_summary="Evaluate a candidate replay output for structural process criteria only; no writes, fetches, model runs, scoring engine, simulation, or advice.",
    ),
    ReportToolRegistration(
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
    ),
    ReportToolRegistration(
        "report.execution_quality",
        lambda args, ctx: report_execution_quality(args),
        description=(
            "Read-only local execution-quality/slippage diagnostics over imported external receipts, "
            "pre-trade intents, and local snapshots. Surfaces missing/stale snapshots, partial fills, "
            "rejections, cancel failures, stale open imported receipt evidence, adverse/improved fills, "
            "and sparse-sample caveats. No fetch, broker access, execution, cancellation, remediation, "
            "trade advice, alpha, or profit claims."
        ),
        optional_keys=("pretrade_intent_id", "market_id", "instrument_id", "lifecycle_state", "as_of", "limit", "min_sample", "stale_snapshot_minutes", "stale_open_minutes"),
        json_schema=_REPORT_SCHEMAS["report.execution_quality"],
        usage_summary="Diagnose imported execution evidence quality from local records only; no writes, fetches, execution, remediation, or advice.",
    ),
    ReportToolRegistration(
        "report.operational_health",
        lambda args, ctx: report_operational_health(args),
        description=(
            "Read-only local operational health report over trader-intelligence inputs: imported snapshots, "
            "reconciliations, external receipts, approvals, risk-check receipts, autonomous run/incident records, "
            "source evidence, and work-queue obligations. Surfaces stale/missing/sparse/unresolved inputs with stable "
            "codes and contributing local record ids. No fetch, scheduling, alerting, supervision, execution, "
            "remediation, advice, alpha, or profit claims."
        ),
        optional_keys=("filter", "as_of", "limit", "stale_snapshot_minutes", "stale_receipt_minutes", "stale_reconciliation_minutes", "stale_evidence_minutes"),
        json_schema=_REPORT_SCHEMAS["report.operational_health"],
        usage_summary="Summarize local trader-intelligence input health; read-only and local-evidence-only.",
    ),
    ReportToolRegistration(
        "report.calibration",
        _report_calibration,
        description=(
            "Calibration metric panel over scored binary forecasts: Brier, "
            "log score, ECE (equal-mass bins), sharpness, baseline + "
            "skill, plus reliability bins (scoring.md §7). Excludes "
            "late-recorded forecasts by default per dogfood-protocol §2.2 "
            "(opt in via filter.outcome.include_late_recorded). Emits a "
            "sample_warning when N < min_sample (default 20). Embeds the "
            "six anti-goodhart hygiene diagnostics from "
            "report.calibration_integrity under data.integrity_diagnostics."
        ),
        json_schema=_REPORT_SCHEMAS["report.calibration"]
    ),
    ReportToolRegistration(
        "report.calibration_advisory",
        _report_calibration_advisory,
        description=(
            "Decision-time recalibration for a candidate forecast probability: "
            "given the YES probability you are about to commit, returns your own "
            "prior resolved forecasts in that equal-width 0.1 band, their "
            "observed resolution rate, and a calibration-derived "
            "suggested_probability (band gap = observed_frequency - "
            "mean_probability). Read-only, deterministic, no trade advice. "
            "Excludes late-recorded forecasts by default per dogfood-protocol §2.2."
        ),
        example_minimal={"probability": 0.7, "filter": {}},
        json_schema=_REPORT_SCHEMAS["report.calibration_advisory"],
    ),
    ReportToolRegistration(
        "report.calibration_anchored",
        _report_calibration_anchored,
        description="Calibration over scored binary forecasts anchored to caller-supplied local market snapshots; baseline and skill use snapshot implied probabilities.",
        optional_keys=("filter", "min_sample"),
        json_schema=_REPORT_SCHEMAS["report.calibration"],
    ),
    ReportToolRegistration(
        "report.calibration_terminal",
        _report_calibration_terminal,
        description="Calibration over scored binary forecasts with terminal local market snapshot baseline at or before resolution; no network or live market fetch.",
        optional_keys=("filter", "min_sample"),
        json_schema=_REPORT_SCHEMAS["report.calibration"],
    ),
    ReportToolRegistration(
        "report.market_lifecycle",
        _report_market_lifecycle,
        description="Local market lifecycle durations and engagement counts across open/closed/resolving/resolved states; no external market calls.",
        optional_keys=("filter",),
        json_schema=_REPORT_SCHEMAS["report.market_lifecycle"],
    ),
    ReportToolRegistration(
        "report.resolution_quality",
        _report_resolution_quality,
        description="Local resolution quality diagnostics: status mix, ambiguous/void/disputed/cancelled counts, and pre-resolution uncertainty flags.",
        optional_keys=("filter",),
        json_schema=_REPORT_SCHEMAS["report.resolution_quality"],
    ),
    ReportToolRegistration(
        "report.time_decay_sharpening",
        _report_time_decay_sharpening,
        description="Time-to-resolution sharpening diagnostics for scored binary forecasts, grouped by hours before resolution.",
        optional_keys=("filter", "min_sample"),
        json_schema=_REPORT_SCHEMAS["report.time_decay_sharpening"],
    ),
    ReportToolRegistration(
        "report.forecast_diagnostics",
        _report_forecast_diagnostics,
        description=(
            "Binary-first retrospective diagnostics over local forecasts, outcomes, decisions/non-actions, "
            "and caller-supplied snapshot market/reference fields. Reports Brier/reliability/base-rate "
            "caveats and recorded_market_reference_gap only when snapshots.implied_probability was stored; "
            "the gap is a caller-supplied retrospective reference comparison, not a trading signal. "
            "No external fetching, trading advice, alpha/profit claim, or performance ranking."
        ),
        example_minimal={"filter": {}, "min_sample": 20},
        optional_keys=("filter", "min_sample"),
        json_schema=_REPORT_SCHEMAS["report.forecast_diagnostics"],
    ),
    ReportToolRegistration(
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
    ),
    ReportToolRegistration(
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
    ),
    ReportToolRegistration(
        "report.audit_readiness",
        _report_audit_readiness,
        description=(
            "Read-only prediction/event-market audit-readiness diagnostics: "
            "resolution-rule provenance, snapshot age, market microstructure, "
            "source freshness/contradictions, and decision provenance. "
            "Deterministic local report; no network and no trading advice."
        ),
        example_minimal={"stale_snapshot_threshold_days": 1, "stale_source_threshold_days": 7},
        optional_keys=("stale_snapshot_threshold_days", "stale_source_threshold_days"),
        json_schema=_REPORT_SCHEMAS["report.audit_readiness"],
    ),
    ReportToolRegistration(
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
    ),
    ReportToolRegistration(
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
    ),
    ReportToolRegistration(
        "report.decision_velocity",
        _report_decision_velocity,
        description=(
            "Decision counts bucketed by day or week over the filter's "
            "decision_at_* window. Bucket boundaries are UTC-aligned; "
            "groups[] are ordered by bucket key ascending."
        ),
        json_schema=_REPORT_SCHEMAS["report.decision_velocity"]
    ),
    ReportToolRegistration(
        "report.mistakes",
        _make_filter_only_report(report_mistakes),
        description=(
            "Tag-aggregated recurring patterns ranked by mean Brier of "
            "associated scored forecasts (worst first). Per-group metrics: "
            "decision_count, scored_forecast_count, mean_brier."
        ),
        json_schema=_REPORT_SCHEMAS["report.mistakes"]
    ),
    ReportToolRegistration(
        "report.mistake_tripwire",
        _report_mistake_tripwire,
        description=(
            "Decision-time recurring-mistake trip-wire: given the tag fingerprint "
            "of a decision you are about to make, fire — without an explicit recall "
            "query — the candidate tags that match your own poorly-calibrated "
            "patterns (mean Brier >= threshold over >= min_sample scored "
            "forecasts), with the prior failing decisions/forecasts. Read-only, "
            "deterministic, no trade advice."
        ),
        example_minimal={"tags": ["chased_momentum"]},
        json_schema=_REPORT_SCHEMAS["report.mistake_tripwire"],
    ),
    ReportToolRegistration(
        "report.process_quality",
        _report_process_quality,
        description=(
            "Score declared bet SIZE against declared EDGE (Kelly-consistency) "
            "and direction over sized entry decisions, computed WITHOUT consulting "
            "any resolution/outcome — process quality, not outcome quality, so the "
            "agent does not learn the wrong lesson from variance. Per-decision "
            "stated_edge/kelly_fraction/direction_consistent; summary "
            "kelly_alignment and direction_consistency_rate. Deterministic, no "
            "trade advice."
        ),
        example_minimal={},
        json_schema=_REPORT_SCHEMAS["report.process_quality"],
    ),
    ReportToolRegistration(
        "report.resolution_misreads",
        _report_resolution_misreads,
        description=(
            "Compare the agent's recorded resolution-criteria interpretation "
            "(forecast.interpret_resolution) against each market's actual "
            "resolution source. A contract_misread — interpreted source != actual "
            "source on a resolved market — is a distinct error class from "
            "calibration error (right about the world, wrong about the contract). "
            "Diagnostic, not trade advice."
        ),
        example_minimal={},
        json_schema=_REPORT_SCHEMAS["report.resolution_misreads"],
    ),
    ReportToolRegistration(
        "report.strengths",
        _make_filter_only_report(report_strengths),
        description=(
            "Tag-aggregated patterns ranked by mean Brier (best first). "
            "Mirror of report.mistakes."
        ),
        json_schema=_REPORT_SCHEMAS["report.strengths"]
    ),
    ReportToolRegistration(
        "report.process_analytics",
        _make_request_report(report_process_analytics),
        description=(
            "Decision-tags-only process analytics MVP: tag frequency and "
            "tag-pair co-occurrence over local decision_tags, with explicit "
            "unsupported metadata for review/review_tags and cost-family analytics."
        ),
        json_schema=_REPORT_SCHEMAS["report.process_analytics"]
    ),
    ReportToolRegistration(
        "report.pnl",
        _make_filter_only_report(report_pnl),
        description=(
            "Realized + unrealized + mark-to-market P&L over the positions "
            "projection. Per-instrument groups; summary carries "
            "open_mark_coverage (open positions with marks / open positions). "
            "Reads the rebuildable positions projection (trade-trace-5zg). "
            "This is a lower-level P&L report: for open trades/current exposure, "
            "start with report.current_exposure; for row-level open-position detail, "
            "use report.open_positions. Trade Trace records local journal/projection "
            "state only; it does not execute trades or prove broker portfolio truth."
        ),
        json_schema=_REPORT_SCHEMAS["report.pnl"],
        usage_summary=(
            "Use for realized/unrealized/MTM P&L over local projection rows. Do not use as the first source for "
            "open trades/current exposure; start with report.current_exposure or report.open_positions."
        ),
        examples=(
            "tt report pnl --home <journal-home>",
            "tt report current_exposure --home <journal-home>",
            "tt report open_positions --home <journal-home>",
        ),
        next_actions=(
            "If summary.metrics.open_position_count > 0, run report.current_exposure for the recommended agent packet or report.open_positions for row-level open-position detail.",
            "State that P&L/open-position rows are local journal/projection records; Trade Trace does not execute trades or prove broker portfolio truth.",
        ),
    ),
    ReportToolRegistration(
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
    ),
    ReportToolRegistration(
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
    ),
    ReportToolRegistration(
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
        json_schema=_REPORT_SCHEMAS["report.compare"],
        usage_summary="Compare calibration or pnl metrics across one allowlisted dimension using optional shared report filters.",
        examples=("tt report compare --base-report calibration --group-by strategy_id --filter-json '{}'",),
        enum_notes={"base_report": "calibration or pnl", "group_by": "Allowed values depend on base_report and are validated by the report schema."},
        common_failures=("group_by is not allowed for the selected base_report.",),
        next_actions=("Use report.filter_schema to build the filter object before calling report.compare.",),
    ),
    ReportToolRegistration(
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
    ),
    ReportToolRegistration(
        "report.lifecycle",
        _report_lifecycle,
        description=(
            "Read-only derived lifecycle report for local decision, forecast, and material non-action cases. "
            "Returns lifecycle_cases and groups with stable states/status, reason/caveat codes, source_refs, "
            "record_ids, due_at, thresholds, and timestamps. Supports ReportFilter strategy/instrument/run/date "
            "plus states/status, as_of, and stale_threshold_days. No writes, no scheduling, no recommendations."
        ),
        example_minimal={"filter": {}, "states": ["pending_review"], "as_of": "2026-01-20T00:00:00Z", "stale_threshold_days": 14},
        optional_keys=("filter", "states", "status", "as_of", "stale_threshold_days"),
        json_schema=_REPORT_SCHEMAS["report.lifecycle"],
    ),
    ReportToolRegistration(
        "report.strategy_health",
        _report_strategy_health,
        description=(
            "Deterministic read-only local strategy process-health report across strategies. Identifies review_due, "
            "low_n, open unresolved forecasts, thesis source-reference gaps, repeated overrides, and local "
            "policy-candidate support status. Defaults to active strategies; ordering is administrative "
            "review_due-first then slug/id, not profit/performance ranking. No network, execution, "
            "edge/signal detection, or trading advice."
        ),
        example_minimal={"filter": {}, "status": "active", "as_of": "2026-01-20T00:00:00Z", "min_sample": 5},
        optional_keys=("filter", "status", "as_of", "min_sample"),
        json_schema=_REPORT_SCHEMAS["report.strategy_health"],
    ),
    ReportToolRegistration(
        "report.recall_receipts",
        _report_recall_receipts,
        description=(
            "Read-only computed recall receipts over memory_recall_events, returned memory nodes, "
            "and downstream typed edge evidence. Returns query/context/strategies, actor/model/run "
            "metadata, returned node IDs, cited_or_used vs ignored_or_unattributed status, source_refs, "
            "and stale/contradicted caveats. Does not create receipt tables or transcript memory."
        ),
        example_minimal={"recall_id": "recall_..."},
        optional_keys=("recall_id", "node_id", "consumer_kind", "consumer_id", "run_id", "agent_id", "model_id", "environment", "instrument_id", "strategy_id", "as_of", "limit"),
        json_schema=_REPORT_SCHEMAS["report.recall_receipts"],
    ),
    ReportToolRegistration(
        "report.memory_usefulness",
        _report_memory_usefulness,
        description=(
            "Read-only diagnostic projection over recall receipts and typed edge evidence. "
            "Includes negative controls: recalled-unused, used-contradicted, stale-retrieved, "
            "high-confidence bad-outcome (edge-based only), missing-expected-memory (caveated), "
            "and overfit/harmful (edge-based only). No causal memory value, profit, signal, or advice claims."
        ),
        example_minimal={"recall_id": "recall_...", "as_of": "2026-01-20T00:00:00Z"},
        optional_keys=("recall_id", "node_id", "consumer_kind", "consumer_id", "run_id", "agent_id", "model_id", "environment", "instrument_id", "strategy_id", "memory_kind", "as_of", "limit"),
        json_schema=_REPORT_SCHEMAS["report.memory_usefulness"],
    ),
    ReportToolRegistration(
        "report.policy_candidates",
        _report_policy_candidates,
        description=(
            "Read-only report over quarantined/candidate policy reflection metadata. "
            "Surfaces source-backed support/contradiction, scope, missing evidence, replay refs, and reasons not promoted; no writes, promotion, fetch, model advice, or performance claims."
        ),
        example_minimal={"status": "candidate", "as_of": "2026-01-20T00:00:00Z"},
        optional_keys=("status", "strategy_id", "playbook_id", "as_of", "limit"),
        json_schema=_REPORT_SCHEMAS["report.policy_candidates"],
    ),
    ReportToolRegistration(
        "report.work_queue",
        _report_work_queue,
        description=(
            "Read-only derived process-obligation report over lifecycle cases. Each item includes kind, priority, caveat, source_refs, reason, allowed_actions, forbidden_actions, and closure_condition. "
            "No writes, no durable tasks, no scheduling, no assignment, no external fetching, no broker/execution path, and no trading advice."
        ),
        example_minimal={"filter": {}, "as_of": "2026-01-20T00:00:00Z", "stale_threshold_days": 14},
        optional_keys=("filter", "as_of", "stale_threshold_days", "kinds", "kind"),
        json_schema=_REPORT_SCHEMAS["report.work_queue"],
    ),
    ReportToolRegistration(
        "agent.next_actions",
        _agent_next_actions,
        description=(
            "Safe projection/alias over report.work_queue for agent session startup. Returns process-safe allowed_actions only; not a planner, scheduler, daemon, assignment system, broker/execution path, fetcher, or advice surface."
        ),
        example_minimal={"filter": {}, "as_of": "2026-01-20T00:00:00Z", "stale_threshold_days": 14},
        optional_keys=("filter", "as_of", "stale_threshold_days", "kinds", "kind"),
        json_schema=_REPORT_SCHEMAS["agent.next_actions"],
    ),
    ReportToolRegistration(
        "report.open_positions",
        _report_open_positions,
        description=(
            "Row-level open trades/current exposure from the canonical "
            "positions projection and position_events lineage. Defaults to "
            "open/partial positions only; closed positions are excluded. "
            "Agents must not infer current exposure from unclosed decisions, "
            "watch decisions, or record-only actual decisions without a linked "
            "position projection/event. Returns positive empty results with "
            "count=0 and NO_OPEN_POSITIONS."
        ),
        example_minimal={"limit": 100},
        optional_keys=(
            "limit",
            "cursor",
            "kind",
            "instrument_id",
            "strategy_id",
            "stale_mark_threshold_days",
            "as_of",
        ),
        json_schema=_REPORT_SCHEMAS["report.open_positions"],
        usage_summary="List canonical row-level open positions/current exposure; do not query or infer from decisions.",
        examples=("tt report open_positions --home <journal-home>",),
        next_actions=("Use these rows directly to summarize open exposure; do not run raw SQLite for open positions.",),
    ),
    ReportToolRegistration(
        "report.exposure_anomalies",
        _report_exposure_anomalies,
        description=(
            "Read-only current-exposure ambiguity/data-quality caveat report. "
            "Surfaces projection_anomalies with stable codes for duplicate entry "
            "decisions, decisions without linked position_events, record-only actual "
            "journal rows, missing/stale marks, and missing/stale projections. "
            "This is not market risk and does not assert broker truth."
        ),
        example_minimal={"stale_mark_threshold_days": 14},
        optional_keys=("stale_mark_threshold_days", "as_of"),
        json_schema=_REPORT_SCHEMAS["report.exposure_anomalies"],
        usage_summary="List local journal/projection anomalies that caveat current-exposure answers; do not treat them as open trades.",
        examples=("tt report exposure_anomalies --home <journal-home>",),
        next_actions=("Use report.open_positions for canonical exposure rows; mention these caveats separately.",),
    ),
    ReportToolRegistration(
        "report.current_exposure",
        _report_current_exposure,
        description=(
            "Recommended trader-agent entry point for open trades/current exposure/recent trading activity. "
            "Composes canonical open_positions, local event_exposure_sets grouping/netting diagnostics, WATCH_ONLY_IDEA watchlist rows, recent_trade_activity journal rows, "
            "and projection_anomalies in one read-only packet. Decisions are activity/audit trail, not canonical exposure; "
            "negative-risk metadata is caveated only and never converted/redeemed/settled; actual-recorded rows are record-only without linked position_events/projection. Does not assert broker truth."
        ),
        example_minimal={"recent_limit": 10, "include_watchlist": True, "include_anomalies": True},
        optional_keys=("recent_limit", "include_watchlist", "include_anomalies", "kind", "instrument_id", "strategy_id", "stale_mark_threshold_days", "as_of"),
        json_schema=_REPORT_SCHEMAS["report.current_exposure"],
        usage_summary="Recommended trader-agent entry point for answering open trades/current exposure and recently traded questions without raw queries.",
        examples=("tt report current_exposure --home <journal-home> --recent-limit 10",),
        next_actions=("Use open_positions for canonical exposure; mention watchlist/recent activity/anomalies separately as caveats/context.",),
    ),
    ReportToolRegistration(
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
)


def register_report_tools(registry: ToolRegistry) -> None:
    """Register `report.*` tools on the supplied registry."""

    for registration in _REPORT_TOOL_REGISTRATIONS:
        registration.register(registry)

__all__ = [name for name in globals() if not name.startswith("__")]
