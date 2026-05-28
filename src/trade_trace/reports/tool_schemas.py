"""JSON schemas for the report.*/agent/replay tool surface.

Kept outside ``trade_trace.tools.reports`` so the tool module can focus on
compatibility wrappers and registration while PM report-family modules evolve.
"""

from __future__ import annotations

from typing import Any

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

_BOOTSTRAP_FILTER_PROP = {
    "type": "object",
    "description": (
        "Bootstrap request filter. Currently supported by the composed read model: "
        "run_id and exactly one strategy_ids entry. Contract-recognized filters "
        "such as actor_id, agent_id, model_id, environment, symbols, tags, since, "
        "and until are rejected when non-empty until all composed local reports support them."
    ),
    "properties": {
        "run_id": {"type": "string"},
        "strategy_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 1},
        "actor_id": {"type": "string"},
        "agent_id": {"type": "string"},
        "model_id": {"type": "string"},
        "environment": {"type": "string"},
        "symbols": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "since": {"type": "string", "format": "date-time"},
        "until": {"type": "string", "format": "date-time"},
    },
}

_BOOTSTRAP_BUDGETS_PROP = {
    "type": "object",
    "description": "Hard output budgets for bootstrap packet sections and total serialized size.",
    "properties": {
        "max_chars_total": {"type": "integer", "minimum": 1},
        "default_max_items_per_section": {"type": "integer", "minimum": 0},
        "default_max_chars_per_section": {"type": "integer", "minimum": 1},
        "sections": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "max_items": {"type": "integer", "minimum": 0},
                    "max_chars": {"type": "integer", "minimum": 1},
                },
            },
        },
        "include_memory_body": {"type": "boolean"},
        "include_sensitive_sources": {"type": "boolean"},
    },
}


