"""Read-only policy candidate report.

Surfaces quarantined/candidate policy reflections from memory metadata without
promoting or mutating policy/playbook state.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from trade_trace.reports._envelope import standard_report_result

CAVEAT_CODES = (
    "POLICY_CANDIDATE_READ_ONLY",
    "NOT_PROMOTED_POLICY",
    "LOCAL_CALLER_SUPPLIED_EVIDENCE_ONLY",
    "SOURCE_ID_BACKED_REVIEW_REQUIRED",
)


def report_policy_candidates(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    strategy_id: str | None = None,
    playbook_id: str | None = None,
    as_of: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return deterministic read-only policy-candidate reflections.

    Candidates are reflection `memory_nodes` whose `meta_json` contains an
    object-valued `policy_candidate`. The report is caveated and source-backed;
    it does not write, promote policy, mutate playbooks, fetch external data, run
    models, or make trading/performance claims.
    """

    if limit < 1:
        raise ValueError("limit must be a positive integer")

    rows = conn.execute(
        """
        SELECT id, title, body, meta_json, confidence_base, importance,
               valid_from, valid_to, invalidated_at, created_at, actor_id,
               agent_id, model_id, environment, run_id
        FROM memory_nodes
        WHERE node_type = 'reflection'
        ORDER BY COALESCE(valid_from, created_at) ASC, created_at ASC, id ASC
        """
    ).fetchall()

    candidates: list[dict[str, Any]] = []
    malformed_ids: list[str] = []
    for row in rows:
        item = _candidate_from_row(row)
        if item is None:
            continue
        if item.get("malformed_metadata"):
            malformed_ids.append(item["node_id"])
        if as_of is not None and not _valid_as_of(item, as_of):
            continue
        if status is not None and item["lifecycle_status"] != status:
            continue
        if strategy_id is not None and item["scope"].get("strategy_id") != strategy_id and item.get("strategy_id") != strategy_id:
            continue
        if playbook_id is not None and item["scope"].get("playbook_id") != playbook_id and item.get("playbook_id") != playbook_id:
            continue
        candidates.append(item)

    total = len(candidates)
    truncated = total > limit
    candidates = candidates[:limit]
    groups = [_group_for_status(key, [c for c in candidates if c["lifecycle_status"] == key], status, strategy_id, playbook_id, as_of, limit) for key in sorted({c["lifecycle_status"] for c in candidates})]
    caveats: set[str] = set(CAVEAT_CODES)
    if malformed_ids:
        caveats.add("MALFORMED_POLICY_CANDIDATE_METADATA_SKIPPED_FIELDS")
    if not candidates:
        caveats.add("NO_POLICY_CANDIDATES_FOUND")

    summary = {
        "bucket": "policy_candidates",
        "sample_size": len(candidates),
        "sample_warning": "no_policy_candidates" if not candidates else None,
        "filter": {"status": status, "strategy_id": strategy_id, "playbook_id": playbook_id, "as_of": as_of, "limit": limit},
        "metrics": {
            "candidate_count": len(candidates),
            "total_matching_before_limit": total,
            "support_count": sum(c["evidence_counts"]["support"] for c in candidates),
            "contradiction_count": sum(c["evidence_counts"]["contradiction"] for c in candidates),
            "missing_evidence_count": sum(len(c["missing_evidence"]) for c in candidates),
            "replay_case_count": sum(len(c["replay_cases"]) for c in candidates),
        },
        "caveat_codes": sorted(caveats),
        "interpretation": "Read-only local report of quarantined/candidate policy reflections. Items are not promoted policy and require source-ID-backed review of support, contradiction, missing evidence, replay cases, and reasons not promoted.",
    }
    return standard_report_result(summary=summary, groups=groups, truncated=truncated, extra={"policy_candidates": candidates})


