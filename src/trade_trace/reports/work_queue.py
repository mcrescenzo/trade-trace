"""Derived agent work-queue / next-action report.

This module is intentionally read-only. It projects existing lifecycle cases into
process-obligation items for fresh agent sessions; it does not create, assign,
schedule, persist, notify, fetch, or execute anything.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import process_filter
from trade_trace.reports.lifecycle import derive_lifecycle_cases
from trade_trace.reports.watchlist import DEFAULT_STALE_THRESHOLD_DAYS
from trade_trace.timestamps import to_utc_iso8601
from trade_trace.tools._helpers import now_iso

WorkQueueKind = Literal[
    "resolve_due_forecast",
    "review_due_watch",
    "review_stale_record",
    "record_reflection",
    "record_playbook_adherence",
]

_BOUNDARY_CAVEATS = [
    "derived_read_only",
    "local_rows_only",
    "no_scheduler_daemon_or_reminder",
    "no_assignment_or_broker_action",
    "no_external_fetch_or_market_lookup",
    "no_trading_advice_or_signal",
]
_FORBIDDEN_ACTIONS = [
    "schedule_job",
    "start_daemon",
    "assign_owner",
    "send_notification",
    "fetch_market_data",
    "fetch_outcome",
    "submitting_orders",
    "trading_execution",
    "connect_wallet_or_broker",
    "rank_trade_opportunities",
]

_ALLOWED_BY_KIND: dict[WorkQueueKind, list[str]] = {
    "resolve_due_forecast": [
        "inspect_forecast_and_resolution_rule",
        "review_caller_supplied_outcome_evidence",
        "record_outcome_or_resolution_when_caller_supplies_evidence",
        # outcome.fetch ingests on-chain resolution and needs
        # network.polymarket.polygon_rpc_url (fails closed CONFIG_REQUIRED when
        # unset). With no RPC, the no-RPC evidence route is the Gamma read path:
        # snapshot.fetch / market.refresh carry winningOutcome/outcomePrices
        # without an RPC endpoint, then resolution.add records it. Signposting
        # this here keeps an automated resolution feeder from dead-ending so
        # forecasts can progress toward the calibration N>=20 floor
        # (bead trade-trace-isqo).
        "fetch_gamma_resolution_evidence_via_snapshot_fetch_when_no_polygon_rpc",
        "document_missing_external_input",
    ],
    "review_due_watch": [
        "inspect_watch_and_linked_context",
        "record_review_decision",
        "update_or_invalidate_thesis_with_caller_supplied_basis",
        "record_reflection_if_review_changes_process_learning",
    ],
    "review_stale_record": [
        "inspect_stale_record_and_linked_context",
        "record_review_or_update_source_record",
        "document_continuing_watch_reason_if_applicable",
    ],
    "record_reflection": [
        "inspect_outcome_review_and_source_context",
        "record_reflection_memory_if_caller_accepts_lesson",
        "link_reflection_to_source_artifact",
    ],
    "record_playbook_adherence": [
        "inspect_decision_and_playbook_version",
        "record_considered_followed_overridden_or_not_applicable_rows",
        "document_override_reason_from_caller_supplied_context",
    ],
}

_PRIORITY_BY_STATE = {
    "pending_review": "due",
    "stale": "stale",
    "reflection_due": "due",
    "adherence_due": "hygiene",
}


def report_work_queue(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    as_of: str | None = None,
    stale_threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS,
    kinds: list[str] | None = None,
) -> dict[str, Any]:
    """Return deterministic derived process-obligation items.

    The output is a report over caller-supplied local rows only. Queue items are
    transient projections with closure conditions, not durable tasks.
    """

    if not isinstance(stale_threshold_days, int) or stale_threshold_days < 0:
        raise ValueError("stale_threshold_days must be a non-negative integer")
    if kinds is not None and (not isinstance(kinds, list) or not all(isinstance(item, str) for item in kinds)):
        raise ValueError("kinds must be a list of strings")
    allowed_kinds = set(WorkQueueKind.__args__)  # type: ignore[attr-defined]
    kind_filter = sorted(set(kinds or []))
    unknown = [kind for kind in kind_filter if kind not in allowed_kinds]
    if unknown:
        raise ValueError(f"unsupported work queue kind(s): {unknown!r}")

    resolved_as_of = to_utc_iso8601(as_of or now_iso(), field="as_of")
    rf = ReportFilter.model_validate(raw_filter or {})
    filter_view = process_filter(rf, report="report.work_queue")

    lifecycle_cases = derive_lifecycle_cases(conn, as_of=resolved_as_of, stale_threshold_days=stale_threshold_days)
    items: list[dict[str, Any]] = []
    for case in lifecycle_cases:
        item = _item_from_case(case, resolved_as_of)
        if item is not None:
            items.append(item)
    items = [item for item in items if _item_matches_filter(item, rf)]
    if kind_filter:
        items = [item for item in items if item["kind"] in kind_filter]
    items = sorted(items, key=_item_sort_key)

    kind_counts = {kind: 0 for kind in sorted(allowed_kinds)}
    priority_counts: dict[str, int] = {}
    for item in items:
        kind_counts[item["kind"]] += 1
        priority_counts[item["priority"]] = priority_counts.get(item["priority"], 0) + 1

    groups = [
        {
            "key": item["item_id"],
            "label": f"{item['kind']} work-queue item",
            "metrics": {
                "kind": item["kind"],
                "priority": item["priority"],
                "due_at": item.get("due_at"),
                "required_external_input": item["required_external_input"],
            },
            "filter": {**filter_view, "kinds": kind_filter},
            "record_ids": item["record_ids"],
            "examples": [{"kind": "work_queue_item", "id": item["item_id"], "summary": item["reason"]}],
            "sample_size": 1,
            "sample_warning": None,
            "truncated": False,
        }
        for item in items
    ]
    return standard_report_result(
        summary={
            "sample_size": len(items),
            "sample_warning": None,
            "filter": {**filter_view, "kinds": kind_filter},
            "metrics": {
                "item_count": len(items),
                "kind_counts": kind_counts,
                "priority_counts": dict(sorted(priority_counts.items())),
                "stale_threshold_days": stale_threshold_days,
            },
            "caveats": _BOUNDARY_CAVEATS,
            "boundary": "Derived process-obligation report only; not a scheduler, daemon, assignment system, broker, execution, or advice path.",
        },
        groups=groups,
        extra={"as_of": resolved_as_of, "work_queue": items, "next_actions": _next_actions_projection(items)},
    )


def agent_next_actions(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]:
    """Safe alias/projection over report_work_queue; no planner semantics."""

    data = report_work_queue(conn, **kwargs)
    data["summary"]["surface"] = "agent.next_actions"
    data["summary"]["alias_of"] = "report.work_queue"
    data["summary"]["boundary"] = "Projection of report.work_queue allowed process actions only; no planning, scheduling, assignment, fetching, broker, execution, or advice path."
    return data


def _item_from_case(case: dict[str, Any], as_of: str) -> dict[str, Any] | None:
    state = case["state"]
    refs = case.get("source_refs") or []
    if not refs:
        return None
    primary = _primary_ref(case)
    if primary is None:
        return None
    if state == "pending_review" and primary["kind"] == "forecast":
        kind: WorkQueueKind = "resolve_due_forecast"
    elif state == "pending_review":
        kind = "review_due_watch"
    elif state == "stale":
        kind = "review_stale_record"
    elif state == "reflection_due":
        kind = "record_reflection"
    elif state == "adherence_due":
        kind = "record_playbook_adherence"
    else:
        return None

    caveats = sorted(set([*case.get("caveat_codes", []), *_BOUNDARY_CAVEATS]))
    return {
        "item_id": f"derived:work_queue:{kind}:{primary['kind']}:{primary['id']}",
        "kind": kind,
        "priority": _PRIORITY_BY_STATE.get(state, "hygiene"),
        "caveat": caveats,
        "source_refs": refs,
        "reason": _reason(kind, case),
        "allowed_actions": _ALLOWED_BY_KIND[kind],
        "forbidden_actions": _FORBIDDEN_ACTIONS,
        "closure_condition": _closure_condition(kind, primary),
        "required_external_input": kind == "resolve_due_forecast",
        "due_at": case.get("due_at"),
        "as_of": as_of,
        "trigger_evidence": {"report": "report.lifecycle", "case_id": case["case_id"], "state": state, "reason_codes": case.get("reason_codes", [])},
        "record_ids": _record_ids(refs),
    }


def _primary_ref(case: dict[str, Any]) -> dict[str, str] | None:
    case_id = case.get("case_id", "")
    preferred = "forecast" if ":forecast:" in case_id else "decision"
    for ref in case.get("source_refs", []):
        if ref.get("kind") == preferred:
            return ref
    return case.get("source_refs", [None])[0]


def _reason(kind: str, case: dict[str, Any]) -> str:
    codes = ",".join(case.get("reason_codes", []))
    due = case.get("due_at")
    suffix = f" due_at={due}" if due else ""
    return f"Derived from lifecycle state {case['state']} ({codes}){suffix}."


def _closure_condition(kind: str, primary: dict[str, str]) -> str:
    if kind == "resolve_due_forecast":
        return f"Closes when forecast {primary['id']} has a final/superseding recorded outcome/score or is superseded/invalidated."
    if kind in {"review_due_watch", "review_stale_record"}:
        return f"Closes when source {primary['kind']} {primary['id']} is reviewed, superseded, updated, invalidated, or no longer stale/due under lifecycle rules."
    if kind == "record_reflection":
        return f"Closes when a reflection memory is linked about {primary['kind']} {primary['id']} or the source is superseded/closed."
    return f"Closes when playbook adherence rows exist for {primary['kind']} {primary['id']} or the decision/playbook link is superseded."


def _record_ids(refs: list[dict[str, str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ref in refs:
        out.setdefault(f"{ref['kind']}s", []).append(ref["id"])
    return {kind: sorted(set(ids)) for kind, ids in sorted(out.items())}


def _item_matches_filter(item: dict[str, Any], rf: ReportFilter) -> bool:
    refs = {(ref["kind"], ref["id"]) for ref in item["source_refs"]}
    if rf.instrument.instrument_id and not any(("instrument", inst) in refs for inst in rf.instrument.instrument_id):
        return False
    if rf.strategy.strategy_id and ("strategy", rf.strategy.strategy_id) not in refs:
        return False
    if rf.actors.run_id and not any(("run", run_id) in refs for run_id in rf.actors.run_id):
        return False
    return True


def _item_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    priority_order = {"due": "0", "stale": "1", "hygiene": "2"}
    return (priority_order.get(item["priority"], "9"), item.get("due_at") or "", item["item_id"])


def _next_actions_projection(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "item_id": item["item_id"],
            "kind": item["kind"],
            "priority": item["priority"],
            "source_refs": item["source_refs"],
            "reason": item["reason"],
            "allowed_actions": item["allowed_actions"],
            "forbidden_actions": item["forbidden_actions"],
            "closure_condition": item["closure_condition"],
            "required_external_input": item["required_external_input"],
            "caveat": item["caveat"],
        }
        for item in items
    ]


__all__ = ["agent_next_actions", "report_work_queue"]
