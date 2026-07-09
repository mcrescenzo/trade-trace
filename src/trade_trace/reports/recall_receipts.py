"""Computed recall receipts over memory recall telemetry and typed edges.

Recall receipts are deliberately read-only: they are reconstructed from
``memory_recall_events``, ``memory_nodes``, and existing typed edges rather than
materialized in a receipt table.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Final

from trade_trace.reports._envelope import standard_report_result
from trade_trace.tools._helpers import now_iso

USE_EDGE_TYPES: Final[set[str]] = {"supports", "derived_from", "about", "follows", "violates"}
CONTRADICTION_EDGE_TYPES: Final[set[str]] = {"contradicts"}
SUPERSESSION_EDGE_TYPES: Final[set[str]] = {"supersedes"}
HARMFUL_EDGE_TYPES: Final[set[str]] = {"violates"}
CONSUMER_KINDS: Final[set[str]] = {"decision", "thesis", "forecast", "outcome", "review", "playbook_version"}
ATTRIBUTION_CONVENTIONS: Final[dict[str, Any]] = {
    "use_link_direction": "consumer -> memory_node",
    "use_edge_types": sorted(USE_EDGE_TYPES),
    "contradiction_edge_types": sorted(CONTRADICTION_EDGE_TYPES),
    "supersession_edge_types": sorted(SUPERSESSION_EDGE_TYPES),
    "source_reference_direction": "memory_node -> source (not downstream use evidence)",
    "strong_inference_requires": "consumer_kind plus consumer_id",
}


def report_recall_receipts(
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
    as_of: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return deterministic computed recall receipts.

    ``as_of`` bounds recall events and downstream edge evidence by their
    creation timestamps. No rows are written and no hidden clock is consulted.
    """

    if limit < 1:
        raise ValueError("limit must be a positive integer")
    if consumer_kind is not None and consumer_kind not in CONSUMER_KINDS:
        raise ValueError(f"unsupported consumer_kind: {consumer_kind!r}")
    if consumer_id is not None and consumer_kind is None:
        raise ValueError("consumer_kind is required when consumer_id is supplied")

    events = _load_recall_events(
        conn,
        recall_id=recall_id,
        node_id=node_id,
        run_id=run_id,
        agent_id=agent_id,
        model_id=model_id,
        environment=environment,
        instrument_id=instrument_id,
        strategy_id=strategy_id,
        as_of=as_of,
        limit=limit,
    )
    # Batch the three per-node lookups across ALL events up front so
    # report.recall_receipts no longer issues 3 SQL queries per returned
    # node (trade-trace-qf78). The consumer_kind/consumer_id/as_of filters
    # are constant for the whole call, so a node's memory row, incoming
    # edge-evidence, and outgoing source_refs are identical wherever that
    # node appears, and can be assembled once into dicts keyed by node_id.
    all_node_ids = [
        nid
        for event in events
        for nid in event["node_ids_returned"]
        if node_id is None or nid == node_id
    ]
    nodes_by_id = _memory_nodes_batch(conn, all_node_ids)
    evidence_by_node = _edge_evidence_batch(
        conn, all_node_ids, consumer_kind=consumer_kind, consumer_id=consumer_id, as_of=as_of
    )
    source_refs_by_node = _source_refs_batch(conn, all_node_ids)
    maybe_receipts = [
        _receipt_for_event(
            event,
            node_filter=node_id,
            consumer_kind=consumer_kind,
            as_of=as_of,
            nodes_by_id=nodes_by_id,
            evidence_by_node=evidence_by_node,
            source_refs_by_node=source_refs_by_node,
        )
        for event in events
    ]
    receipts: list[dict[str, Any]] = [receipt for receipt in maybe_receipts if receipt is not None]

    status_counts = {"raw_retrieved": 0, "cited_or_used": 0, "ignored_or_unattributed": 0}
    caveat_codes: set[str] = set()
    for receipt in receipts:
        caveat_codes.update(receipt["caveat_codes"])
        for item in receipt["items"]:
            status_counts["raw_retrieved"] += 1
            if item["status"] == "cited_or_used":
                status_counts["cited_or_used"] += 1
            elif item["status"] == "ignored_or_unattributed":
                status_counts["ignored_or_unattributed"] += 1
            caveat_codes.update(item["caveat_codes"])

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
        "as_of": as_of,
        "limit": limit,
    }
    groups = [
        {
            "key": receipt["recall_id"],
            "label": "computed recall receipt",
            "metrics": {
                "returned_count": len(receipt["items"]),
                "used_count": len(receipt["node_ids_used"]),
                "ignored_or_unattributed_count": len(receipt["node_ids_ignored_or_unattributed"]),
            },
            "filter": filt,
            "record_ids": {"recall_ids": [receipt["recall_id"]], "memory_node_ids": receipt["node_ids_returned"]},
            "examples": [{"kind": "recall_receipt", "id": receipt["receipt_id"], "summary": receipt["query"]}],
            "sample_size": len(receipt["items"]),
            "sample_warning": None,
            "truncated": False,
        }
        for receipt in receipts
    ]
    return standard_report_result(
        summary={
            "bucket": "recall_receipts",
            "sample_size": len(receipts),
            "sample_warning": "no_recall_events" if not receipts else None,
            "filter": filt,
            "metrics": {"receipt_count": len(receipts), **status_counts},
            "caveat_codes": sorted(caveat_codes),
        },
        groups=groups,
        extra={"recall_receipts": receipts, "attribution_conventions": ATTRIBUTION_CONVENTIONS},
    )


