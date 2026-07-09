"""Read-only memory usefulness diagnostics with negative controls.

This report intentionally avoids causal claims. It summarizes local recall
telemetry and downstream edge evidence as diagnostics only.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Final

from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports.recall_receipts import ATTRIBUTION_CONVENTIONS, report_recall_receipts

CONTROL_NAMES: Final[tuple[str, ...]] = (
    "recalled_unused",
    "used_contradicted",
    "stale_retrieved",
    "high_confidence_bad_outcome",
    "missing_expected_memory",
    "overfit_harmful",
)
HIGH_CONFIDENCE_THRESHOLD: Final[float] = 0.8
HARMFUL_EDGE_TYPES: Final[set[str]] = {"violates"}


def report_memory_usefulness(
    conn: sqlite3.Connection,
    *,
    recall_id: str | None = None,
    node_id: str | None = None,
    consumer_kind: str | None = None,
    consumer_id: str | None = None,
    run_id: str | None = None,
    agent_id: str | None = None,
    model_id: str | None = None,
    environment: str | None = None,
    instrument_id: str | None = None,
    strategy_id: str | None = None,
    memory_kind: str | None = None,
    as_of: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return deterministic memory usefulness diagnostics.

    The projection is read-only and computed from recall receipts, memory nodes,
    recall events, and existing typed edges. Metrics are associations/caveats,
    not causal estimates, scores, advice, or optimization targets.
    """

    receipts_report = report_recall_receipts(
        conn,
        recall_id=recall_id,
        node_id=node_id,
        consumer_kind=consumer_kind,
        consumer_id=consumer_id,
        run_id=run_id,
        agent_id=agent_id,
        model_id=model_id,
        environment=environment,
        instrument_id=instrument_id,
        strategy_id=strategy_id,
        as_of=as_of,
        limit=limit,
    )
    receipts = receipts_report["recall_receipts"]
    if memory_kind is not None:
        receipts = [_filter_receipt_items(receipt, memory_kind) for receipt in receipts]
        receipts = [receipt for receipt in receipts if receipt["items"]]

    diagnostics = [_diagnostic_for_item(receipt, item, as_of=as_of) for receipt in receipts for item in receipt["items"]]
    controls = _negative_controls(diagnostics)
    caveat_codes = {code for d in diagnostics for code in d["caveat_codes"]} | set(receipts_report["summary"].get("caveat_codes", [])) | {"DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM", "OUTCOME_IMPACT_NOT_INFERRED"}
    for control in controls:
        caveat_codes.update(control["caveat_codes"])
    filt = {
        "recall_id": recall_id,
        "node_id": node_id,
        "consumer_kind": consumer_kind,
        "consumer_id": consumer_id,
        "run_id": run_id,
        "agent_id": agent_id,
        "model_id": model_id,
        "environment": environment,
        "instrument_id": instrument_id,
        "strategy_id": strategy_id,
        "memory_kind": memory_kind,
        "as_of": as_of,
        "limit": limit,
    }
    groups = _groups(diagnostics, filt)
    metrics = {
        "recall_count": len(receipts),
        "retrieved_item_count": len(diagnostics),
        "used_count": sum(1 for d in diagnostics if d["used"]),
        "unused_count": sum(1 for d in diagnostics if not d["used"]),
        "contradicted_count": sum(1 for d in diagnostics if d["contradicted"]),
        "stale_count": sum(1 for d in diagnostics if d["stale"]),
        "source_ref_count": sum(len(d["source_refs"]) for d in diagnostics),
        "negative_control_hit_count": sum(c["count"] for c in controls),
    }
    return standard_report_result(
        summary={
            "bucket": "memory_usefulness",
            "sample_size": len(diagnostics),
            "sample_warning": "no_recall_items" if not diagnostics else None,
            "filter": filt,
            "metrics": metrics,
            "caveat_codes": sorted(caveat_codes),
            "interpretation": "Read-only diagnostic associations over local recall/use evidence; does not estimate or claim causal memory value, profitability, or advice.",
        },
        groups=groups,
        extra={
            "memory_diagnostics": diagnostics,
            "negative_controls": controls,
            "attribution_conventions": ATTRIBUTION_CONVENTIONS,
        },
    )


def _filter_receipt_items(receipt: dict[str, Any], memory_kind: str) -> dict[str, Any]:
    cloned = {**receipt}
    cloned["items"] = [item for item in receipt["items"] if item.get("node_type") == memory_kind]
    cloned["node_ids_returned"] = [item["id"] for item in cloned["items"]]
    cloned["node_ids_used"] = [item["id"] for item in cloned["items"] if item.get("status") == "cited_or_used"]
    cloned["node_ids_ignored_or_unattributed"] = [item["id"] for item in cloned["items"] if item.get("status") != "cited_or_used"]
    return cloned


