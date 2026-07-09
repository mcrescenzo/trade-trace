"""`source.add` + `source.attach_to_*` handlers and registration.

Extracted from `tools/ledger/__init__.py` per bead trade-trace-36ui.
Owns the public source-attach surface: a single `_SOURCE_ATTACH_TARGETS`
table drives both per-target row-existence validation (bead
trade-trace-l9q) and the registration block, so the supported
`source.attach_to_<target>` tool names stay in lockstep with the
validator. The memory_node attacher also exposes an in-UoW variant used
by the memory.add pipeline.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    common_metadata,
    db_for_args,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    reject_if_contains_secrets,
    require,
    store_metadata_json,
)
from trade_trace.tools.errors import ToolError
from trade_trace.tools.ledger._shared import examples_for

SOURCE_STANCES = (
    "supports", "contradicts", "neutral", "context", "resolution_rule",
    "official_source", "stale", "missing", "redacted", "sensitive",
)
EDGE_STANCE_TYPES = {"supports", "contradicts"}
REDACTING_STATUSES = {"redacted", "sensitive"}
REDACTING_STANCES = {"redacted", "sensitive"}


def _metadata_with_evidence_stance(raw: str | None, stance: str) -> str:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    parsed.setdefault("source_quality_code", f"evidence_stance.{stance}")
    parsed["evidence_stance"] = stance
    return json.dumps(parsed, sort_keys=True)


def _source_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            return _source_add_in_uow(args, ctx, uow)


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
    text_is_redacted = redaction_status in REDACTING_STATUSES or stance in REDACTING_STANCES
    excerpt = None if text_is_redacted else args.get("excerpt")
    extracted_text = None if text_is_redacted else args.get("extracted_text")
    summary = None if text_is_redacted else args.get("summary")
    metadata_json = store_metadata_json(args)
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
            "excerpt": excerpt,
            "extracted_text": extracted_text,
            "summary": summary,
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
            excerpt, extracted_text,
            summary, args.get("hash_algorithm"),
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


def _inline_source_object(
    conn: sqlite3.Connection, source_id: str, edge_type: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, kind, title, uri, ref, stance, captured_at, freshness_at,
               content_hash, redaction_status, metadata_json, publisher
        FROM sources
        WHERE id = ?
        """,
        (source_id,),
    ).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, f"source {source_id!r} not found")
    (
        s_id, kind, title, uri, ref, stance, captured_at, freshness_at,
        content_hash, redaction_status, metadata_json, publisher,
    ) = row
    try:
        meta = json.loads(metadata_json or "{}")
    except json.JSONDecodeError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    inline = {
        "id": s_id,
        "kind": kind,
        "title": title,
        "url": uri or ref,
        "uri": uri,
        "ref": ref,
        "stance": stance,
        "edge_type": edge_type,
        "captured_at": captured_at,
        "freshness_at": freshness_at,
        "hash": content_hash,
        "content_hash": content_hash,
        "redaction_status": redaction_status,
    }
    if publisher is not None:
        inline["publisher"] = publisher
    for key in ("source_author",):
        if key in meta and key not in inline:
            inline[key] = meta[key]
    return {k: v for k, v in inline.items() if v is not None}


def _metadata_with_appended_source(raw: str | None, source: dict[str, Any]) -> str:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    existing = parsed.get("sources")
    if not isinstance(existing, list):
        existing = []
    source_id = source.get("id")
    if source_id is not None and any(isinstance(s, dict) and s.get("id") == source_id for s in existing):
        parsed["sources"] = existing
        return json.dumps(parsed, sort_keys=True)
    parsed["sources"] = [*existing, source]
    return json.dumps(parsed, sort_keys=True)


