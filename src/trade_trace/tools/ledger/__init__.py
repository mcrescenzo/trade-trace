"""M1 manual ledger / source / resolution write tools per PRD §4.0–§4.5.

Each tool below is a pure dispatch handler: validates args, opens the DB,
writes a primary row inside a UnitOfWork, writes the matching event via
the EventWriter, and returns the new row's id (and key fields) in the
success envelope's `data` payload.

The implementation is intentionally compact — heavy validation lives in
shared helpers (`_helpers.py`, `decision_matrix.py`, the storage CHECK
constraints, the EventWriter, the timestamp normalizer, and the actor_id
grammar in contracts/grammar.py).
"""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    common_metadata,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    open_db_for_args,
    reject_if_contains_secrets,
    require,
)
from trade_trace.tools._helpers import (
    store_metadata_json as _store_metadata_json,
)
from trade_trace.tools.decision_matrix import (
    allowed_decision_types,
    decision_matrix_contract,
    material_non_action_taxonomy,
)
from trade_trace.tools.errors import ToolError

# Internally used: see _outcome_add body below.
from trade_trace.tools.ledger._scoring import (
    _autoscore_pending_forecasts,
    _emit_forecast_scored,
)

# Re-exported for external callers (journal.py rescan, tests/integration/
# test_scoring_lifecycle.py) — see __all__ at module bottom. The aliases
# are deliberate per ruff PLC0414 so the surface is explicit.
from trade_trace.tools.ledger._scoring import (
    _current_resolved_final_outcome as _current_resolved_final_outcome,
)
from trade_trace.tools.ledger._scoring import (
    _score_one_forecast as _score_one_forecast,
)
from trade_trace.tools.ledger._scoring import (
    derive_scoring_state as derive_scoring_state,
)

# Per-domain entity handlers extracted per bead trade-trace-dh3b.
from trade_trace.tools.ledger.decision import _decision_add
from trade_trace.tools.ledger.forecast import _forecast_add, _forecast_supersede
from trade_trace.tools.ledger.instrument import _instrument_add
from trade_trace.tools.ledger.snapshot import _snapshot_add
from trade_trace.tools.ledger.thesis import _thesis_add
from trade_trace.tools.ledger.venue import _venue_add

# -- outcome.add / resolve.record ------------------------------------------

