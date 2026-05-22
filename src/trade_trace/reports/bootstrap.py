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

    source_tools: list[str] = []
    work = report_work_queue(conn, raw_filter=report_filter, as_of=resolved_as_of)
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
    suggested = _suggested_calls(obligations)
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
                node["body"] = item.get("title")
            nodes.append(node)
    return {"included": True, "recall_queries": [{"source": "report.recall_receipts", "telemetry_persisted": False}], "memory_nodes": nodes, "recall_receipts": recall.get("recall_receipts", []), "memory_diagnostics": memory.get("memory_diagnostics", []), "omitted_memory": {}, "memory_caveats": sorted(set(recall.get("summary", {}).get("caveat_codes", []) + memory.get("summary", {}).get("caveat_codes", []) + (["memory_body_omitted"] if not include_body else [])))}


def _suggested_calls(obligations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = [
        ("report.work_queue", "Inspect derived local process obligations."),
        ("agent.next_actions", "Inspect the safe alias projection of local process obligations."),
        ("report.recall_receipts", "Inspect local memory recall attribution receipts."),
        ("strategy.show", "Drill into a caller-selected local strategy."),
    ]
    calls = [{"call_id": f"call_{i:03d}", "tool": tool, "reason": reason, "preconditions": ["local_read_only"], "args_template": {}, "source_refs": [{"kind": "report", "id": tool}], "caveat_codes": ["not_trade_advice", "not_executed", "no_fetch_performed"]} for i, (tool, reason) in enumerate(base, 1)]
    for i, obl in enumerate(obligations[:3], len(calls) + 1):
        calls.append({"call_id": f"call_{i:03d}", "tool": "decision.add", "reason": "Record a caller-supplied review/non-action decision if the caller has evidence.", "preconditions": ["caller_supplied_evidence"], "args_template": {"type": "review"}, "source_refs": obl["source_refs"], "caveat_codes": ["requires_caller_supplied_data", "not_trade_advice", "not_executed"]})
    return calls


def _caveats(broadening: list[str], *reports: dict[str, Any]) -> dict[str, Any]:
    return {"hard_boundary_caveats": list(BOUNDARY_CAVEATS), "scope_caveats": broadening, "evidence_caveats": ["no_fetch_performed"], "data_quality_caveats": sorted({c for r in reports for c in r.get("summary", {}).get("caveats", []) + r.get("summary", {}).get("caveat_codes", [])}), "memory_caveats": [], "truncation_caveats": []}


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
        reason = reason or "max_chars"
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


def _enforce_total_budget(packet: dict[str, Any], max_chars_total: int) -> None:
    packet["truncation"]["total_chars_returned"] = _serialized_len(packet)
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
        packet["truncation"]["total_chars_returned"] = _serialized_len(packet)

    if packet["truncation"]["total_chars_returned"] > max_chars_total:
        raise ValueError("bootstrap packet cannot fit within max_chars_total without omitting required metadata")


def _packet_id(packet: dict[str, Any]) -> str:
    clone = deepcopy(packet)
    clone["metadata"]["packet_id"] = "pending"
    raw = json.dumps(clone, sort_keys=True, separators=(",", ":"))
    return "bootstrap:" + hashlib.sha256(raw.encode()).hexdigest()[:24]


__all__ = ["BOOTSTRAP_CONTRACT_VERSION", "compose_bootstrap_packet"]
