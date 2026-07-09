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
        "ReportFilter object; accepted fields vary by report and unsupported "
        "non-default leaves are rejected."
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
    "report.calibration": _schema(
        {"filter": _FILTER_PROP, "min_sample": {"type": "integer", "minimum": 1}},
        description="Optional ReportFilter and low-N warning threshold; defaults min_sample=20.",
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
    "report.execution_quality": _schema(
        {
            "pretrade_intent_id": {"type": "string"},
            "market_id": {"type": "string"},
            "instrument_id": {"type": "string"},
            "lifecycle_state": {"type": "string"},
            "as_of": {"type": "string", "format": "date-time"},
            "limit": {"type": "integer", "minimum": 1},
            "min_sample": {"type": "integer", "minimum": 1},
            "stale_snapshot_minutes": {"type": "number", "minimum": 0},
            "stale_open_minutes": {"type": "number", "minimum": 0},
        },
        description=(
            "Read-only local execution-quality diagnostics over caller-supplied/imported pre-trade intents, "
            "snapshots, and external execution receipts. Computes slippage only where local numeric evidence exists; "
            "no fetching, broker access, execution, cancellation, remediation, advice, alpha, or profit claims."
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
    "report.audit_readiness": _schema(
        {
            "stale_snapshot_threshold_days": {"type": "integer", "minimum": 0},
            "stale_source_threshold_days": {"type": "integer", "minimum": 0},
        },
        description="Read-only local prediction/event-market audit-readiness diagnostics; no network, no advice.",
    ),
    "report.phase_gate_readiness": _schema(
        {
            "thresholds": {
                "type": "object",
                "description": (
                    "OWNER-supplied numeric bar per criterion. Any unset "
                    "criterion reports pass=null and the gate is NEVER 'ready'. "
                    "The agent must not pick the bar that grants itself a "
                    "wallet (VISION 'autonomy is earned')."
                ),
                "properties": {
                    "resolved_n": {"type": "integer", "minimum": 0},
                    "brier": {"type": "number", "minimum": 0},
                    "skill_vs_market": {"type": "number"},
                    "reconciliation_cleanliness": {"type": "integer", "minimum": 0},
                    "audit_readiness": {"type": "boolean"},
                    "paper_fill_coverage": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "additionalProperties": False,
            },
            "min_sample": {"type": "integer", "minimum": 1},
        },
        description=(
            "Measurable VISION Phase-2 -> Phase-3 gate criteria computed from "
            "the journal against owner-supplied numeric thresholds. Read-only, "
            "deterministic, local-only; no network, no advice, no execution."
        ),
    ),
    "report.autonomy_readiness": _schema(
        {
            "thresholds": {
                "type": "object",
                "description": (
                    "OWNER-supplied numeric bar per gate criterion, passed "
                    "through to report.phase_gate_readiness. Any unset criterion "
                    "yields state='insufficient_data' and the gate is NEVER "
                    "'ready' (the agent must not self-grant a wallet)."
                ),
                "properties": {
                    "resolved_n": {"type": "integer", "minimum": 0},
                    "brier": {"type": "number", "minimum": 0},
                    "skill_vs_market": {"type": "number"},
                    "reconciliation_cleanliness": {"type": "integer", "minimum": 0},
                    "audit_readiness": {"type": "boolean"},
                    "paper_fill_coverage": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "additionalProperties": False,
            },
            "min_sample": {"type": "integer", "minimum": 1},
            "window_days": {
                "type": "integer",
                "minimum": 1,
                "description": "Longitudinal-window width for the calibration trend and expectancy series; defaults 30.",
            },
            "max_windows": {
                "type": "integer",
                "minimum": 1,
                "description": "Trailing-window cap for the trend/expectancy series; defaults 12.",
            },
        },
        description=(
            "Earned-autonomy readiness EVIDENCE BUNDLE. Composes the "
            "owner-thresholded report.phase_gate_readiness verdict with a "
            "longitudinal calibration trend, an expectancy series, and "
            "audit/hygiene diagnostics, keyed to the gate criteria with "
            "per-criterion pass/fail/insufficient_data and contributing "
            "record_ids. Evidence-only: it renders no verdict of its own and "
            "can never turn a not-ready gate ready. Read-only, deterministic, "
            "local-only; no network, no advice, no execution."
        ),
    ),
    "report.unscored_forecasts": _schema({"filter": _FILTER_PROP}),
    "report.mistakes": _schema({"filter": _FILTER_PROP}),
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
    "report.work_queue": _schema(
        {
            "filter": _FILTER_PROP,
            "as_of": {"type": "string", "format": "date-time"},
            "stale_threshold_days": {"type": "integer", "minimum": 0},
            "kinds": {"type": "array", "items": {"type": "string"}},
            "kind": {"type": "string"},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "Maximum obligations per page; defaults to the report page "
                    "default. When more obligations match, truncated=true and "
                    "next_cursor pages the next slice (mirrors the internal lifecycle substrate)."
                ),
            },
            "cursor": {
                "type": "string",
                "description": "Opaque pagination cursor from a previous report.work_queue response.",
            },
        },
        description=(
            "Read-only derived process-obligation queue; not a scheduler, assignment, broker, "
            "execution, fetch, or advice path. Paginated via limit + cursor + top-level "
            "truncated + next_cursor; summary.metrics carry full-set totals while groups/"
            "work_queue/next_actions carry the current page."
        ),
    ),
    "agent.next_actions": _schema(
        {
            "filter": _FILTER_PROP,
            "as_of": {"type": "string", "format": "date-time"},
            "stale_threshold_days": {"type": "integer", "minimum": 0},
            "kinds": {"type": "array", "items": {"type": "string"}},
            "kind": {"type": "string"},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "Maximum obligations per page; defaults to the report page "
                    "default. When more obligations match, truncated=true and "
                    "next_cursor pages the next slice (mirrors report.work_queue)."
                ),
            },
            "cursor": {
                "type": "string",
                "description": "Opaque pagination cursor from a previous agent.next_actions response.",
            },
        },
        description=(
            "Safe projection/alias over report.work_queue; process actions only, no planner or "
            "execution semantics. Paginated via limit + cursor + top-level truncated + next_cursor."
        ),
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
            "ENTRY_DECISION_WITHOUT_POSITION_EVENT, DUPLICATE_DECISIONS "
            "(exact-replay entry decisions), FRAGMENTED_SAME_SIDE_EXPOSURE "
            "(>1 open position on one instrument+side — fragmented exposure from "
            "paper_enter always opening an independent position), "
            "RECORD_ONLY_ACTUAL, MISSING_MARK, STALE_MARK, PROJECTION_MISSING, "
            "and PROJECTION_STALE. This reports local journal/projection data quality, "
            "not market risk or broker truth."
        ),
    ),
    "report.current_exposure": _schema(
        {
            "limit": {"type": "integer", "minimum": 1, "description": "Maximum open-position rows per page; defaults to the positions page default. When more positions match, truncated=true and next_cursor pages the rest (mirrors report.open_positions)."},
            "cursor": {"type": "string", "description": "Opaque pagination cursor from a previous report.current_exposure response; pages the next slice of open_positions."},
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