def _diagnostic_for_item(receipt: dict[str, Any], item: dict[str, Any], *, as_of: str | None) -> dict[str, Any]:
    caveats = set(item.get("caveat_codes", []))
    edge_evidence = item.get("edge_evidence", [])
    used = item.get("status") == "cited_or_used"
    contradicted = any(ev.get("edge_type") == "contradicts" for ev in edge_evidence)
    stale = "STALE_OR_INVALIDATED_MEMORY" in caveats or "STALE_AS_OF_RECEIPT" in caveats or item.get("attribution_status") == "stale"
    harmful = any(ev.get("edge_type") in HARMFUL_EDGE_TYPES for ev in edge_evidence)
    confidence = item.get("confidence_base")
    high_conf_bad = False
    if confidence is not None and confidence >= HIGH_CONFIDENCE_THRESHOLD:
        # No canonical bad-outcome value is available from recall receipts. Only
        # flag when explicit contradictory/harmful edge evidence exists.
        high_conf_bad = contradicted or harmful
    return {
        "recall_id": receipt["recall_id"],
        "node_id": item["id"],
        "memory_kind": item.get("node_type"),
        "rank": item.get("rank"),
        "strategy_id": receipt.get("context", {}).get("strategy_id"),
        "instrument_id": receipt.get("context", {}).get("instrument_id"),
        "agent_id": receipt.get("agent_id"),
        "model_id": receipt.get("model_id"),
        "run_id": receipt.get("run_id"),
        "strategies_used": receipt.get("strategies_used", []),
        "created_at": item.get("created_at"),
        "recalled_at": receipt.get("created_at"),
        "age_days_at_recall": _days_between(item.get("created_at"), receipt.get("created_at")),
        "age_days_as_of": _days_between(item.get("created_at"), as_of) if as_of else None,
        "decay_rate_per_day": item.get("decay_rate_per_day"),
        "confidence_base": confidence,
        "importance": item.get("importance"),
        "used": used,
        "contradicted": contradicted,
        "stale": stale,
        "harmful_edge_based": harmful,
        "high_confidence_bad_outcome_edge_based": high_conf_bad,
        "outcome_impact": "not_measurable_from_current_receipt_evidence",
        "source_refs": item.get("source_refs", []),
        "edge_evidence": edge_evidence,
        "caveat_codes": sorted(caveats | {"DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM"}),
    }


def _negative_controls(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    predicates = {
        "recalled_unused": lambda d: not d["used"],
        "used_contradicted": lambda d: d["used"] and d["contradicted"],
        "stale_retrieved": lambda d: d["stale"],
        "high_confidence_bad_outcome": lambda d: d["high_confidence_bad_outcome_edge_based"],
        "missing_expected_memory": lambda d: False,
        "overfit_harmful": lambda d: d["harmful_edge_based"],
    }
    controls = []
    for name in CONTROL_NAMES:
        matches = [d for d in diagnostics if predicates[name](d)]
        caveats = ["DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM"]
        measurability = "measured_edge_based"
        if name == "missing_expected_memory":
            measurability = "not_measurable"
            caveats.append("NO_EXPECTED_MEMORY_SIGNAL")
        elif name == "high_confidence_bad_outcome":
            measurability = "edge_based_only"
            caveats.append("BAD_OUTCOME_NOT_CANONICALLY_INFERRED")
        elif name == "overfit_harmful":
            measurability = "edge_based_only"
            caveats.append("HARMFUL_OVERFIT_EDGE_BASED_ONLY")
        controls.append({
            "name": name,
            "count": len(matches),
            "node_ids": sorted({d["node_id"] for d in matches}),
            "receipt_refs": sorted({f"recall_receipt:{d['recall_id']}" for d in matches}),
            "measurability": measurability,
            "sample_warning": "insufficient_evidence" if measurability == "not_measurable" else None,
            "caveat_codes": caveats,
        })
    return controls


def _groups(diagnostics: list[dict[str, Any]], filt: dict[str, Any]) -> list[dict[str, Any]]:
    specs = [
        ("strategy", lambda d: d.get("strategy_id")),
        ("retrieval_strategy", lambda d: d.get("strategies_used") or None),
        ("agent", lambda d: d.get("agent_id")),
        ("model", lambda d: d.get("model_id")),
        ("run", lambda d: d.get("run_id")),
        ("memory_kind", lambda d: d.get("memory_kind")),
        ("confidence", lambda d: _confidence_bucket(d.get("confidence_base"))),
        ("age", lambda d: _age_bucket(d.get("age_days_at_recall"))),
        ("decay", lambda d: _decay_bucket(d.get("decay_rate_per_day"))),
        ("outcome_impact", lambda d: d.get("outcome_impact")),
        ("citation_use", lambda d: "used" if d.get("used") else "unused"),
    ]
    groups = []
    for dimension, key_fn in specs:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for diagnostic in diagnostics:
            for key in _group_keys(key_fn(diagnostic)):
                buckets.setdefault(key, []).append(diagnostic)
        for key in sorted(buckets):
            rows = buckets[key]
            groups.append({
                "key": f"{dimension}:{key}",
                "label": f"{dimension}={key}",
                "metrics": {
                    "retrieved_item_count": len(rows),
                    "used_count": sum(1 for d in rows if d["used"]),
                    "contradicted_count": sum(1 for d in rows if d["contradicted"]),
                    "stale_count": sum(1 for d in rows if d["stale"]),
                },
                "filter": filt,
                "record_ids": {"recall_ids": sorted({d["recall_id"] for d in rows}), "memory_node_ids": sorted({d["node_id"] for d in rows})},
                "examples": [{"kind": "memory_node", "id": d["node_id"], "summary": d["outcome_impact"]} for d in rows[:3]],
                "sample_size": len(rows),
                "sample_warning": None,
                "truncated": False,
            })
    return groups


def _confidence_bucket(value: Any) -> str:
    if value is None:
        return "unknown"
    if value >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def _age_bucket(days: Any) -> str:
    if days is None:
        return "unknown"
    if days < 7:
        return "0_6d"
    if days < 30:
        return "7_29d"
    if days < 90:
        return "30_89d"
    return "90d_plus"


def _decay_bucket(value: Any) -> str:
    if value is None:
        return "unknown"
    if value == 0:
        return "none"
    if value <= 0.001:
        return "slow"
    if value <= 0.005:
        return "medium"
    return "fast"


def _group_keys(value: Any) -> list[str]:
    if value is None:
        return ["unknown"]
    if isinstance(value, list):
        keys = sorted({str(item) for item in value if item is not None})
        return keys or ["unknown"]
    return [str(value)]


def _days_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        return None
    return round((end_dt - start_dt).total_seconds() / 86400, 6)