def _outcome_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    instrument_id = require(args, "instrument_id")
    resolved_at = normalize_timestamp(args, "resolved_at", required=True)
    outcome_label = require(args, "outcome_label")
    status = require(args, "status")
    idempotency_key = args.get("idempotency_key")
    seg = common_metadata(args)
    metadata_json = _store_metadata_json(args)

    def _payload(oid: str) -> dict[str, Any]:
        return {
            "id": oid,
            "instrument_id": instrument_id,
            "resolved_at": resolved_at,
            "outcome_label": outcome_label,
            "outcome_value": args.get("outcome_value"),
            "status": status,
            "source": args.get("source", "manual"),
            "confidence": args.get("confidence"),
        }

    db = open_db_for_args(args)
    auto_scored: list[dict[str, Any]] = []
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="outcome.recorded",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                outcome_id = replay["id"]
                emit_event(
                    uow, event_type="outcome.recorded",
                    subject_kind="outcome", subject_id=outcome_id,
                    payload=_payload(outcome_id),
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT created_at FROM outcomes WHERE id = ?", (outcome_id,)
                ).fetchone()
                return {"id": outcome_id, "instrument_id": instrument_id,
                        "status": status, "resolved_at": resolved_at,
                        "auto_scored_forecasts": [],
                        "created_at": row[0]}

            outcome_id = args.get("id") or new_id("out")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, "
                "outcome_value, status, source, confidence, agent_id, model_id, "
                "environment, run_id, metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    outcome_id, instrument_id, resolved_at, outcome_label,
                    args.get("outcome_value"), status,
                    args.get("source", "manual"), args.get("confidence"),
                    seg["agent_id"], seg["model_id"], seg["environment"], seg["run_id"],
                    metadata_json, created_at, ctx.actor_id,
                ),
            )
            emit_event(
                uow, event_type="outcome.recorded",
                subject_kind="outcome", subject_id=outcome_id,
                payload=_payload(outcome_id),
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
            # Auto-scoring per scoring.md §6 / §5 hard invariant.
            if status == "resolved_final":
                auto_scored = _autoscore_pending_forecasts(
                    uow.conn,
                    instrument_id=instrument_id,
                    outcome_id=outcome_id,
                    outcome_label=outcome_label,
                    actor_id=ctx.actor_id,
                    created_at=created_at,
                )
                for score in auto_scored:
                    _emit_forecast_scored(
                        uow, score, actor_id=ctx.actor_id, ctx=ctx,
                        scored_at=created_at,
                    )
    finally:
        db.close()
    return {"id": outcome_id, "instrument_id": instrument_id, "status": status,
            "resolved_at": resolved_at, "auto_scored_forecasts": auto_scored,
            "created_at": created_at}



# -- source.add + source.attach_to_* ---------------------------------------

def _source_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            return _source_add_in_uow(args, ctx, uow)
    finally:
        db.close()


def _source_add_in_uow(args: dict[str, Any], ctx: ToolContext, uow: UnitOfWork) -> dict[str, Any]:
    """Create a source row using an existing transaction."""

    kind = require(args, "kind")
    reject_if_contains_secrets(args.get("title"), field="title")
    reject_if_contains_secrets(args.get("note"), field="note")
    reject_if_contains_secrets(args.get("excerpt"), field="excerpt")
    reject_if_contains_secrets(args.get("extracted_text"), field="extracted_text")
    reject_if_contains_secrets(args.get("summary"), field="summary")
    idempotency_key = args.get("idempotency_key")
    stance = args.get("stance", "neutral")
    storage_kind = args.get("storage_kind", "inline_text")
    redaction_status = args.get("redaction_status", "none")
    freshness_at = normalize_timestamp(args, "freshness_at")
    captured_at = normalize_timestamp(args, "captured_at")
    retrieved_at = normalize_timestamp(args, "retrieved_at")
    metadata_json = _store_metadata_json(args)
    seg = common_metadata(args)

    def _payload(sid: str) -> dict[str, Any]:
        return {
            "id": sid, "kind": kind, "ref": args.get("ref"),
            "title": args.get("title"), "note": args.get("note"),
            "stance": stance, "freshness_at": freshness_at,
            "content_hash": args.get("content_hash"),
            "captured_at": captured_at, "uri": args.get("uri"),
            "media_type": args.get("media_type"),
            "storage_kind": storage_kind,
            "retrieved_at": retrieved_at,
            "source_author": args.get("source_author"),
            "publisher": args.get("publisher"),
            "excerpt": args.get("excerpt"),
            "extracted_text": args.get("extracted_text"),
            "summary": args.get("summary"),
            "hash_algorithm": args.get("hash_algorithm"),
            "redaction_status": redaction_status,
            "license_or_terms_note": args.get("license_or_terms_note"),
            "agent_id": seg["agent_id"],
            "model_id": seg["model_id"],
            "environment": seg["environment"],
            "run_id": seg["run_id"],
            "metadata_json": metadata_json,
        }

    replay = check_idempotency_replay(
        uow, event_type="source.added",
        actor_id=ctx.actor_id, idempotency_key=idempotency_key,
    )
    if replay is not None:
        source_id = replay["id"]
        emit_event(
            uow, event_type="source.added",
            subject_kind="source", subject_id=source_id,
            payload=_payload(source_id),
            actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
        )
        row = uow.conn.execute(
            "SELECT created_at FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        return {"id": source_id, "kind": kind, "stance": stance,
                "created_at": row[0]}

    source_id = args.get("id") or new_id("src")
    created_at = now_iso()
    uow.execute(
        "INSERT INTO sources(id, kind, ref, title, note, stance, freshness_at, "
        "content_hash, captured_at, uri, media_type, storage_kind, retrieved_at, "
        "source_author, publisher, excerpt, extracted_text, summary, "
        "hash_algorithm, redaction_status, license_or_terms_note, agent_id, "
        "model_id, environment, run_id, metadata_json, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            source_id, kind, args.get("ref"), args.get("title"),
            args.get("note"), stance, freshness_at,
            args.get("content_hash"), captured_at, args.get("uri"),
            args.get("media_type"), storage_kind, retrieved_at,
            args.get("source_author"), args.get("publisher"),
            args.get("excerpt"), args.get("extracted_text"),
            args.get("summary"), args.get("hash_algorithm"),
            redaction_status, args.get("license_or_terms_note"),
            seg["agent_id"], seg["model_id"], seg["environment"], seg["run_id"],
            metadata_json, created_at, ctx.actor_id,
        ),
    )
    emit_event(
        uow, event_type="source.added",
        subject_kind="source", subject_id=source_id,
        payload=_payload(source_id),
        actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
    )
    return {"id": source_id, "kind": kind, "stance": stance,
            "created_at": created_at}