def _candidate_from_row(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any] | None:
    (node_id, title, body, meta_raw, confidence, importance, valid_from, valid_to, invalidated_at, created_at, actor_id, agent_id, model_id, environment, run_id) = row
    try:
        meta = json.loads(meta_raw or "{}")
    except json.JSONDecodeError:
        return None
    pc = meta.get("policy_candidate") if isinstance(meta, dict) else None
    if not isinstance(pc, dict):
        return None
    scope = _dict_value(pc, "scope")
    evidence = _dict_value(pc, "evidence")
    support = _list_from_any(_first(pc, "support", "supports", "supporting_evidence", default=None) or evidence.get("support") or evidence.get("supports"))
    contradiction = _list_from_any(_first(pc, "contradiction", "contradictions", "contradicting_evidence", default=None) or evidence.get("contradiction") or evidence.get("contradictions"))
    source_refs = sorted(set(_string_refs(pc.get("source_refs")) | _string_refs(pc.get("source_ids")) | _string_refs(evidence.get("source_refs")) | _string_refs(support) | _string_refs(contradiction)))
    recall_refs = sorted(set(_string_refs(_first(pc, "recall_refs", "recall_references", default=None))))
    adherence_refs = sorted(set(_string_refs(_first(pc, "adherence_refs", "adherence_references", default=None))))
    replay_cases = sorted(set(_string_refs(_first(pc, "replay_cases", "replay_refs", "replay_references", default=None))))
    missing = _list_from_any(_first(pc, "missing_evidence", "evidence_gaps", "missing_evidence_gaps", default=[]))
    why_not = _list_from_any(_first(pc, "why_not_promoted", "reasons_not_promoted", "not_promoted_reasons", default=[]))
    rejection_reason = _first(pc, "rejection_reason", "rejected_reason", default=None)
    if rejection_reason and rejection_reason not in why_not:
        why_not.append(rejection_reason)
    status = str(_first(pc, "lifecycle_status", "status", default="candidate"))
    return {
        "node_id": node_id,
        "memory_node_id": node_id,
        "title": title,
        "candidate_statement": _first(pc, "candidate_statement", "statement", default=body),
        "lifecycle_status": status,
        "scope": scope,
        "strategy_id": pc.get("strategy_id") or scope.get("strategy_id"),
        "playbook_id": pc.get("playbook_id") or scope.get("playbook_id"),
        "playbook_version_id": pc.get("playbook_version_id") or scope.get("playbook_version_id"),
        "support": support,
        "contradiction": contradiction,
        "evidence_counts": {"support": _count(pc, "support_count", support), "contradiction": _count(pc, "contradiction_count", contradiction)},
        "missing_evidence": missing,
        "caveats": _list_from_any(pc.get("caveats")) + ["not_promoted_policy", "read_only_candidate_report"],
        "replay_cases": replay_cases,
        "recall_refs": recall_refs,
        "source_refs": source_refs,
        "adherence_refs": adherence_refs,
        "rejection_reason": rejection_reason,
        "superseded_by": pc.get("superseded_by"),
        "why_not_promoted": why_not,
        "reasons_not_promoted": why_not,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "invalidated_at": invalidated_at,
        "created_at": created_at,
        "provenance": {"actor_id": actor_id, "agent_id": agent_id, "model_id": model_id, "environment": environment, "run_id": run_id},
        "confidence_base": confidence,
        "importance": importance,
    }


def _group_for_status(status: str, items: list[dict[str, Any]], status_filter: str | None, strategy_id: str | None, playbook_id: str | None, as_of: str | None, limit: int) -> dict[str, Any]:
    return {"key": status, "label": f"Policy candidates with status {status}", "metrics": {"candidate_count": len(items), "support_count": sum(i["evidence_counts"]["support"] for i in items), "contradiction_count": sum(i["evidence_counts"]["contradiction"] for i in items), "missing_evidence_count": sum(len(i["missing_evidence"]) for i in items)}, "filter": {"status": status_filter or status, "strategy_id": strategy_id, "playbook_id": playbook_id, "as_of": as_of, "limit": limit}, "record_ids": {"memory_nodes": [i["node_id"] for i in items], "sources": sorted({s for i in items for s in i["source_refs"]}), "replay_cases": sorted({r for i in items for r in i["replay_cases"]})}, "examples": [{"kind": "memory_node", "id": i["node_id"], "summary": str(i["candidate_statement"])[:160]} for i in items[:3]], "sample_size": len(items), "sample_warning": None, "truncated": False}


def _valid_as_of(item: dict[str, Any], as_of: str) -> bool:
    return item["valid_from"] <= as_of and (item["valid_to"] is None or item["valid_to"] > as_of) and (item["invalidated_at"] is None or item["invalidated_at"] > as_of)


def _first(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


def _dict_value(d: dict[str, Any], key: str) -> dict[str, Any]:
    value = d.get(key)
    return value if isinstance(value, dict) else {}


def _list_from_any(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _count(d: dict[str, Any], key: str, fallback: list[Any]) -> int:
    value = d.get(key)
    return value if isinstance(value, int) else len(fallback)


def _string_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    for item in _list_from_any(value):
        if isinstance(item, str):
            refs.add(item)
        elif isinstance(item, dict):
            for key in ("source_id", "source_ref", "id", "record_id", "case_id", "recall_id"):
                if isinstance(item.get(key), str):
                    refs.add(item[key])
    return refs