_REPORT_SCHEMAS: dict[str, dict[str, Any]] = {
    "report.bootstrap": _schema(
        {
            "as_of": {"type": "string", "format": "date-time", "description": "Deterministic read boundary echoed in data.metadata.as_of."},
            "filter": _BOOTSTRAP_FILTER_PROP,
            "sections": {"type": "array", "items": {"type": "string"}, "description": "Optional bootstrap sections to include; omitted sections remain present with omission caveats."},
            "budgets": _BOOTSTRAP_BUDGETS_PROP,
        },
        description=(
            "Read-only local bootstrap packet for stateless agent continuity. JSON-first, no fetch, no execution, "
            "no scheduler, no trading advice, and no market ranking or return-claim semantics. Returns kind='agent.bootstrap' "
            "per shared contract alias policy."
        ),
    ),
    "replay.case_bundle": _schema(
        {
            "kind": {"type": "string", "const": "replay.case_bundle"},
            "contract_version": {"type": "string", "const": "replay.case_bundle.v0"},
            "as_of": {"type": "string", "format": "date-time", "description": "Required point-in-time UTC boundary; response normalizes to Z."},
            "case_selection": {"type": "object", "description": "Select deterministic v0 case_ids, explicit decision/forecast/recall_event source_refs, or safe filters plus max_cases. Unsupported non-empty filters are rejected."},
            "task": {"type": "object", "description": "Task mode; defaults blind_decision. include_evaluation_labels defaults false and, when true, labels are top-level only."},
            "budgets": {"type": "object", "description": "Hard local output/redaction budgets echoed as effective budgets."},
        },
        required=["as_of"],
        description=(
            "Read-only deterministic local replay case bundle export over caller-supplied journal rows. "
            "No fetch, no model runner, no market simulator, no backtester, no broker/execution path, "
            "no profit proof, and no trading advice. Future outcomes/labels are withheld from candidate context."
        ),
    ),
    "replay.evaluate_output": _schema(
        {
            "kind": {"type": "string", "const": "replay.evaluate_output"},
            "contract_version": {"type": "string", "const": "replay.evaluate_output.v0"},
            "case_bundle": {"type": "object", "description": "Required replay.case_bundle data payload supplied by caller."},
            "candidate_output": {"type": "object", "description": "Required candidate agent output object to check."},
            "rubric_version": {"type": "string", "description": "Optional rubric version; defaults replay.rubric.v0."},
        },
        required=["case_bundle", "candidate_output"],
        description=(
            "Read-only deterministic replay candidate-output process checker over caller-supplied objects. "
            "No DB writes, no fetch, no model runner, no market simulator, no backtester, profit proof, or trading advice."
        ),
    ),
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
    "report.calibration_trajectory": _schema(
        {"filter": _FILTER_PROP, "min_sample": {"type": "integer", "minimum": 1}},
        description="Time-to-resolution trajectory calibration over local scored binary forecasts; no external calls.",
    ),
    "report.market_lifecycle": _schema(
        {"filter": _FILTER_PROP},
        description="Local market lifecycle timing and engagement counts over caller-recorded market rows.",
    ),
    "report.resolution_quality": _schema(
        {"filter": _FILTER_PROP},
        description="Local resolution status quality diagnostics and pre-resolution uncertainty flags.",
    ),
    "report.amm_slippage": _schema(
        {"filter": _FILTER_PROP},
        description="AMM decision price versus linked local snapshot mark in basis points; no broker or external quote path.",
    ),
    "report.time_decay_sharpening": _schema(
        {"filter": _FILTER_PROP, "min_sample": {"type": "integer", "minimum": 1}},
        description="Time-to-resolution sharpening diagnostics grouped by local forecast age-to-resolution buckets.",
    ),
    "report.forecast_diagnostics": _schema(
        {"filter": _FILTER_PROP, "min_sample": {"type": "integer", "minimum": 1}},
        description=(
            "Binary-first retrospective diagnostics over local forecasts, scored outcomes, decisions, "
            "and caller-supplied snapshots.implied_probability; recorded_market_reference_gap is a "
            "caller-supplied retrospective reference comparison, not a trading signal. No external fetching, "
            "trading advice, alpha/profit claim, or performance ranking."
        ),
    ),
    "report.playbook_adherence": _schema(
        {
            "filter": _FILTER_PROP,
            "playbook_id": {"type": "string"},
            "strategy_id": {"type": "string"},
        },
        description="Optional ReportFilter plus top-level playbook_id/strategy_id scoping.",
    ),
    "report.policy_candidates": _schema(
        {
            "status": {"type": "string"},
            "strategy_id": {"type": "string"},
            "playbook_id": {"type": "string"},
            "as_of": {"type": "string", "format": "date-time"},
            "limit": {"type": "integer", "minimum": 1},
        },
        description=(
            "Read-only local report over reflection memory_nodes with meta_json.policy_candidate. "
            "Shows caveated candidate policy statements, support/contradiction, scope, missing evidence, replay refs, and reasons not promoted. No writes, promotion, fetching, model advice, or performance claims."
        ),
    ),
    "report.source_quality": _schema(
        {
            "stale_threshold_days": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Age threshold in days for stale_sources. The diagnostic "
                    "compares sources.freshness_at to the linked decision.created_at; "
                    "sources without freshness_at are skipped, and retrieved_at is "
                    "not used as a fallback."
                ),
            }
        },
        description=(
            "Global source provenance hygiene report. stale_sources is driven by "
            "sources.freshness_at (evidence-current time) versus decision.created_at; "
            "retrieved_at is retrieval/provenance time only and does not trigger stale diagnostics."
        ),
    ),
    "report.audit_readiness": _schema(
        {
            "stale_snapshot_threshold_days": {"type": "integer", "minimum": 0},
            "stale_source_threshold_days": {"type": "integer", "minimum": 0},
        },
        description="Read-only local prediction/event-market audit-readiness diagnostics; no network, no advice.",
    ),
    "report.calibration_integrity": _schema(
        # min_sample is accepted but currently unused by the integrity
        # panel; the schema declares it so a caller habitually passing
        # the same low-N threshold across the report.calibration family
        # gets a consistent rejection on negative values (bead
        # trade-trace-cms2). Sibling tools share the minimum:1 contract.
        {"min_sample": {"type": "integer", "minimum": 1}},
        description=(
            "Standalone anti-goodhart hygiene panel. min_sample is "
            "accepted for parity with the report.calibration family but "
            "currently unused; reserved for future denominator-coverage "
            "thresholds."
        ),
    ),
    "report.unscored_forecasts": _schema({"filter": _FILTER_PROP}),
    "report.decision_velocity": _schema(
        {"filter": _FILTER_PROP, "bucket": {"type": "string", "enum": ["day", "week"]}},
        description="bucket defaults to day; only day/week are accepted.",
    ),
    "report.mistakes": _schema({"filter": _FILTER_PROP}),
    "report.strengths": _schema({"filter": _FILTER_PROP}),
    "report.process_analytics": _schema(
        {
            "filter": _FILTER_PROP,
            "dimensions": {"type": "array", "items": {"type": "string"}},
            "group_by": {"type": "array", "items": {"type": "string"}},
            "metrics": {"type": "array", "items": {"type": "string"}},
            "features": {"type": "array", "items": {"type": "string"}},
            "include_costs": {"type": "boolean"},
            "min_sample": {"type": "integer", "minimum": 1},
            "max_groups": {"type": "integer", "minimum": 1},
            "max_record_ids_per_group": {"type": "integer", "minimum": 1},
            "as_of": {"type": "string"},
        },
        description=(
            "Decision-tags-only process analytics MVP: tag frequency and tag-pair "
            "co-occurrence over local decision_tags. Review/review_tags and cost-family "
            "analytics are explicitly unsupported metadata, not computed values."
        ),
    ) | {"additionalProperties": False},
    "report.pnl": _schema(
        {"filter": _FILTER_PROP},
        description=(
            "Lower-level P&L report over the local positions projection. Use for realized/unrealized/MTM P&L, "
            "not as the first answer to 'open trades' or 'current exposure'. For open trades/current exposure, "
            "start with report.current_exposure; for row-level open-position detail use report.open_positions. "
            "If summary.metrics.open_position_count > 0, run report.current_exposure or report.open_positions before "
            "answering exposure questions. Trade Trace records local journal/projection state only; it does not execute trades "
            "or prove broker portfolio truth."
        ),
    ),
    "report.risk": _schema({"filter": _FILTER_PROP}),
    "report.opportunity": _schema(
        {
            "filter": _FILTER_PROP,
            "minimum_coverage": {"type": "string", "enum": ["sparse", "partial", "complete"]},
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
    "report.strategy_health": _schema(
        {
            "filter": _FILTER_PROP,
            "status": {"type": "string", "enum": ["active", "archived", "all"]},
            "as_of": {"type": "string", "format": "date-time"},
            "min_sample": {"type": "integer", "minimum": 1},
        },
        description=(
            "Read-only local strategy process-health report over local caller-supplied records; defaults "
            "to active strategies. Ordering is administrative review_due-first, not profit/performance ranking. "
            "No network, execution, edge/signal detection, or trading advice."
        ),
    ),
    "report.watchlist": _schema(
        {
            "filter": _FILTER_PROP,
            "mode": {"type": "string", "enum": ["all", "stale"]},
            "stale_threshold_days": {"type": "integer", "minimum": 0},
        }
    ),
    "report.lifecycle": _schema(
        {
            "filter": _FILTER_PROP,
            "states": {"type": "array", "items": {"type": "string"}},
            "status": {"type": "string"},
            "as_of": {"type": "string", "format": "date-time"},
            "stale_threshold_days": {"type": "integer", "minimum": 0},
        },
        description="Read-only derived lifecycle cases; filter by ReportFilter plus states/status, as_of, and stale threshold.",
    ),
    "report.recall_receipts": _schema(
        {
            "recall_id": {"type": "string"},
            "node_id": {"type": "string"},
            "consumer_kind": {"type": "string", "enum": ["decision", "thesis", "forecast", "outcome", "review", "playbook_version"]},
            "consumer_id": {"type": "string"},
            "run_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "model_id": {"type": "string"},
            "environment": {"type": "string"},
            "instrument_id": {"type": "string"},
            "strategy_id": {"type": "string"},
            "as_of": {"type": "string", "format": "date-time"},
            "limit": {"type": "integer", "minimum": 1},
        },
        description="Read-only computed recall receipts over memory_recall_events, memory_nodes, and typed edge evidence.",
    ),
    "report.memory_usefulness": _schema(
        {
            "recall_id": {"type": "string"},
            "node_id": {"type": "string"},
            "consumer_kind": {"type": "string", "enum": ["decision", "thesis", "forecast", "outcome", "review", "playbook_version"]},
            "consumer_id": {"type": "string"},
            "run_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "model_id": {"type": "string"},
            "environment": {"type": "string"},
            "instrument_id": {"type": "string"},
            "strategy_id": {"type": "string"},
            "memory_kind": {"type": "string", "enum": ["observation", "reflection", "playbook_rule"]},
            "as_of": {"type": "string", "format": "date-time"},
            "limit": {"type": "integer", "minimum": 1},
        },
        description="Read-only diagnostic memory usefulness projection with explicit negative controls and no causal/profit/advice claims.",
    ),
    "report.work_queue": _schema(
        {
            "filter": _FILTER_PROP,
            "as_of": {"type": "string", "format": "date-time"},
            "stale_threshold_days": {"type": "integer", "minimum": 0},
            "kinds": {"type": "array", "items": {"type": "string"}},
            "kind": {"type": "string"},
        },
        description="Read-only derived process-obligation queue; not a scheduler, assignment, broker, execution, fetch, or advice path.",
    ),
    "agent.next_actions": _schema(
        {
            "filter": _FILTER_PROP,
            "as_of": {"type": "string", "format": "date-time"},
            "stale_threshold_days": {"type": "integer", "minimum": 0},
            "kinds": {"type": "array", "items": {"type": "string"}},
            "kind": {"type": "string"},
        },
        description="Safe projection/alias over report.work_queue; process actions only, no planner or execution semantics.",
    ),
    "report.open_positions": _schema(
        {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum open-position rows to return; defaults to the positions page default.",
            },
            "cursor": {
                "type": "string",
                "description": "Opaque pagination cursor from a previous report.open_positions response.",
            },
            "kind": {
                "type": "string",
                "enum": ["paper", "actual", "simulation"],
                "description": "Optional position kind filter. Omit to include all open exposure kinds.",
            },
            "instrument_id": {"type": "string"},
            "strategy_id": {"type": "string"},
            "stale_mark_threshold_days": {
                "type": "integer",
                "minimum": 0,
                "description": "Age threshold in days for latest snapshot/mark caveats; defaults to 14.",
            },
            "as_of": {
                "type": "string",
                "format": "date-time",
                "description": "Optional ISO timestamp used to evaluate stale latest marks; defaults to current UTC.",
            },
        },
        description=(
            "Read-only current-exposure report: canonical row-level open positions "
            "from the positions projection/position_events lineage. Defaults to open "
            "and partial positions only; closed positions and unclosed decisions are not "
            "current exposure. Includes latest snapshot mark metadata when available and "
            "flags stale marks by stale_mark_threshold_days. Do not infer open trades from "
            "decisions or watches."
        ),
    ),
    "report.exposure_anomalies": _schema(
        {
            "stale_mark_threshold_days": {
                "type": "integer",
                "minimum": 0,
                "description": "Age threshold in days for latest snapshot/mark anomalies; defaults to 14.",
            },
            "as_of": {
                "type": "string",
                "format": "date-time",
                "description": "Optional ISO timestamp used to evaluate stale latest marks; defaults to current UTC.",
            },
        },
        description=(
            "Read-only current-exposure ambiguity/data-quality caveat report. "
            "Returns projection_anomalies with stable codes including "
            "ENTRY_DECISION_WITHOUT_POSITION_EVENT, DUPLICATE_DECISIONS, "
            "RECORD_ONLY_ACTUAL, MISSING_MARK, STALE_MARK, PROJECTION_MISSING, "
            "and PROJECTION_STALE. This reports local journal/projection data quality, "
            "not market risk or broker truth."
        ),
    ),
    "report.current_exposure": _schema(
        {
            "recent_limit": {"type": "integer", "minimum": 0, "description": "Maximum recent trade-typed decision rows to return; defaults to 10."},
            "include_watchlist": {"type": "boolean", "description": "Include watchlist bucket; defaults true. Watches are WATCH_ONLY_IDEA and never exposure."},
            "include_anomalies": {"type": "boolean", "description": "Include projection_anomalies bucket; defaults true."},
            "kind": {"type": "string", "enum": ["paper", "actual", "simulation"]},
            "instrument_id": {"type": "string"},
            "strategy_id": {"type": "string"},
            "stale_mark_threshold_days": {"type": "integer", "minimum": 0},
            "as_of": {"type": "string", "format": "date-time"},
        },
        description=(
            "Recommended trader-agent entry point for open trades/current exposure/recent trading activity. "
            "Returns open_positions, event_exposure_sets, watchlist, recent_trade_activity, and projection_anomalies in one packet. "
            "Current exposure comes from positions/position_events; event_exposure_sets are local derived grouping/netting diagnostics with negative-risk caveats only; watchlist rows are WATCH_ONLY_IDEA; recent_trade_activity "
            "is journal activity and not canonical exposure by itself."
        ),
    ),
    "report.coach": _schema(
        {"filter": _FILTER_PROP, "stale_threshold_days": {"type": "integer", "minimum": 0}}
    ),
}


__all__ = ["_EMPTY_SCHEMA", "_REPORT_SCHEMAS"]