_SOURCE_ATTACH_TARGETS: dict[str, dict[str, Any]] = {
    "thesis": {
        "table": "theses",
        "tool": "source.attach_to_thesis",
        "json_schema": None,
        "example_key": "source.attach_to_thesis",
    },
    "decision": {
        "table": "decisions",
        "tool": "source.attach_to_decision",
        "json_schema": None,
        "example_key": "source.attach_to_decision",
    },
    "forecast": {
        "table": "forecasts",
        "tool": "source.attach_to_forecast",
        "json_schema": None,
        "example_key": "source.attach_to_forecast",
    },
    "memory_node": {
        "table": "memory_nodes",
        "tool": "source.attach_to_memory_node",
        "json_schema": None,
        "example_key": "source.attach_to_memory_node",
    },
}
"""Single source of truth for public source.attach_to_* target metadata.

Per bead trade-trace-l9q, each source.attach_to_<target> validates the
target row exists before writing the edge. The memory_node attacher
became functional with M3 (bead e86 + bead s3f). Bead trade-trace-4v31
keeps the public tool names separate while driving both validation and
registration from this mapping; no generic public source.attach endpoint
is registered.
"""


def _make_source_attacher(target_kind: str):
    """Build a `source.attach_to_<target>` handler. Edge type is derived from
    the source's `stance` column per PRD §4.5."""

    def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        source_id = require(args, "source_id")
        target_id = require(args, "target_id")
        idempotency_key = args.get("idempotency_key")
        metadata_json = _store_metadata_json(args)
        db = open_db_for_args(args)
        try:
            stance_row = db.connection.execute(
                "SELECT stance FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
            if stance_row is None:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"source {source_id!r} not found",
                    details={
                        "entity_kind": "source",
                        "source_id": source_id,
                    },
                )
            # Target validation per bead trade-trace-l9q: refuse to attach
            # a source to a row that does not exist. Without this guard the
            # edge would point to a phantom id and the agent would see a
            # successful write that produced an orphan edge.
            target_meta = _SOURCE_ATTACH_TARGETS.get(target_kind)
            if target_meta is None:
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    f"unsupported target_kind {target_kind!r}",
                    details={
                        "field": "target_kind",
                        "value": target_kind,
                        "allowed": sorted(_SOURCE_ATTACH_TARGETS),
                    },
                )
            target_table = target_meta["table"]
            target_row = db.connection.execute(
                f"SELECT 1 FROM {target_table} WHERE id = ?", (target_id,)
            ).fetchone()
            if target_row is None:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"{target_kind} {target_id!r} not found",
                    details={
                        "entity_kind": target_kind,
                        "target_id": target_id,
                    },
                )
            stance = stance_row[0]
            edge_type = stance if stance in ("supports", "contradicts") else "about"
            with UnitOfWork(db.connection) as uow:
                replay = check_idempotency_replay(
                    uow, event_type="source.attached",
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key,
                )
                if replay is not None:
                    edge_id = replay["id"]
                    emit_event(
                        uow, event_type="source.attached",
                        subject_kind="edge", subject_id=edge_id,
                        payload={
                            "id": edge_id, "source_id": source_id,
                            "target_kind": target_kind, "target_id": target_id,
                            "edge_type": edge_type,
                        },
                        actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                    )
                    row = uow.conn.execute(
                        "SELECT created_at FROM edges WHERE id = ?", (edge_id,)
                    ).fetchone()
                    return {"id": edge_id, "source_id": source_id,
                            "target_kind": target_kind, "target_id": target_id,
                            "edge_type": edge_type, "created_at": row[0]}

                edge_id = args.get("id") or new_id("edg")
                created_at = now_iso()
                uow.execute(
                    "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
                    "edge_type, metadata_json, created_at, actor_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        edge_id, "source", source_id, target_kind, target_id, edge_type,
                        metadata_json, created_at, ctx.actor_id,
                    ),
                )
                emit_event(
                    uow, event_type="source.attached",
                    subject_kind="edge", subject_id=edge_id,
                    payload={
                        "id": edge_id, "source_id": source_id,
                        "target_kind": target_kind, "target_id": target_id,
                        "edge_type": edge_type,
                    },
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                )
        finally:
            db.close()
        return {"id": edge_id, "source_id": source_id, "target_kind": target_kind,
                "target_id": target_id, "edge_type": edge_type, "created_at": created_at}

    return _handler


