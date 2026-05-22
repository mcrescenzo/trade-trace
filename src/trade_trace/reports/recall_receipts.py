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

USE_EDGE_TYPES: Final[set[str]] = {"supports", "derived_from", "about", "follows", "violates"}
CONTRADICTION_EDGE_TYPES: Final[set[str]] = {"contradicts"}
SUPERSESSION_EDGE_TYPES: Final[set[str]] = {"supersedes"}
CONSUMER_KINDS: Final[set[str]] = {"decision", "thesis", "forecast", "outcome", "review", "playbook_version"}


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
    maybe_receipts = [
        _receipt_for_event(
            conn,
            event,
            node_filter=node_id,
            consumer_kind=consumer_kind,
            consumer_id=consumer_id,
            as_of=as_of,
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
        extra={"recall_receipts": receipts},
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


def _receipt_for_event(conn: sqlite3.Connection, event: dict[str, Any], *, node_filter: str | None, consumer_kind: str | None, consumer_id: str | None, as_of: str | None) -> dict[str, Any] | None:
    node_ids = [nid for nid in event["node_ids_returned"] if node_filter is None or nid == node_filter]
    items = [_memory_item(conn, nid, rank=i + 1, edge_evidence=_edge_evidence(conn, nid, consumer_kind=consumer_kind, consumer_id=consumer_id, as_of=as_of), as_of=as_of) for i, nid in enumerate(node_ids)]
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


def _memory_item(conn: sqlite3.Connection, node_id: str, *, rank: int, edge_evidence: list[dict[str, Any]], as_of: str | None) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, node_type, title, importance, valid_from, valid_to,
               invalidated_at, invalidated_by
        FROM memory_nodes WHERE id = ?
        """,
        (node_id,),
    ).fetchone()
    caveats: list[str] = []
    if row is None:
        return {"id": node_id, "rank": rank, "status": "missing_node", "edge_evidence": edge_evidence, "source_refs": [], "caveat_codes": ["RETURNED_NODE_MISSING"]}
    node = dict(zip(("id", "node_type", "title", "importance", "valid_from", "valid_to", "invalidated_at", "invalidated_by"), row, strict=True))
    if node["valid_to"] is not None or node["invalidated_at"] is not None:
        caveats.append("STALE_OR_INVALIDATED_MEMORY")
    if as_of is not None and node["valid_to"] is not None and node["valid_to"] <= as_of:
        caveats.append("STALE_AS_OF_RECEIPT")
    if any(ev["edge_type"] in CONTRADICTION_EDGE_TYPES for ev in edge_evidence):
        caveats.append("CONTRADICTED_DOWNSTREAM")
    if any(ev["edge_type"] in SUPERSESSION_EDGE_TYPES for ev in edge_evidence):
        caveats.append("SUPERSEDED_DOWNSTREAM")
    used = any(ev["edge_type"] in USE_EDGE_TYPES for ev in edge_evidence)
    return {
        **node,
        "rank": rank,
        "status": "cited_or_used" if used else "ignored_or_unattributed",
        "edge_evidence": edge_evidence,
        "source_refs": _source_refs_for(conn, node_id),
        "caveat_codes": sorted(set(caveats)),
    }


def _edge_evidence(conn: sqlite3.Connection, node_id: str, *, consumer_kind: str | None, consumer_id: str | None, as_of: str | None) -> list[dict[str, Any]]:
    clauses = ["target_kind = 'memory_node'", "target_id = ?"]
    params: list[Any] = [node_id]
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
        SELECT id, source_kind, source_id, edge_type, created_at
        FROM edges
        WHERE """ + " AND ".join(clauses) + " ORDER BY created_at ASC, id ASC",
        params,
    ).fetchall()
    return [{"edge_id": r[0], "consumer_kind": r[1], "consumer_id": r[2], "edge_type": r[3], "created_at": r[4]} for r in rows]


def _source_refs_for(conn: sqlite3.Connection, node_id: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT target_kind, target_id, edge_type FROM edges
        WHERE source_kind = 'memory_node' AND source_id = ?
        ORDER BY edge_type, target_kind, target_id
        """,
        (node_id,),
    ).fetchall()
    return [{"target_kind": r[0], "target_id": r[1], "edge_type": r[2]} for r in rows]


def _event_dict(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    keys = ("recall_id", "query", "strategies_used", "node_ids_returned", "context", "limit_k", "as_of", "created_at", "actor_id", "agent_id", "model_id", "environment", "run_id")
    data: dict[str, Any] = dict(zip(keys, row, strict=True))
    data["strategies_used"] = _json_list(data["strategies_used"])
    data["node_ids_returned"] = _json_list(data["node_ids_returned"])
    data["context"] = _json_obj(data["context"])
    return data


def _json_list(raw: str) -> list[str]:
    value = json.loads(raw)
    return value if isinstance(value, list) else []


def _json_obj(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    return value if isinstance(value, dict) else {}