def _load_recall_events(conn: sqlite3.Connection, **filters: Any) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for col in ("recall_id", "run_id", "agent_id", "model_id", "environment"):
        if filters.get(col) is not None:
            clauses.append(f"{col} = ?")
            params.append(filters[col])
    if filters.get("as_of") is not None:
        clauses.append("created_at <= ?")
        params.append(filters["as_of"])
    if filters.get("node_id") is not None:
        clauses.append(
            "json_valid(node_ids_returned) "
            "AND EXISTS (SELECT 1 FROM json_each(node_ids_returned) WHERE value = ?)"
        )
        params.append(filters["node_id"])
    for key in ("instrument_id", "strategy_id"):
        expected = filters.get(key)
        if expected is not None:
            clauses.append("json_valid(context_json) AND json_extract(context_json, ?) = ?")
            params.extend((f"$.{key}", expected))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"""
        SELECT recall_id, query, strategies_used, node_ids_returned, context_json,
               limit_k, as_of, created_at, actor_id, agent_id, model_id, environment, run_id
        FROM memory_recall_events{where}
        ORDER BY created_at ASC, recall_id ASC
        LIMIT ?
        """,
        (*params, filters["limit"]),
    ).fetchall()
    events = [_event_dict(row) for row in rows]
    return [event for event in events if _event_matches_json_filters(event, filters)]


def _event_matches_json_filters(event: dict[str, Any], filters: dict[str, Any]) -> bool:
    node_id = filters.get("node_id")
    if node_id is not None and node_id not in event["node_ids_returned"]:
        return False
    context = event["context"]
    for key in ("instrument_id", "strategy_id"):
        expected = filters.get(key)
        if expected is not None and context.get(key) != expected:
            return False
    return True


def _receipt_for_event(
    event: dict[str, Any],
    *,
    node_filter: str | None,
    consumer_kind: str | None,
    as_of: str | None,
    nodes_by_id: dict[str, dict[str, Any] | None],
    evidence_by_node: dict[str, list[dict[str, Any]]],
    source_refs_by_node: dict[str, list[dict[str, str]]],
) -> dict[str, Any] | None:
    node_ids = [nid for nid in event["node_ids_returned"] if node_filter is None or nid == node_filter]
    items = [
        _memory_item(
            nid,
            rank=i + 1,
            node_row=nodes_by_id.get(nid),
            edge_evidence=evidence_by_node.get(nid, []),
            source_refs=source_refs_by_node.get(nid, []),
            as_of=as_of,
        )
        for i, nid in enumerate(node_ids)
    ]
    if consumer_kind is not None and not any(item["edge_evidence"] for item in items):
        return None
    used = [item["id"] for item in items if item["status"] == "cited_or_used"]
    ignored = [item["id"] for item in items if item["status"] == "ignored_or_unattributed"]
    caveats = sorted({code for item in items for code in item["caveat_codes"]})
    if not any(item["edge_evidence"] for item in items):
        caveats.append("NO_DOWNSTREAM_USE_EVIDENCE")
    if consumer_kind is None:
        caveats.append("CONSUMER_INFERENCE_UNSCOPED")
    return {
        "receipt_id": f"recall_receipt:{event['recall_id']}",
        "recall_id": event["recall_id"],
        "query": event["query"],
        "context": event["context"],
        "strategies_used": event["strategies_used"],
        "limit_k": event["limit_k"],
        "as_of": event["as_of"],
        "created_at": event["created_at"],
        "actor_id": event["actor_id"],
        "agent_id": event["agent_id"],
        "model_id": event["model_id"],
        "environment": event["environment"],
        "run_id": event["run_id"],
        "node_ids_returned": node_ids,
        "node_ids_used": used,
        "node_ids_ignored_or_unattributed": ignored,
        "items": items,
        "source_refs": [{"kind": "memory_recall_event", "id": event["recall_id"]}],
        "caveat_codes": sorted(set(caveats)),
    }