def _source_attach_to_memory_node_in_uow(args: dict[str, Any], ctx: ToolContext, uow: UnitOfWork) -> dict[str, Any]:
    """Attach a source to a memory_node using an existing transaction."""

    source_id = require(args, "source_id")
    target_id = require(args, "target_id")
    idempotency_key = args.get("idempotency_key")
    metadata_json = _store_metadata_json(args)
    stance_row = uow.conn.execute(
        "SELECT stance FROM sources WHERE id = ?", (source_id,),
    ).fetchone()
    if stance_row is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"source {source_id!r} not found",
            details={"entity_kind": "source", "source_id": source_id},
        )
    target_row = uow.conn.execute(
        "SELECT 1 FROM memory_nodes WHERE id = ?", (target_id,),
    ).fetchone()
    if target_row is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"memory_node {target_id!r} not found",
            details={"entity_kind": "memory_node", "target_id": target_id},
        )
    stance = stance_row[0]
    edge_type = stance if stance in ("supports", "contradicts") else "about"
    replay = check_idempotency_replay(
        uow, event_type="source.attached",
        actor_id=ctx.actor_id, idempotency_key=idempotency_key,
    )
    if replay is not None:
        edge_id = replay["id"]
        emit_event(
            uow, event_type="source.attached",
            subject_kind="edge", subject_id=edge_id,
            payload={
                "id": edge_id, "source_id": source_id,
                "target_kind": "memory_node", "target_id": target_id,
                "edge_type": edge_type,
            },
            actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
        )
        row = uow.conn.execute(
            "SELECT created_at FROM edges WHERE id = ?", (edge_id,),
        ).fetchone()
        return {"id": edge_id, "source_id": source_id, "target_kind": "memory_node",
                "target_id": target_id, "edge_type": edge_type, "created_at": row[0]}

    edge_id = args.get("id") or new_id("edg")
    created_at = now_iso()
    uow.execute(
        "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
        "edge_type, metadata_json, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (edge_id, "source", source_id, "memory_node", target_id, edge_type,
         metadata_json, created_at, ctx.actor_id),
    )
    emit_event(
        uow, event_type="source.attached",
        subject_kind="edge", subject_id=edge_id,
        payload={
            "id": edge_id, "source_id": source_id,
            "target_kind": "memory_node", "target_id": target_id,
            "edge_type": edge_type,
        },
        actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
    )
    return {"id": edge_id, "source_id": source_id, "target_kind": "memory_node",
            "target_id": target_id, "edge_type": edge_type, "created_at": created_at}


# -- resolve.pending ---------------------------------------------------------

