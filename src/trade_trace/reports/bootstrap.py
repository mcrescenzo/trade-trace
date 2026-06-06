"""Internal deterministic bootstrap packet composition read model.

The bootstrap packet is read-only synthesis over already-local report/read-model
rows. It does not register a public tool surface, persist packets, run recall in a
telemetry-writing mode, fetch external data, schedule work, or execute trades.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from typing import Any, Final

from trade_trace.reports.forecast_diagnostics import report_forecast_diagnostics
from trade_trace.reports.lifecycle import report_lifecycle
from trade_trace.reports.memory_usefulness import report_memory_usefulness
from trade_trace.reports.recall_receipts import report_recall_receipts
from trade_trace.reports.strategy_health import report_strategy_health
from trade_trace.reports.work_queue import report_work_queue
from trade_trace.storage.database import read_snapshot
from trade_trace.timestamps import to_utc_iso8601
from trade_trace.tools._helpers import now_iso

BOOTSTRAP_CONTRACT_VERSION: Final = "bootstrap.v0"
DEFAULT_SECTIONS: Final[tuple[str, ...]] = (
    "current_scope",
    "obligations",
    "active_ideas",
    "strategy_context",
    "memory_context",
    "caveats",
    "suggested_process_calls",
)
TOTAL_BUDGET_PRUNE_ORDER: Final[tuple[str, ...]] = (
    "suggested_process_calls",
    "memory_context",
    "active_ideas",
    "strategy_context",
    "obligations",
    "current_scope",
)
OPTIONAL_SECTIONS: Final[set[str]] = set(DEFAULT_SECTIONS)
SUPPORTED_FILTER_KEYS: Final[set[str]] = {
    "run_id",
    "strategy_ids",
}
RECOGNIZED_BUT_UNSUPPORTED_FILTER_KEYS: Final[set[str]] = {
    "actor_id",
    "agent_id",
    "model_id",
    "environment",
    "symbols",
    "tags",
    "since",
    "until",
}
HARD_CONSTRAINTS: Final[dict[str, bool]] = {
    "no_financial_advice": True,
    "no_market_data_fetch": True,
    "no_broker_or_exchange_fetch": True,
    "no_trade_execution": True,
    "no_order_preparation": True,
    "no_scheduler_or_alert_creation": True,
    "caller_supplied_data_only": True,
    "local_read_synthesis_only": True,
}
BOUNDARY_CAVEATS: Final[list[str]] = [
    "no_market_data_fetch",
    "no_broker_verification",
    "no_trade_execution",
    "no_financial_advice",
    "caller_supplied_data_only",
    "local_read_only_synthesis",
    "no_scheduler_or_alert_creation",
]

# Relative path (from the repo root / docs site root) to the human/agent
# readable caveat-code glossary. Surfaced inline so a bot reading the
# packet can resolve any code it does not recognise without out-of-band
# knowledge (trade-trace-o1wr).
CAVEAT_GLOSSARY_DOC: Final = "docs/architecture/bootstrap-caveat-glossary.md"

# One-line gloss per caveat code that report.bootstrap can emit anywhere
# in the packet. Keep this in sync with the glossary doc; the doc test
# `tests/docs/test_bootstrap_caveat_glossary.py` asserts every code here
# is documented and vice versa, and the read-model test asserts every
# code that actually appears in a composed packet has a gloss here.
#
# Codes are grouped by origin for readability only; lookup is flat.
CAVEAT_GLOSSARY: Final[dict[str, str]] = {
    # Hard boundary caveats (always present): non-negotiable safety limits.
    "no_market_data_fetch": "This packet did not fetch live market/price data; treat any market context as caller-supplied and possibly stale.",
    "no_broker_verification": "No broker/exchange was queried; positions and fills reflect the local journal only, not verified account state.",
    "no_trade_execution": "Nothing here was executed; suggestions are inspection prompts, never orders.",
    "no_financial_advice": "Summaries are not buy/sell recommendations or profit claims.",
    "caller_supplied_data_only": "All evidence comes from data the caller previously recorded locally; no external truth was added.",
    "local_read_only_synthesis": "The packet is a read-only synthesis over local rows; it wrote nothing and ran no recall telemetry.",
    "no_scheduler_or_alert_creation": "No jobs, reminders, or alerts were created; obligations are derived signals, not scheduled tasks.",
    # Scope caveats: the caller left a dimension unscoped so the read broadened.
    "missing_agent_id": "No agent_id was supplied, so the read spans all agents; results may mix unrelated agents.",
    "missing_run_id": "No run_id was supplied, so the read spans all runs; results may mix unrelated sessions.",
    "missing_strategy_ids": "No strategy_id was supplied, so the read spans all strategies; results may mix unrelated strategies.",
    # Evidence caveats.
    "no_fetch_performed": "No external fetch backed this item; it rests entirely on previously recorded local evidence.",
    "not_trade_advice": "This item is a process artifact, not trading advice or a signal.",
    "not_executed": "This suggested call was not run; the caller must choose whether to invoke it.",
    "requires_caller_supplied_data": "Acting on this suggestion requires the caller to provide external evidence first.",
    "requires_caller_supplied_evidence": "Acting on this suggestion requires the caller to provide external evidence first.",
    "count_unavailable": "An exact available/omitted count could not be computed for this section; absence is not proof of emptiness.",
    # Data-quality caveats from sub-reports (work_queue, strategy_health,
    # forecast_diagnostics, lifecycle, recall, memory_usefulness).
    "derived_read_only": "Work-queue obligations are derived read-only signals, not a task manager.",
    "local_rows_only": "Only local journal rows were considered; nothing external was consulted.",
    "no_scheduler_daemon_or_reminder": "The work queue is not a scheduler/daemon and created no reminders.",
    "no_assignment_or_broker_action": "No owner assignment or broker action was taken on these obligations.",
    "no_external_fetch_or_market_lookup": "No external fetch or market lookup backed these obligations.",
    "no_trading_advice_or_signal": "Obligations are process prompts, not trading advice or signals.",
    "low_n_decisions": "Too few decisions to make strategy metrics reliable; treat as directional only.",
    "low_n": "Sample size is below the diagnostic minimum; metrics are caveated and may be noise.",
    "caller_supplied_market_reference_only": "Market references come only from caller-supplied snapshots stored locally; no market data was fetched or derived.",
    "no_external_fetch": "No external fetch backed these diagnostics; they rest on local rows only.",
    "not_advice_or_profitability_evidence": "These diagnostics are not trading advice and are not evidence of profitability.",
    "thesis_source_coverage_only_missing_refs": "Source-coverage check only flags theses missing source refs; it does not assess source content.",
    "source_quality_checks_limited_to_thesis_source_refs": "Source-quality checks look only at thesis source refs, not full provenance.",
    "policy_candidates_unsupported_local_surface": "Policy-candidate promotion is not a supported local surface; candidates are read-only.",
    "late_recorded_excluded": "Late-recorded outcomes were excluded from scoring to avoid look-ahead bias.",
    "baseline_unavailable": "No baseline was available, so calibration is reported without a comparison anchor.",
    "missing_source_reference": "Some items lack a source reference, weakening their provenance.",
    "missing_source_ref": "This case has no linked source record; its provenance is incomplete.",
    "missing_market_reference": "A forecast-decision link lacks a market reference, so market context is incomplete.",
    "missing_spread": "Spread context is missing for some references; liquidity quality is unknown.",
    "wide_spread": "A referenced market had a wide spread; fills/marks may be unreliable.",
    "missing_liquidity_context": "Liquidity context is missing for some references.",
    # Memory / recall caveats.
    "memory_body_omitted": "Memory node bodies were omitted to save budget; only summaries/IDs are shown.",
    "STALE_OR_INVALIDATED_MEMORY": "A recalled memory node is stale or has been invalidated; do not rely on it as current.",
    "STALE_AS_OF_RECEIPT": "The recall receipt itself is stale relative to as_of; the recall may not reflect current memory.",
    "CONTRADICTED_DOWNSTREAM": "A later record contradicts this memory; weigh it against the contradiction.",
    "SUPERSEDED_DOWNSTREAM": "This memory has been superseded by a newer node; prefer the successor.",
    "HARMFUL_DOWNSTREAM": "Downstream evidence suggests acting on this memory was harmful.",
    "NO_DOWNSTREAM_USE_EVIDENCE": "There is no evidence this recalled memory was used downstream.",
    "CONSUMER_INFERENCE_UNSCOPED": "Consumer attribution could not be scoped precisely; usefulness is uncertain.",
    "RETURNED_NODE_MISSING": "A recall returned a node ID that no longer resolves to a stored node.",
    "REJECTED_RECEIPT": "This recall receipt was rejected and should not be treated as valid attribution.",
    "DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM": "Memory-usefulness metrics are diagnostic associations only; they make no causal claim.",
    "OUTCOME_IMPACT_NOT_INFERRED": "The impact of memory on outcomes was not inferred; correlation is not impact.",
    "NO_EXPECTED_MEMORY_SIGNAL": "No expected-memory signal could be measured for this control; it is not measurable here, not a finding.",
    "BAD_OUTCOME_NOT_CANONICALLY_INFERRED": "High-confidence-bad-outcome control is edge-based only; the bad outcome was not canonically inferred.",
    "HARMFUL_OVERFIT_EDGE_BASED_ONLY": "Harmful-overfit control is edge-based only; treat as a heuristic flag, not a proven failure.",
    # Section/structural caveats.
    "section_not_requested": "This section was not requested by the caller, so it is empty by choice, not by absence of data.",
    "playbook_detail_not_composed": "Playbook detail is not composed into this packet; drill in via dedicated tools.",
    "section_unavailable": "This section could not be composed (e.g. invalid sub-report inputs); not an assertion of emptiness.",
    # Truncation caveats.
    "max_items": "The section hit its max-items budget; some rows were omitted (see omitted_counts).",
    "max_chars": "The section hit its max-chars budget and was emptied; raise the budget to see it.",
    "max_total_chars": "The whole packet hit its total-chars budget; some sections were pruned (see omitted_counts).",
}


def compose_bootstrap_packet(
    conn: sqlite3.Connection,
    *,
    as_of: str | None = None,
    raw_filter: Any = None,
    sections: list[str] | None = None,
    budgets: dict[str, Any] | None = None,
    kind: str = "agent.bootstrap",
) -> dict[str, Any]:
    """Return a deterministic bootstrap packet over local state only."""

    resolved_as_of = to_utc_iso8601(as_of or now_iso(), field="as_of")
    requested_filter = _normalize_filter(raw_filter)
    requested_sections = list(DEFAULT_SECTIONS if sections is None else sections)
    unknown_sections = sorted(set(requested_sections) - OPTIONAL_SECTIONS)
    if unknown_sections:
        raise ValueError(f"unsupported bootstrap section(s): {unknown_sections!r}")
    effective_budgets = _effective_budgets(budgets or {})
    report_filter = _report_filter(requested_filter, resolved_as_of)

    # Pin one read snapshot for every sub-report so the bootstrap packet is
    # internally consistent under concurrent writes (trade-trace-d8lu). The
    # nested report functions are no-ops on the snapshot helper because the
    # connection is already in a transaction here.
    with read_snapshot(conn):
        source_tools: list[str] = []
        # limit=None: the composer derives obligations off the WHOLE queue, so
        # it must not be paginated here (trade-trace-1y9s); the transport-facing
        # report.work_queue / agent.next_actions surfaces default to a bounded
        # page size instead.
        work = report_work_queue(conn, raw_filter=report_filter, as_of=resolved_as_of, limit=None)
        source_tools.append("report.work_queue")
        lifecycle = report_lifecycle(conn, raw_filter=report_filter, as_of=resolved_as_of)
        source_tools.append("report.lifecycle")
        try:
            strategy = report_strategy_health(conn, raw_filter=report_filter, status="all", as_of=resolved_as_of)
            source_tools.append("report.strategy_health")
        except ValueError as exc:
            strategy = {"summary": {"sample_warning": "section_unavailable", "caveats": [str(exc)]}, "groups": []}
        recall = report_recall_receipts(conn, **_receipt_kwargs(requested_filter, resolved_as_of, effective_budgets["sections"]["memory_context"]["max_items"]))
        source_tools.append("report.recall_receipts")
        memory = report_memory_usefulness(conn, **_receipt_kwargs(requested_filter, resolved_as_of, effective_budgets["sections"]["memory_context"]["max_items"]))
        source_tools.append("report.memory_usefulness")
        forecast = report_forecast_diagnostics(conn, raw_filter=report_filter)
        source_tools.append("report.forecast_diagnostics")

    broadening = _broadening(requested_filter)
    current_scope = _current_scope(requested_filter, resolved_as_of, broadening)
    obligations = [_obligation(item, i) for i, item in enumerate(work.get("work_queue", []), start=1)]
    active_ideas = _active_ideas(lifecycle)
    strategy_context = _strategy_context(strategy)
    memory_context = _memory_context(recall, memory, include_body=effective_budgets["include_memory_body"])
    cold_start = _is_cold_start(obligations, lifecycle, strategy_context, memory_context)
    suggested = _suggested_calls(obligations, cold_start=cold_start)
    caveats = _caveats(broadening, work, strategy, recall, memory, forecast)

    sections_data: dict[str, Any] = {
        "current_scope": current_scope,
        "obligations": obligations,
        "active_ideas": active_ideas,
        "strategy_context": strategy_context,
        "memory_context": memory_context,
        "caveats": caveats,
        "suggested_process_calls": suggested,
    }
    omitted_counts = {name: _empty_omitted() for name in DEFAULT_SECTIONS}
    trunc_sections: dict[str, Any] = {}
    for name in DEFAULT_SECTIONS:
        if name not in requested_sections:
            sections_data[name] = _empty_section(name)
            omitted_counts[name]["section_not_requested"] = 1
            trunc_sections[name] = _trunc(name, 0, 0, reason="section_not_requested")
            continue
        value, trunc, omitted = _apply_budget(name, sections_data[name], effective_budgets["sections"][name])
        sections_data[name] = value
        trunc_sections[name] = trunc
        omitted_counts[name].update(omitted)

    truncation = {
        "is_partial": any(s["is_partial"] for s in trunc_sections.values()),
        "policy": "stable_priority_then_time_then_id",
        "total_chars_returned": 0,
        "sections": trunc_sections,
    }
    packet: dict[str, Any] = {
        "kind": kind,
        "contract_version": BOOTSTRAP_CONTRACT_VERSION,
        "metadata": {
            "packet_id": _pending_packet_id(),
            "generated_at": resolved_as_of,
            "as_of": resolved_as_of,
            "contract_version": BOOTSTRAP_CONTRACT_VERSION,
            "source_tools": source_tools,
            "side_effects": [],
            "determinism": {
                "stable_ordering": True,
                "ranking_keys": ["process_urgency", "due_at", "source_kind", "source_id"],
                "nondeterministic_components": [],
            },
        },
        "filter": {"requested": requested_filter, "applied": report_filter, "unsupported_rejected": [], "broadening": broadening},
        "budgets": effective_budgets,
        "truncation": truncation,
        "omitted_counts": omitted_counts,
        "current_scope": sections_data["current_scope"],
        "obligations": sections_data["obligations"],
        "active_ideas": sections_data["active_ideas"],
        "strategy_context": sections_data["strategy_context"],
        "memory_context": sections_data["memory_context"],
        "caveats": sections_data["caveats"],
        "suggested_process_calls": sections_data["suggested_process_calls"],
        "hard_constraints": deepcopy(HARD_CONSTRAINTS),
    }
    # The total-budget enforcer attaches/refreshes the inline caveat gloss
    # on every measurement, so the glossary's bytes are counted against
    # max_chars_total and it always reflects exactly the codes that survive
    # pruning (trade-trace-o1wr).
    _enforce_total_budget(packet, effective_budgets["max_chars_total"])
    packet["metadata"]["packet_id"] = _packet_id(packet)
    packet["truncation"]["total_chars_returned"] = _serialized_len(packet)
    if packet["truncation"]["total_chars_returned"] > effective_budgets["max_chars_total"]:
        raise ValueError("bootstrap packet cannot fit within max_chars_total without omitting required metadata")
    return packet


def _normalize_filter(raw: Any) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("bootstrap filter must be an object")
    unsupported = sorted(
        k for k, v in raw.items() if k in RECOGNIZED_BUT_UNSUPPORTED_FILTER_KEYS and v not in (None, [], {})
    )
    if unsupported:
        raise ValueError(
            "unsupported bootstrap filter(s) for composed read model: "
            f"{unsupported!r}; supported filters are {sorted(SUPPORTED_FILTER_KEYS)!r}"
        )
    unknown = sorted(
        k
        for k, v in raw.items()
        if k not in SUPPORTED_FILTER_KEYS and k not in RECOGNIZED_BUT_UNSUPPORTED_FILTER_KEYS and v not in (None, [], {})
    )
    if unknown:
        raise ValueError(f"unsupported bootstrap filter(s): {unknown!r}")
    strategy_ids = raw.get("strategy_ids")
    if strategy_ids not in (None, []):
        if not isinstance(strategy_ids, list):
            raise ValueError("bootstrap filter strategy_ids must be a list")
        if len(strategy_ids) != 1:
            raise ValueError("bootstrap filter strategy_ids supports exactly one strategy_id when provided")
    out = {k: raw.get(k) for k in sorted(SUPPORTED_FILTER_KEYS)}
    return {k: v for k, v in out.items() if v not in (None, [], {})}


def _report_filter(f: dict[str, Any], as_of: str) -> dict[str, Any]:
    actors = {k: [f[k]] for k in ("actor_id", "agent_id", "model_id", "environment", "run_id") if k in f}
    return {
        "actors": actors,
        "strategy": {"strategy_id": (f.get("strategy_ids") or [None])[0] if isinstance(f.get("strategy_ids"), list) else None},
        "instrument": {"symbol": f.get("symbols", [])},
        "time_window": {"created_at_gte": f.get("since"), "created_at_lt": f.get("until")},
    }


def _receipt_kwargs(f: dict[str, Any], as_of: str, limit: int) -> dict[str, Any]:
    return {
        "run_id": f.get("run_id"),
        "agent_id": f.get("agent_id"),
        "model_id": f.get("model_id"),
        "environment": f.get("environment"),
        "strategy_id": (f.get("strategy_ids") or [None])[0] if isinstance(f.get("strategy_ids"), list) else None,
        "as_of": as_of,
        "limit": max(1, limit),
    }


def _effective_budgets(raw: dict[str, Any]) -> dict[str, Any]:
    default_items = _non_negative_int(raw.get("default_max_items_per_section", 10), field="default_max_items_per_section")
    default_chars = _positive_int(raw.get("default_max_chars_per_section", 4000), field="default_max_chars_per_section")
    raw_sections_value = raw.get("sections", {})
    if not isinstance(raw_sections_value, dict):
        raise ValueError("bootstrap budget sections must be an object")
    sections_raw = raw_sections_value
    unknown_sections = sorted(set(sections_raw) - set(DEFAULT_SECTIONS))
    if unknown_sections:
        raise ValueError(f"unsupported bootstrap budget section(s): {unknown_sections!r}")
    sections = {name: {"max_items": default_items, "max_chars": default_chars} for name in DEFAULT_SECTIONS}
    for name, vals in sections_raw.items():
        if not isinstance(vals, dict):
            raise ValueError(f"bootstrap budget for section {name!r} must be an object")
        sections[name] = {
            "max_items": _non_negative_int(vals.get("max_items", default_items), field=f"sections.{name}.max_items"),
            "max_chars": _positive_int(vals.get("max_chars", default_chars), field=f"sections.{name}.max_chars"),
        }
    return {
        "max_chars_total": _positive_int(raw.get("max_chars_total", 24000), field="max_chars_total"),
        "default_max_items_per_section": default_items,
        "default_max_chars_per_section": default_chars,
        "sections": sections,
        "include_memory_body": bool(raw.get("include_memory_body", False)),
        "include_sensitive_sources": bool(raw.get("include_sensitive_sources", False)),
    }


def _non_negative_int(value: Any, *, field: str) -> int:
    out = int(value)
    if out < 0:
        raise ValueError(f"bootstrap budget {field} must be non-negative")
    return out


def _positive_int(value: Any, *, field: str) -> int:
    out = int(value)
    if out <= 0:
        raise ValueError(f"bootstrap budget {field} must be positive")
    return out


def _current_scope(f: dict[str, Any], as_of: str, broadening: list[str]) -> dict[str, Any]:
    return {
        "identity": {k: f.get(k) for k in ("actor_id", "agent_id", "model_id", "environment", "run_id")},
        "time_window": {"as_of": as_of, "since": f.get("since"), "until": f.get("until")},
        "selectors": {"strategy_ids": f.get("strategy_ids", []), "symbols": f.get("symbols", []), "tags": f.get("tags", [])},
        "missing_scope_fields": [k for k in ("actor_id", "agent_id", "model_id", "environment", "run_id") if k not in f],
        "scope_caveat_codes": broadening,
    }


def _broadening(f: dict[str, Any]) -> list[str]:
    return [f"missing_{k}" for k in ("agent_id", "run_id", "strategy_ids") if k not in f]


def _obligation(item: dict[str, Any], n: int) -> dict[str, Any]:
    return {
        "obligation_id": item["item_id"],
        "kind": item["kind"],
        "urgency": item.get("priority"),
        "due_at": item.get("due_at"),
        "summary": item.get("reason"),
        "source_refs": item.get("source_refs", []),
        "evidence_refs": [{"kind": "report", "id": "report.work_queue"}],
        "caveat_codes": sorted(set(item.get("caveat", []) + ["no_fetch_performed", "not_trade_advice"])),
        "suggested_process_call_ids": [f"call_{n:03d}"],
    }


def _active_ideas(lifecycle: dict[str, Any]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {"current_exposure": [], "watches": [], "unresolved_forecasts": [], "non_actions_and_reviews": [], "recently_resolved_needing_learning": []}
    for case in lifecycle.get("lifecycle_cases", []):
        item = {"id": case["case_id"], "summary": ",".join(case.get("reason_codes", [])), "timestamps": case.get("timestamps", {}), "source_refs": case.get("source_refs", []), "caveat_codes": case.get("caveat_codes", []), "drilldown_tool": "report.lifecycle"}
        if any(r.get("kind") == "forecast" for r in case.get("source_refs", [])) and case.get("state") in {"open", "pending_review"}:
            buckets["unresolved_forecasts"].append(item)
        elif case.get("state") in {"pending_review", "stale", "adherence_due"}:
            buckets["non_actions_and_reviews"].append(item)
        elif case.get("state") == "reflection_due":
            buckets["recently_resolved_needing_learning"].append(item)
    return buckets


def _strategy_context(report: dict[str, Any]) -> dict[str, Any]:
    active: list[dict[str, Any]] = []
    archived: list[dict[str, Any]] = []
    caveats = list(report.get("summary", {}).get("caveats", []))
    for g in report.get("groups", []):
        metrics = g.get("metrics", {})
        row = {"strategy_id": metrics.get("strategy_id"), "slug": metrics.get("slug"), "status": metrics.get("status"), "source_refs": [{"kind": "strategy", "id": metrics.get("strategy_id")}], "health_report_refs": [{"kind": "report", "id": "report.strategy_health"}], "caveat_codes": g.get("caveats", [])}
        (active if metrics.get("status") == "active" else archived).append(row)
    return {"active_strategies": active, "relevant_archived_strategies": archived, "playbook_state": {"status": "section_unavailable", "caveat_codes": ["playbook_detail_not_composed"]}, "strategy_caveats": sorted(set(caveats))}


def _memory_context(recall: dict[str, Any], memory: dict[str, Any], *, include_body: bool) -> dict[str, Any]:
    nodes = []
    for receipt in recall.get("recall_receipts", []):
        for item in receipt.get("items", []):
            node = {"node_id": item.get("id"), "node_type": item.get("node_type"), "summary": item.get("title"), "valid_from": item.get("valid_from"), "valid_to": item.get("valid_to"), "confidence": item.get("confidence_base"), "importance": item.get("importance"), "source_refs": item.get("source_refs", []), "caveat_codes": item.get("caveat_codes", [])}
            if include_body:
                node["body"] = item.get("body")
            nodes.append(node)
    return {"included": True, "recall_queries": [{"source": "report.recall_receipts", "telemetry_persisted": False}], "memory_nodes": nodes, "recall_receipts": recall.get("recall_receipts", []), "memory_diagnostics": memory.get("memory_diagnostics", []), "omitted_memory": {}, "memory_caveats": sorted(set(recall.get("summary", {}).get("caveat_codes", []) + memory.get("summary", {}).get("caveat_codes", []) + (["memory_body_omitted"] if not include_body else [])))}


def _is_cold_start(
    obligations: list[dict[str, Any]],
    lifecycle: dict[str, Any],
    strategy_context: dict[str, Any],
    memory_context: dict[str, Any],
) -> bool:
    """A journal is a *cold start* when it holds nothing to orient on: no
    derived process obligations, no lifecycle cases (forecasts, positions,
    watches, reviews), no strategies, and no recalled memory nodes. On such a
    truly empty journal the continuity/read suggested_process_calls all return
    empty, so there is no discoverable forward action; bootstrap surfaces a
    first-run breadcrumb pointing at the entry sequence instead (trade-trace-xqjv).

    Emptiness is read off the already-composed sub-reports — never a fresh fetch
    or DB probe — so it stays inside the read-only/no-fetch contract. The
    lifecycle total is taken from ``summary.metrics.case_count`` (the WHOLE
    filtered set), not the page, so a paginated-but-non-empty journal is never
    misread as cold."""

    if obligations:
        return False
    lifecycle_total = lifecycle.get("summary", {}).get("metrics", {}).get("case_count", 0)
    if lifecycle_total:
        return False
    if strategy_context.get("active_strategies") or strategy_context.get("relevant_archived_strategies"):
        return False
    if memory_context.get("memory_nodes"):
        return False
    return True


def _suggested_calls(obligations: list[dict[str, Any]], *, cold_start: bool = False) -> list[dict[str, Any]]:
    base = [
        ("report.work_queue", "Inspect derived local process obligations."),
        ("agent.next_actions", "Inspect the safe alias projection of local process obligations."),
        ("report.recall_receipts", "Inspect local memory recall attribution receipts."),
        ("strategy.show", "Drill into a caller-selected local strategy."),
    ]
    calls = [{"call_id": f"call_{i:03d}", "tool": tool, "reason": reason, "preconditions": ["local_read_only"], "args_template": {}, "source_refs": [{"kind": "report", "id": tool}], "caveat_codes": ["not_trade_advice", "not_executed", "no_fetch_performed"]} for i, (tool, reason) in enumerate(base, 1)]
    for i, obl in enumerate(obligations[:3], len(calls) + 1):
        calls.append({"call_id": f"call_{i:03d}", "tool": "decision.add", "reason": "Record a caller-supplied review/non-action decision if the caller has evidence.", "preconditions": ["caller_supplied_evidence"], "args_template": {"type": "review"}, "source_refs": obl["source_refs"], "caveat_codes": ["requires_caller_supplied_data", "not_trade_advice", "not_executed"]})
    if cold_start:
        # First-run onboarding breadcrumb: on a truly empty journal every
        # read/continuity call above returns empty, so a cold agent has no
        # discoverable forward action. Point it at the entry sequence
        # (market.search -> market.bind -> snapshot.fetch -> forecast.add) so
        # the loop can BEGIN (trade-trace-xqjv). This is a process-call HINT,
        # not advice or a fetch: the tools are listed (not invoked), no market
        # is named or ranked, and the caveat codes mark it as such — preserving
        # the no-market-data-fetch / no-financial-advice contract. Distinct
        # from trade-trace-663l, which added the market.search surface itself.
        calls.extend(_first_run_onboarding_calls(len(calls) + 1))
    return calls


# Ordered entry sequence a brand-new agent follows to begin the forecasting
# loop. market.search/bind/snapshot.fetch are listed as the discovery + binding
# steps; forecast.add is the first journal write. None are invoked here.
_FIRST_RUN_ENTRY_SEQUENCE: Final[tuple[tuple[str, str, list[str], dict[str, Any]], ...]] = (
    ("market.search", "First-run entry point: discover bindable live binary markets (read-only adapter scan). No market is named, ranked, or recommended here.", ["local_read_only", "adapter_enabled"], {}),
    ("market.bind", "Bind a caller-chosen discovered market into the local journal so it can be referenced.", ["caller_selected_market"], {"external_id": "<from market.search>"}),
    ("snapshot.fetch", "Record a caller-triggered local price/liquidity snapshot for the bound market.", ["bound_market", "adapter_enabled"], {"market_id": "<from market.bind>"}),
    ("forecast.add", "Record the agent's own first forecast (probability + resolution rule) for the bound market's thesis; inspect tool.schema for the required fields.", ["caller_supplied_thesis_and_probability"], {}),
)


def _first_run_onboarding_calls(start_index: int) -> list[dict[str, Any]]:
    return [
        {
            "call_id": f"call_{start_index + offset:03d}",
            "tool": tool,
            "reason": reason,
            "preconditions": preconditions,
            "args_template": args_template,
            "source_refs": [{"kind": "doc", "id": "docs/AGENT_GUIDE.md"}],
            "caveat_codes": ["not_trade_advice", "not_executed", "no_fetch_performed"],
        }
        for offset, (tool, reason, preconditions, args_template) in enumerate(_FIRST_RUN_ENTRY_SEQUENCE)
    ]


def _caveats(broadening: list[str], *reports: dict[str, Any]) -> dict[str, Any]:
    return {
        "hard_boundary_caveats": list(BOUNDARY_CAVEATS),
        "scope_caveats": broadening,
        "evidence_caveats": ["no_fetch_performed"],
        "data_quality_caveats": sorted({c for r in reports for c in r.get("summary", {}).get("caveats", []) + r.get("summary", {}).get("caveat_codes", [])}),
        "memory_caveats": [],
        "truncation_caveats": [],
        # Inline gloss (code -> one-line meaning) for every caveat code
        # that appears anywhere in this packet, plus a pointer to the full
        # glossary doc. Populated in a final pass once the packet is fully
        # composed and budgeted (trade-trace-o1wr).
        "caveat_glossary_doc": CAVEAT_GLOSSARY_DOC,
        "caveat_glossary": {},
    }


def _is_caveat_code(value: Any) -> bool:
    """A caveat *code* is a machine-readable identifier token: a non-empty
    string with no whitespace. Some sub-reports also carry full prose
    sentences under `caveats`/`caveat` keys (human notes, not codes); those
    contain spaces and are excluded so the inline glossary stays a code map
    rather than a sentence map (trade-trace-o1wr)."""

    return isinstance(value, str) and bool(value) and not any(ch.isspace() for ch in value)


def _collect_caveat_codes(value: Any, found: set[str]) -> None:
    """Walk an arbitrary packet substructure and collect every caveat
    *code* (identifier-shaped string) from `caveat`/`caveat_codes`/
    `scope_caveat_codes` fields and from the various ``*caveats`` arrays,
    so the inline glossary can resolve them. Prose caveat sentences are
    skipped by `_is_caveat_code`."""

    if isinstance(value, dict):
        for key, sub in value.items():
            if key == "caveat_glossary":
                # Don't recurse into the glossary itself (its keys are the
                # codes, already accounted for via the rest of the packet).
                continue
            if key in {"caveat_codes", "scope_caveat_codes", "caveat"}:
                if isinstance(sub, list):
                    found.update(c for c in sub if _is_caveat_code(c))
                elif _is_caveat_code(sub):
                    found.add(sub)
            elif key.endswith("caveats") and isinstance(sub, list):
                found.update(c for c in sub if _is_caveat_code(c))
            else:
                _collect_caveat_codes(sub, found)
    elif isinstance(value, list):
        for item in value:
            _collect_caveat_codes(item, found)


def _attach_caveat_glossary(packet: dict[str, Any]) -> None:
    """Populate ``caveats.caveat_glossary`` with a one-line gloss for every
    caveat code present in the composed packet. Unknown codes get a stable
    placeholder so a bot can still tell the code was deliberate."""

    found: set[str] = set()
    _collect_caveat_codes(packet, found)
    glossary = {
        code: CAVEAT_GLOSSARY.get(code, "No gloss registered for this code; see the caveat-glossary doc.")
        for code in sorted(found)
    }
    packet["caveats"]["caveat_glossary"] = glossary


def _apply_budget(name: str, value: Any, budget: dict[str, int]) -> tuple[Any, dict[str, Any], dict[str, int]]:
    available = len(value) if isinstance(value, list) else sum(len(v) for v in value.values() if isinstance(v, list)) if isinstance(value, dict) else 1
    out = deepcopy(value)
    omitted = _empty_omitted()
    if isinstance(out, list) and len(out) > budget["max_items"]:
        omitted["max_items"] = len(out) - budget["max_items"]
        out = out[: budget["max_items"]]
    elif isinstance(out, dict):
        for k, v in list(out.items()):
            if isinstance(v, list) and len(v) > budget["max_items"]:
                omitted["max_items"] += len(v) - budget["max_items"]
                out[k] = v[: budget["max_items"]]
    reason = "max_items" if omitted["max_items"] else None
    if len(json.dumps(out, sort_keys=True)) > budget["max_chars"]:
        omitted["max_chars"] += 1
        # The char guard discards the whole section, so it — not any prior
        # per-item trimming — is the controlling reason the section is empty.
        # Reporting a stale "max_items" here would be self-contradictory
        # (returned_count:0 under a >0 max_items budget) and would mislead a
        # consumer into "some rows omitted" when in fact ALL rows were dropped
        # by the char cap (axloop AX-038).
        reason = "max_chars"
        out = _empty_section(name)
    returned = len(out) if isinstance(out, list) else sum(len(v) for v in out.values() if isinstance(v, list)) if isinstance(out, dict) else 1
    return out, _trunc(name, returned, available, reason=reason), omitted


def _trunc(_name: str, returned: int, available: int, *, reason: str | None) -> dict[str, Any]:
    return {"is_partial": reason is not None and reason != "section_not_requested", "returned_count": returned, "available_count": available, "omitted_count": max(available - returned, 0), "reason": reason, "next_cursor": None}


def _empty_omitted() -> dict[str, int]:
    return {"max_items": 0, "max_chars": 0, "max_total_chars": 0, "section_not_requested": 0, "redacted_or_sensitive": 0}


def _empty_section(name: str) -> Any:
    if name in {"obligations", "suggested_process_calls"}:
        return []
    if name == "memory_context":
        return {"included": False, "recall_queries": [], "memory_nodes": [], "recall_receipts": [], "omitted_memory": {"section_not_requested": 1}, "memory_caveats": ["section_not_requested"]}
    return {}


def _empty_section_for_total_budget(name: str) -> Any:
    if name in {"obligations", "suggested_process_calls"}:
        return []
    if name == "memory_context":
        return {"included": False, "recall_queries": [], "memory_nodes": [], "recall_receipts": [], "memory_diagnostics": [], "omitted_memory": {"max_total_chars": 1}, "memory_caveats": ["max_total_chars"]}
    return {}


def _serialized_len(packet: dict[str, Any]) -> int:
    return len(json.dumps(packet, sort_keys=True, separators=(",", ":")))


def _pending_packet_id() -> str:
    return "bootstrap:" + ("0" * 24)


def _section_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        nested_lists = sum(len(v) for v in value.values() if isinstance(v, list))
        return nested_lists if nested_lists else (1 if value else 0)
    return 1 if value else 0


def _measure(packet: dict[str, Any], *, suppress_glossary: bool = False) -> int:
    """Recompute the inline caveat glossary (so it reflects exactly the
    codes currently in the packet) and return the packet's serialized
    length. Pruning a section drops its codes from the glossary, so the
    byte count stays accurate as the enforcer prunes. When the packet is
    still over budget after pruning every section, the glossary itself is
    suppressed (the `caveat_glossary_doc` pointer still resolves codes),
    so the gloss never blocks the hard total-chars bound (trade-trace-o1wr)."""

    if suppress_glossary:
        packet["caveats"]["caveat_glossary"] = {}
    else:
        _attach_caveat_glossary(packet)
    return _serialized_len(packet)


def _enforce_total_budget(packet: dict[str, Any], max_chars_total: int) -> None:
    packet["truncation"]["total_chars_returned"] = _measure(packet)
    if packet["truncation"]["total_chars_returned"] <= max_chars_total:
        return

    packet["truncation"]["is_partial"] = True
    packet["omitted_counts"].setdefault("packet", _empty_omitted())["max_total_chars"] = 1
    packet["caveats"].setdefault("truncation_caveats", []).append("max_total_chars")

    for name in TOTAL_BUDGET_PRUNE_ORDER:
        if packet["truncation"]["total_chars_returned"] <= max_chars_total:
            return
        before = _section_count(packet.get(name))
        if before == 0:
            continue
        packet[name] = _empty_section_for_total_budget(name)
        packet["omitted_counts"].setdefault(name, _empty_omitted())["max_total_chars"] += max(before, 1)
        packet["truncation"]["sections"][name] = _trunc(name, 0, before, reason="max_total_chars")
        packet["truncation"]["total_chars_returned"] = _measure(packet)

    # Last resort before failing: drop the inline gloss. The codes remain
    # resolvable via `caveats.caveat_glossary_doc`.
    if packet["truncation"]["total_chars_returned"] > max_chars_total:
        packet["caveats"]["caveat_glossary"] = {}
        packet["caveats"].setdefault("caveat_glossary_omitted", "max_total_chars")
        packet["truncation"]["total_chars_returned"] = _measure(packet, suppress_glossary=True)

    if packet["truncation"]["total_chars_returned"] > max_chars_total:
        raise ValueError("bootstrap packet cannot fit within max_chars_total without omitting required metadata")


def _packet_id(packet: dict[str, Any]) -> str:
    clone = deepcopy(packet)
    clone["metadata"]["packet_id"] = "pending"
    raw = json.dumps(clone, sort_keys=True, separators=(",", ":"))
    return "bootstrap:" + hashlib.sha256(raw.encode()).hexdigest()[:24]


__all__ = [
    "BOOTSTRAP_CONTRACT_VERSION",
    "CAVEAT_GLOSSARY",
    "CAVEAT_GLOSSARY_DOC",
    "compose_bootstrap_packet",
]