def _append_inline_source_to_target(
    conn: sqlite3.Connection,
    target_kind: str,
    target_id: str,
    source: dict[str, Any],
) -> None:
    if target_kind not in _SOURCE_ATTACH_TARGETS:
        return
    table = _SOURCE_ATTACH_TARGETS[target_kind]["table"]
    trigger = f"trg_{table}_no_update"
    if table == "memory_nodes":
        message = "append-only invariant: UPDATE on memory_nodes is forbidden; write a new versioned node + supersedes edge"
    else:
        message = f"append-only invariant: UPDATE on {table} is forbidden; use a supersedes edge to record a correction (persistence.md §8)"
    row = conn.execute(f"SELECT metadata_json FROM {table} WHERE id = ?", (target_id,)).fetchone()
    if row is None:
        return
    new_metadata = _metadata_with_appended_source(row[0], source)
    conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    try:
        conn.execute(f"UPDATE {table} SET metadata_json = ? WHERE id = ?", (new_metadata, target_id))
    finally:
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {trigger}
            BEFORE UPDATE ON {table}
            BEGIN
                SELECT RAISE(ABORT, '{message}');
            END
            """
        )


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
    "outcome": {
        "table": "outcomes",
        "tool": "source.attach_to_outcome",
        "json_schema": None,
        "example_key": "source.attach_to_outcome",
    },
    "snapshot": {
        "table": "snapshots",
        "tool": "source.attach_to_snapshot",
        "json_schema": None,
        "example_key": "source.attach_to_snapshot",
    },
    "instrument": {
        "table": "instruments",
        "tool": "source.attach_to_instrument",
        "json_schema": None,
        "example_key": "source.attach_to_instrument",
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
        with db_for_args(args) as db:
            with UnitOfWork(db.connection) as uow:
                return _source_attach_in_uow(args, ctx, uow, target_kind=target_kind)

    return _handler


def _source_attach_in_uow(
    args: dict[str, Any], ctx: ToolContext, uow: UnitOfWork, *, target_kind: str,
) -> dict[str, Any]:
    """Attach a source to a supported target using an existing transaction."""

    source_id = require(args, "source_id")
    target_id = require(args, "target_id")
    idempotency_key = args.get("idempotency_key")
    metadata_json = store_metadata_json(args)
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
    stance_row = uow.conn.execute(
        "SELECT stance FROM sources WHERE id = ?", (source_id,),
    ).fetchone()
    if stance_row is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"source {source_id!r} not found",
            details={"entity_kind": "source", "source_id": source_id},
        )
    # Target validation per bead trade-trace-l9q: refuse to attach a source to
    # a row that does not exist. Without this guard the edge would point to a
    # phantom id and the agent would see a successful write that produced an
    # orphan edge.
    target_table = target_meta["table"]
    target_row = uow.conn.execute(
        f"SELECT 1 FROM {target_table} WHERE id = ?", (target_id,),
    ).fetchone()
    if target_row is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"{target_kind} {target_id!r} not found",
            details={"entity_kind": target_kind, "target_id": target_id},
        )
    stance = stance_row[0]
    edge_type = stance if stance in EDGE_STANCE_TYPES else "about"
    edge_metadata = _metadata_with_evidence_stance(metadata_json, stance)
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
                "edge_type": edge_type, "evidence_stance": stance,
            },
            actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
        )
        row = uow.conn.execute(
            "SELECT created_at FROM edges WHERE id = ?", (edge_id,),
        ).fetchone()
        return {"id": edge_id, "source_id": source_id, "target_kind": target_kind,
                "target_id": target_id, "edge_type": edge_type,
                "evidence_stance": stance, "created_at": row[0]}

    edge_id = args.get("id") or new_id("edg")
    created_at = now_iso()
    uow.execute(
        "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
        "edge_type, metadata_json, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (edge_id, "source", source_id, target_kind, target_id, edge_type,
         edge_metadata, created_at, ctx.actor_id),
    )
    _append_inline_source_to_target(
        uow.conn, target_kind, target_id,
        _inline_source_object(uow.conn, source_id, edge_type),
    )
    emit_event(
        uow, event_type="source.attached",
        subject_kind="edge", subject_id=edge_id,
        payload={
            "id": edge_id, "source_id": source_id,
            "target_kind": target_kind, "target_id": target_id,
            "edge_type": edge_type, "evidence_stance": stance,
        },
        actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
    )
    return {"id": edge_id, "source_id": source_id, "target_kind": target_kind,
            "target_id": target_id, "edge_type": edge_type,
            "evidence_stance": stance, "created_at": created_at}


def _source_attach_to_memory_node_in_uow(args: dict[str, Any], ctx: ToolContext, uow: UnitOfWork) -> dict[str, Any]:
    """Attach a source to a memory_node using an existing transaction."""

    return _source_attach_in_uow(args, ctx, uow, target_kind="memory_node")


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
            "enum": list(SOURCE_STANCES),
        },
        "uri": {"type": "string"},
        "title": {"type": "string"},
        "note": {"type": "string"},
        "ref": {"type": "string"},
        "freshness_at": {
            "type": "string",
            "description": (
                "ISO-8601 timestamp for when the evidence itself was current. "
                "source-quality stale_sources diagnostics use this field versus "
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
                "provenance. It does not drive source-quality stale_sources; "
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
        "(persistence.md §5.2; stance expanded by migration 017). Free-text fields "
        "(title/note/excerpt/extracted_text/summary) are scanned at "
        "write time for sensitive-shaped substrings per trade-trace-sy1. "
        "freshness_at is the evidence-current timestamp used by "
            "source-quality stale_sources; retrieved_at is retrieval/provenance "
        "time only."
    ),
}


def register_source_tools(registry: ToolRegistry) -> None:
    """Register `source.add` and every `source.attach_to_<target>` tool."""

    registry.register(
        "source.add", _source_add, is_write=True,
        json_schema=_SOURCE_ADD_SCHEMA, **examples_for("source.add"),
    )
    for target_kind, target_meta in _SOURCE_ATTACH_TARGETS.items():
        tool_name = target_meta["tool"]
        example_key = target_meta["example_key"]
        json_schema = target_meta["json_schema"]
        register_kwargs = {
            "is_write": True,
            **examples_for(example_key),
        }
        if json_schema is not None:
            register_kwargs["json_schema"] = json_schema
        registry.register(
            tool_name,
            _make_source_attacher(target_kind),
            **register_kwargs,
        )