def _resolve_pending(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """List forecasts past their resolution_at without a `resolved_final`
    outcome row. Deterministic ordering per PRD §4.4 / kyr acceptance:
    ORDER BY resolution_at ASC, forecast_id ASC."""

    limit = int(args.get("limit", 100))
    if limit < 1 or limit > 1000:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "limit must be between 1 and 1000",
            details={"field": "limit", "value": limit},
        )
    db = open_db_for_args(args)
    try:
        cur = db.connection.execute(
            """
            SELECT f.id, f.thesis_id, f.kind, f.resolution_at, t.instrument_id
            FROM forecasts f
            JOIN theses t ON t.id = f.thesis_id
            WHERE f.resolution_at IS NOT NULL
              AND f.scoring_state = 'pending'
              AND NOT EXISTS (
                SELECT 1 FROM outcomes o
                WHERE o.instrument_id = t.instrument_id
                  AND o.status = 'resolved_final'
              )
            ORDER BY f.resolution_at ASC, f.id ASC
            LIMIT ?
            """,
            (limit,),
        )
        items = [
            {
                "forecast_id": row[0],
                "thesis_id": row[1],
                "kind": row[2],
                "resolution_at": row[3],
                "instrument_id": row[4],
            }
            for row in cur.fetchall()
        ]
    finally:
        db.close()
    return {"items": items, "count": len(items), "truncated": len(items) == limit}


# -- registration ------------------------------------------------------------


# Hand-crafted JSON schema for decision.add per bead trade-trace-hsnz.
# Auto-derivation from example_minimal=actual_enter forced `quantity`/`price`
# as required, but the decision matrix marks them X (forbidden) for `watch`
# and `skip`. Required set here is the intersection across all matrix rows:
# every row has `instrument_id` R, and `type` discriminates the row, so
# `type`, `instrument_id`, and `idempotency_key` are the only schema-level
# required fields. The runtime decision matrix in `decision_matrix.py`
# enforces per-type R/X constraints uniformly and returns a typed
# VALIDATION_ERROR envelope on violation.
# Hand-crafted JSON schema for snapshot.add per agent-continuity Epic A.
# The runtime persists common run/session provenance fields on snapshots; the
# advertised schema must expose them even though they remain optional.
_SNAPSHOT_ADD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "instrument_id": {"type": "string"},
        "captured_at": {"type": "string"},
        "source": {"type": "string"},
        "source_url": {"type": "string"},
        "price": {"type": "number"},
        "bid": {"type": "number"},
        "ask": {"type": "number"},
        "mid": {"type": "number"},
        "spread": {"type": "number"},
        "volume": {"type": "number"},
        "open_interest": {"type": "number"},
        "implied_probability": {"type": "number"},
        "liquidity_depth_json": {"type": "object"},
        "agent_id": {"type": "string"},
        "model_id": {"type": "string"},
        "environment": {"type": "string"},
        "run_id": {"type": "string"},
        "metadata_json": {"type": "object"},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["instrument_id", "captured_at", "idempotency_key"],
    "description": "snapshot.add — append a caller-supplied local market/context snapshot; optional agent/model/environment/run fields persist as reporting dimensions only.",
}