MEMORY_NODE_COLUMNS: Final[tuple[str, ...]] = (
    "id", "node_type", "title", "body", "importance", "confidence_base", "decay_rate_per_day",
    "valid_from", "valid_to", "invalidated_at", "invalidated_by", "created_at",
)


def _memory_item(
    node_id: str,
    *,
    rank: int,
    node_row: dict[str, Any] | None,
    edge_evidence: list[dict[str, Any]],
    source_refs: list[dict[str, str]],
    as_of: str | None,
) -> dict[str, Any]:
    caveats: list[str] = []
    if node_row is None:
        return {"id": node_id, "rank": rank, "status": "missing_node", "edge_evidence": edge_evidence, "source_refs": [], "caveat_codes": ["RETURNED_NODE_MISSING"]}
    node = node_row
    # A finite valid_to in the future is a planned expiry, not staleness; only
    # flag STALE_OR_INVALIDATED_MEMORY when the node is actually expired or
    # invalidated at the effective evaluation time (trade-trace-uycm).
    effective = as_of or now_iso()
    valid_to = node["valid_to"]
    invalidated_at = node["invalidated_at"]
    if (valid_to is not None and valid_to <= effective) or (invalidated_at is not None and invalidated_at <= effective):
        caveats.append("STALE_OR_INVALIDATED_MEMORY")
    if as_of is not None and valid_to is not None and valid_to <= as_of:
        caveats.append("STALE_AS_OF_RECEIPT")
    if any(ev["edge_type"] in CONTRADICTION_EDGE_TYPES for ev in edge_evidence):
        caveats.append("CONTRADICTED_DOWNSTREAM")
    if any(ev["edge_type"] in SUPERSESSION_EDGE_TYPES for ev in edge_evidence):
        caveats.append("SUPERSEDED_DOWNSTREAM")
    if any(ev["edge_type"] in HARMFUL_EDGE_TYPES for ev in edge_evidence):
        caveats.append("HARMFUL_DOWNSTREAM")
    used = any(ev["edge_type"] in USE_EDGE_TYPES for ev in edge_evidence)
    contradicted = any(ev["edge_type"] in CONTRADICTION_EDGE_TYPES for ev in edge_evidence)
    superseded = any(ev["edge_type"] in SUPERSESSION_EDGE_TYPES for ev in edge_evidence)
    attribution_status = _attribution_status(used=used, contradicted=contradicted, superseded=superseded, caveats=caveats)
    return {
        **node,
        "rank": rank,
        "status": "cited_or_used" if used else "ignored_or_unattributed",
        "attribution_status": attribution_status,
        "edge_evidence": edge_evidence,
        "source_refs": source_refs,
        "caveat_codes": sorted(set(caveats)),
    }


def _attribution_status(*, used: bool, contradicted: bool, superseded: bool, caveats: list[str]) -> str:
    if used:
        return "cited_or_used"
    if contradicted:
        return "contradicted"
    if superseded or "STALE_OR_INVALIDATED_MEMORY" in caveats or "STALE_AS_OF_RECEIPT" in caveats:
        return "stale"
    return "not_attributable"


def _memory_nodes_batch(conn: sqlite3.Connection, node_ids: list[str]) -> dict[str, dict[str, Any] | None]:
    """Fetch every requested memory node in a single ``IN (...)`` query.

    Returns ``{node_id: node_dict}`` for ids that resolve to a row and
    ``{node_id: None}`` for ids with no matching row (so callers see the
    same "missing node" signal the per-node ``WHERE id = ?`` lookup gave).
    Selected columns and dict-key order match the prior per-node query so
    the report output is byte-for-byte unchanged (trade-trace-qf78).
    """

    nodes: dict[str, dict[str, Any] | None] = {nid: None for nid in node_ids}
    if not nodes:
        return nodes
    unique_ids = list(nodes)
    placeholders = ",".join("?" for _ in unique_ids)
    rows = conn.execute(
        f"""
        SELECT id, node_type, title, body, importance, confidence_base, decay_rate_per_day,
               valid_from, valid_to, invalidated_at, invalidated_by, created_at
        FROM memory_nodes WHERE id IN ({placeholders})
        """,
        tuple(unique_ids),
    ).fetchall()
    for row in rows:
        node = dict(zip(MEMORY_NODE_COLUMNS, row, strict=True))
        nodes[node["id"]] = node
    return nodes