# Hand-crafted JSON schema for source.add per bead trade-trace-2ya5.
# Storage migrations 003 pin `kind` to a 10-value enum and `stance` to a
# 3-value enum; the auto-derived schema only emitted the field types as
# strings, so an agent following `tool.schema --tool source.add` saw a
# valid-looking payload that storage then rejected with a raw SQLite
# CHECK constraint error. Surfacing the enums here lets the agent pick a
# valid value up-front.
_SOURCE_ADD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": [
                "url", "pdf", "image", "tweet", "news_article",
                "research_doc", "transcript", "chart_image", "note", "other",
            ],
        },
        "stance": {
            "type": "string",
            "enum": ["supports", "contradicts", "neutral"],
        },
        "uri": {"type": "string"},
        "title": {"type": "string"},
        "note": {"type": "string"},
        "ref": {"type": "string"},
        "freshness_at": {
            "type": "string",
            "description": (
                "ISO-8601 timestamp for when the evidence itself was current. "
                "report.source_quality stale_sources uses this field versus "
                "decision.created_at; set it when you want stale-evidence checks."
            ),
        },
        "content_hash": {"type": "string"},
        "captured_at": {"type": "string"},
        "media_type": {"type": "string"},
        "storage_kind": {
            "type": "string",
            "enum": ["url", "local_path", "inline_text", "external_ref"],
        },
        "retrieved_at": {
            "type": "string",
            "description": (
                "ISO-8601 timestamp for when this source was fetched/recorded as "
                "provenance. It does not drive report.source_quality stale_sources; "
                "use freshness_at for evidence freshness."
            ),
        },
        "source_author": {"type": "string"},
        "publisher": {"type": "string"},
        "excerpt": {"type": "string"},
        "extracted_text": {"type": "string"},
        "summary": {"type": "string"},
        "redaction_status": {"type": "string"},
        "agent_id": {"type": "string"},
        "model_id": {"type": "string"},
        "environment": {"type": "string"},
        "run_id": {"type": "string"},
        "metadata_json": {"type": "object"},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["kind", "idempotency_key"],
    "description": (
        "source.add — kind and stance use storage-pinned enums "
        "(persistence.md §5.2 / migration 003). Free-text fields "
        "(title/note/excerpt/extracted_text/summary) are scanned at "
        "write time for sensitive-shaped substrings per trade-trace-sy1. "
        "freshness_at is the evidence-current timestamp used by "
        "report.source_quality stale_sources; retrieved_at is retrieval/provenance "
        "time only."
    ),
}


_INSTRUMENT_ADD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "venue_id": {"type": "string"},
        "asset_class": {"type": "string"},
        "title": {"type": "string"},
        "external_id": {"type": "string"},
        "symbol": {"type": "string"},
        "currency_or_collateral": {"type": "string"},
        "expiration_or_resolution_at": {"type": "string"},
        "resolution_criteria_text": {"type": "string"},
        "contract_multiplier": {"type": "number"},
        "metadata_json": {"type": "object"},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["venue_id", "asset_class", "title", "idempotency_key"],
    "description": (
        "instrument.add — create an instrument. Optional audit/venue fields "
        "are accepted and persisted when provided."
    ),
}


_DECISION_MATRIX_CONTRACT = decision_matrix_contract()

_DECISION_ADD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": allowed_decision_types(),
            "description": "Decision discriminator. See x-decision-matrix for per-type required/optional/forbidden fields.",
        },
        "instrument_id": {"type": "string"},
        "thesis_id": {"type": "string"},
        "forecast_id": {"type": "string"},
        "snapshot_id": {"type": "string"},
        "side": {"type": "string"},
        "quantity": {"type": "number"},
        "price": {"type": "number"},
        "fees": {"type": "number"},
        "slippage": {"type": "number"},
        "reason": {"type": "string"},
        "review_by": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "metadata_json": {"type": "object"},
        "agent_id": {"type": "string"},
        "model_id": {"type": "string"},
        "environment": {"type": "string"},
        "run_id": {"type": "string"},
        "strategy_id": {"type": "string"},
        "position_id": {"type": "string"},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["type", "instrument_id", "idempotency_key"],
    "description": (
        "decision.add — runtime decision matrix in decision_matrix.py "
        "enforces per-`type` required/forbidden fields and returns a "
        "VALIDATION_ERROR envelope on violation. Use x-decision-matrix "
        "for per-type required/optional/forbidden fields. For `paper_enter`, "
        "the tool appends one linked position_events.open row, refreshes "
        "positions, and returns position_id/position_event_id; actual_* and "
        "paper_exit remain journal records only for projection purposes."
    ),
    "x-decision-matrix": _DECISION_MATRIX_CONTRACT,
    "x-material-non-action-taxonomy": material_non_action_taxonomy(),
    "x-decision-examples": {
        "skip": {
            "type": "skip",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "reason": "Spread too wide for planned edge.",
            "idempotency_key": "00000000-0000-4000-8000-000000000000",
        },
        "watch": {
            "type": "watch",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "reason": "Waiting for liquidity to improve.",
            "review_by": "2026-05-22T14:30:00Z",
            "idempotency_key": "00000000-0000-4000-8000-000000000000",
        },
        "actual_enter": {
            "type": "actual_enter",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "thesis_id": "th_THESIS_ID_HERE",
            "side": "yes",
            "quantity": 100,
            "price": 0.62,
            "idempotency_key": "00000000-0000-4000-8000-000000000000",
        },
        "actual_exit": {
            "type": "actual_exit",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "side": "yes",
            "quantity": 100,
            "price": 0.78,
            "idempotency_key": "00000000-0000-4000-8000-000000000000",
        },
    },
}


def register_ledger_tools(registry: ToolRegistry) -> None:
    """Register all M1 manual ledger / source / resolution write tools."""

    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    registry.register("venue.add", _venue_add, is_write=True, **_examples_for("venue.add"))
    registry.register(
        "instrument.add",
        _instrument_add,
        is_write=True,
        json_schema=_INSTRUMENT_ADD_SCHEMA,
        **_examples_for("instrument.add"),
    )
    registry.register(
        "snapshot.add",
        _snapshot_add,
        is_write=True,
        json_schema=_SNAPSHOT_ADD_SCHEMA,
        optional_keys=(
            "price",
            "source",
            "source_url",
            "bid",
            "ask",
            "mid",
            "spread",
            "volume",
            "open_interest",
            "implied_probability",
            "liquidity_depth_json",
            "agent_id",
            "model_id",
            "environment",
            "run_id",
            "metadata_json",
        ),
        **_examples_for("snapshot.add"),
    )
    registry.register("thesis.add", _thesis_add, is_write=True, **_examples_for("thesis.add"))
    registry.register("forecast.add", _forecast_add, is_write=True, **_examples_for("forecast.add"))
    registry.register("forecast.supersede", _forecast_supersede, is_write=True, **_examples_for("forecast.supersede"))
    registry.register(
        "decision.add",
        _decision_add,
        is_write=True,
        json_schema=_DECISION_ADD_SCHEMA,
        description=(
            "decision.add type choices: " + ", ".join(allowed_decision_types()) +
            ". Per-type required/optional/forbidden fields are exposed in "
            "tool.schema json_schema.x-decision-matrix."
        ),
        usage_summary="Record a trade decision against an instrument; choose type and include only fields allowed by the decision matrix.",
        examples=("tt decision add --instrument-id ins_... --type enter --side long --thesis-id th_... --idempotency-key <uuid>",),
        enum_notes={"type": "Allowed values and per-type field requirements live in json_schema.x-decision-matrix.", "side": "Use long/short only for directional decision types."},
        common_failures=("Missing a field required by the selected decision type.", "Providing a forbidden field for the selected decision type."),
        next_actions=("Inspect `tt tool schema --tool decision.add` before retrying validation failures.",),
        **_examples_for("decision.add"),
    )
    registry.register("outcome.add", _outcome_add, is_write=True, **_examples_for("outcome.add"))
    # resolve.record is an alias for outcome.add (PRD §4.4).
    registry.register("resolve.record", _outcome_add, is_write=True, **_examples_for("outcome.add"))
    registry.register("resolve.pending", _resolve_pending)
    registry.register("source.add", _source_add, is_write=True, json_schema=_SOURCE_ADD_SCHEMA, **_examples_for("source.add"))
    for target_kind, target_meta in _SOURCE_ATTACH_TARGETS.items():
        tool_name = target_meta["tool"]
        example_key = target_meta["example_key"]
        json_schema = target_meta["json_schema"]
        register_kwargs = {
            "is_write": True,
            **_examples_for(example_key),
        }
        if json_schema is not None:
            register_kwargs["json_schema"] = json_schema
        registry.register(
            tool_name,
            _make_source_attacher(target_kind),
            **register_kwargs,
        )