def _edge_evidence_batch(
    conn: sqlite3.Connection,
    node_ids: list[str],
    *,
    consumer_kind: str | None,
    consumer_id: str | None,
    as_of: str | None,
) -> dict[str, list[dict[str, Any]]]:
    """Batched form of the per-node incoming-evidence lookup.

    Fetches all incoming consumer->memory_node edges for every requested
    node in one query grouped by ``target_id``. The per-node ordering
    (``created_at ASC, id ASC``) is preserved byte-identically: the leading
    ``target_id`` in the ORDER BY only groups rows, it does not reorder
    within a node.
    """

    evidence: dict[str, list[dict[str, Any]]] = {nid: [] for nid in node_ids}
    if not evidence:
        return evidence
    unique_ids = list(evidence)
    clauses = ["target_kind = 'memory_node'", "target_id IN (" + ",".join("?" for _ in unique_ids) + ")"]
    params: list[Any] = list(unique_ids)
    if consumer_kind is not None:
        clauses.append("source_kind = ?")
        params.append(consumer_kind)
    else:
        clauses.append("source_kind IN (" + ",".join("?" for _ in CONSUMER_KINDS) + ")")
        params.extend(sorted(CONSUMER_KINDS))
    if consumer_id is not None:
        clauses.append("source_id = ?")
        params.append(consumer_id)
    if as_of is not None:
        clauses.append("created_at <= ?")
        params.append(as_of)
    rows = conn.execute(
        """
        SELECT target_id, id, source_kind, source_id, edge_type, created_at
        FROM edges
        WHERE """ + " AND ".join(clauses) + " ORDER BY target_id, created_at ASC, id ASC",
        params,
    ).fetchall()
    for target_id, eid, source_kind, source_id, edge_type, created_at in rows:
        evidence[target_id].append({"edge_id": eid, "consumer_kind": source_kind, "consumer_id": source_id, "edge_type": edge_type, "created_at": created_at})
    return evidence


def _source_refs_batch(conn: sqlite3.Connection, node_ids: list[str]) -> dict[str, list[dict[str, str]]]:
    """Batched form of the per-node outgoing-source-ref lookup.

    Fetches all outgoing memory_node->source edges for every requested
    node in one query grouped by ``source_id``. The per-node ordering
    (``edge_type, target_kind, target_id``) is preserved byte-identically:
    the leading ``source_id`` only groups rows.
    """

    refs: dict[str, list[dict[str, str]]] = {nid: [] for nid in node_ids}
    if not refs:
        return refs
    unique_ids = list(refs)
    placeholders = ",".join("?" for _ in unique_ids)
    rows = conn.execute(
        f"""
        SELECT source_id, target_kind, target_id, edge_type FROM edges
        WHERE source_kind = 'memory_node' AND source_id IN ({placeholders})
        ORDER BY source_id, edge_type, target_kind, target_id
        """,
        tuple(unique_ids),
    ).fetchall()
    for source_id, target_kind, target_id, edge_type in rows:
        refs[source_id].append({"target_kind": target_kind, "target_id": target_id, "edge_type": edge_type})
    return refs


def _event_dict(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    keys = ("recall_id", "query", "strategies_used", "node_ids_returned", "context", "limit_k", "as_of", "created_at", "actor_id", "agent_id", "model_id", "environment", "run_id")
    data: dict[str, Any] = dict(zip(keys, row, strict=True))
    data["strategies_used"] = _json_list(data["strategies_used"])
    data["node_ids_returned"] = _json_list(data["node_ids_returned"])
    data["context"] = _json_obj(data["context"])
    return data


def _json_list(raw: str | None) -> list[str]:
    # Defensive: a NULL or malformed payload in memory_recall_events used to
    # crash the entire report.recall_receipts call (trade-trace-m9k4). Match
    # the safe-default pattern used by every other JSON loader in this repo.
    if raw is None:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _json_obj(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
