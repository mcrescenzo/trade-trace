"""M4 playbook tools per bead trade-trace-fbq and PRD §4.3.

A playbook is a named, append-only, versioned procedural object. Each
version is anchored to a `provenance_reflection_node_id` — the
reflection that motivated the rule update — so the agent can trace
*why* a version exists from the rule lineage. Adherence is recorded
per `(decision, playbook_version, rule_node)` triple with one of four
status values (considered | followed | overridden | not_applicable).

The M4 surface is intentionally *advisory* per the bead acceptance:
nothing auto-rejects a decision because it violates a playbook rule.
The agent records adherence; reports surface aggregates; the human
(or upstream agent) makes the call.

Tools:
- `playbook.create(name, *, description?, status?)` — register a
  named playbook.
- `playbook.list()` — list every playbook.
- `playbook.show(playbook_id)` — one playbook + its version history.
- `playbook.list_versions(playbook_id)` — versions ordered ascending.
- `playbook.propose_version(playbook_id, provenance_reflection_node_id,
  *, parent_version_id?, description?)` — append a new version row.
- `playbook.adherence(playbook_id, *, strategy_id?)` — thin wrapper
  around report.playbook_adherence scoped to a single playbook.
- `decision.record_adherence(decision_id, playbook_version_id,
  rule_node_id, status, *, reason?)` — write one normalized row into
  `decision_playbook_rules` and emit the matching `playbook_rule.*`
  event.
"""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    db_for_args,
    emit_event,
    new_id,
    now_iso,
    reject_if_contains_secrets,
    require,
    store_metadata_json,
)
from trade_trace.tools.errors import ToolError

ADHERENCE_STATUSES = ("considered", "followed", "overridden", "not_applicable")

# Lifecycle status for the playbook row itself, symmetric with
# strategy.upsert's {active, archived} enum (trade-trace-47tp secondary).
# The DB column is unconstrained TEXT, so the tool layer is the only
# validation boundary; default to 'active' when omitted.
PLAYBOOK_STATUSES = ("active", "archived")
_DEFAULT_PLAYBOOK_STATUS = "active"


def _require_playbook(conn: Any, playbook_id: str) -> None:
    if conn.execute(
        "SELECT 1 FROM playbooks WHERE id = ?", (playbook_id,),
    ).fetchone() is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"playbook {playbook_id!r} not found",
            details={"entity_kind": "playbook", "playbook_id": playbook_id},
        )


def _require_decision(conn: Any, decision_id: str) -> None:
    if conn.execute(
        "SELECT 1 FROM decisions WHERE id = ?", (decision_id,),
    ).fetchone() is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"decision {decision_id!r} not found",
            details={"entity_kind": "decision", "decision_id": decision_id},
        )


def _require_playbook_version(conn: Any, playbook_version_id: str) -> None:
    if conn.execute(
        "SELECT 1 FROM playbook_versions WHERE id = ?",
        (playbook_version_id,),
    ).fetchone() is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"playbook_version {playbook_version_id!r} not found",
            details={
                "entity_kind": "playbook_version",
                "playbook_version_id": playbook_version_id,
            },
        )


def _require_reflection_node(conn: Any, reflection_node_id: str) -> None:
    ref_row = conn.execute(
        "SELECT node_type FROM memory_nodes WHERE id = ?",
        (reflection_node_id,),
    ).fetchone()
    if ref_row is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"reflection node {reflection_node_id!r} not found",
            details={
                "entity_kind": "memory_node",
                "memory_node_id": reflection_node_id,
            },
        )
    if ref_row[0] != "reflection":
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "provenance_reflection_node_id must reference a "
            f"memory_node with node_type='reflection'; got {ref_row[0]!r}",
            details={
                "field": "provenance_reflection_node_id",
                "memory_node_id": reflection_node_id,
                "actual_node_type": ref_row[0],
            },
        )


def _require_playbook_rule_node(conn: Any, rule_node_id: str) -> None:
    rule_row = conn.execute(
        "SELECT node_type FROM memory_nodes WHERE id = ?",
        (rule_node_id,),
    ).fetchone()
    if rule_row is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"rule node {rule_node_id!r} not found",
            details={"entity_kind": "memory_node", "memory_node_id": rule_node_id},
        )
    if rule_row[0] != "playbook_rule":
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "rule_node_id must reference a memory_node with "
            f"node_type='playbook_rule'; got {rule_row[0]!r}",
            details={
                "field": "rule_node_id",
                "memory_node_id": rule_node_id,
                "actual_node_type": rule_row[0],
            },
        )


def _schema(properties: dict[str, Any], *, required: list[str] | None = None, description: str = "") -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "description": description,
    }


# playbook.upsert (legacy playbook.create) had no explicit json_schema, so its
# MCP schema auto-derived from example_minimal and hid the `status` field
# entirely (example_rich was null) — asymmetric with strategy.upsert, which
# advertises its {active, archived} enum. This explicit schema mirrors the
# runtime: name + idempotency_key required, status enum-validated and defaulting
# to 'active' (trade-trace-47tp secondary).
_PLAYBOOK_CREATE_SCHEMA = _schema(
    {
        "name": {"type": "string", "description": "Unique playbook name; duplicate raises VALIDATION_ERROR with details.field='name'."},
        "description": {"type": "string", "description": "Optional free-text description; scanned for sensitive-shaped text."},
        "status": {"type": "string", "enum": list(PLAYBOOK_STATUSES), "description": "Lifecycle status; one of the documented enum. Defaults to 'active' when omitted."},
        "metadata_json": {"type": "object", "description": "Optional structured metadata."},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    required=["name", "idempotency_key"],
    description=(
        "Register a named playbook. Rules live in memory_nodes"
        "(node_type='playbook_rule') wired via playbook.propose_version, "
        "not on the playbook row itself."
    ),
)
_PLAYBOOK_LIST_SCHEMA = _schema(
    {"limit": {"type": "integer", "minimum": 1, "maximum": 1000}},
    description="Optional limit defaults to 100 and is capped at 1000.",
)
_PLAYBOOK_SHOW_SCHEMA = _schema(
    {"playbook_id": {"type": "string"}},
    required=["playbook_id"],
    description="Show one playbook and versions; NOT_FOUND on a bad playbook_id.",
)
_PLAYBOOK_LIST_VERSIONS_SCHEMA = _schema(
    {"playbook_id": {"type": "string"}},
    required=["playbook_id"],
    description="List versions for one playbook; NOT_FOUND on a bad playbook_id.",
)
_PLAYBOOK_PROPOSE_VERSION_SCHEMA = _schema(
    {
        "playbook_id": {"type": "string"},
        "provenance_reflection_node_id": {"type": "string"},
        "parent_version_id": {"type": "string"},
        "description": {"type": "string"},
        "metadata_json": {"type": "object"},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    required=["playbook_id", "provenance_reflection_node_id", "idempotency_key"],
    description=(
        "Append a version anchored to a reflection. Optional parent_version_id "
        "overrides the default prior-head lineage; description is scanned for "
        "sensitive-shaped text. Rule/rule_json/rules_json payloads are not accepted; "
        "create playbook_rule memory nodes separately."
    ),
)
_DECISION_RECORD_ADHERENCE_SCHEMA = _schema(
    {
        "decision_id": {"type": "string"},
        "playbook_version_id": {"type": "string"},
        "rule_node_id": {"type": "string"},
        "status": {"type": "string", "enum": list(ADHERENCE_STATUSES)},
        "reason": {"type": "string"},
        "metadata_json": {"type": "object"},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    required=["decision_id", "playbook_version_id", "rule_node_id", "status", "idempotency_key"],
    description=(
        "Record advisory playbook adherence. status must be one of considered, "
        "followed, overridden, not_applicable. rule_node_id must reference a "
        "memory_node with node_type='playbook_rule'. Use reason for override "
        "rationale; bad endpoints return typed NOT_FOUND/VALIDATION_ERROR."
    ),
)

# -- playbook.create
# -- playbook.create ----------------------------------------------


def _playbook_create(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    name = require(args, "name")
    description = args.get("description")
    # Per bead trade-trace-7j1l: scan the long-form playbook description
    # field. `name` is a short identifier and exempt.
    reject_if_contains_secrets(description, field="description")
    status = args.get("status", _DEFAULT_PLAYBOOK_STATUS)
    if status not in PLAYBOOK_STATUSES:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"status must be one of {PLAYBOOK_STATUSES}; got {status!r}",
            details={"field": "status", "value": status,
                     "allowed": list(PLAYBOOK_STATUSES)},
        )
    metadata_json = store_metadata_json(args)
    idempotency_key = args.get("idempotency_key")

    with db_for_args(args) as db:
        # Pre-check `name` uniqueness so the error surfaces with
        # `details.field='name'` instead of as a generic UNIQUE
        # constraint translation. Allow the idempotency-replay path
        # to bypass this when a key is supplied.
        existing = db.connection.execute(
            "SELECT id FROM playbooks WHERE name = ?", (name,),
        ).fetchone()
        if existing is not None and idempotency_key is None:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"playbook name {name!r} is already taken",
                details={
                    "field": "name", "value": name,
                    "existing_playbook_id": existing[0],
                },
            )
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="playbook.created",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                playbook_id = replay["id"]
                emit_event(
                    uow, event_type="playbook.created",
                    subject_kind="playbook", subject_id=playbook_id,
                    payload=replay,
                    actor_id=ctx.actor_id,
                    idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT name, description, status, created_at "
                    "FROM playbooks WHERE id = ?", (playbook_id,),
                ).fetchone()
                return {
                    "id": playbook_id, "name": row[0],
                    "description": row[1], "status": row[2],
                    "created_at": row[3],
                }

            # Concurrent-write guard: re-check name uniqueness inside
            # the transaction.
            collision = uow.execute(
                "SELECT id FROM playbooks WHERE name = ?", (name,),
            ).fetchone()
            if collision is not None:
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    f"playbook name {name!r} is already taken",
                    details={
                        "field": "name", "value": name,
                        "existing_playbook_id": collision[0],
                    },
                )

            playbook_id = args.get("id") or new_id("pbk")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO playbooks(id, name, description, status, "
                "metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (playbook_id, name, description, status, metadata_json,
                 created_at, ctx.actor_id),
            )
            emit_event(
                uow, event_type="playbook.created",
                subject_kind="playbook", subject_id=playbook_id,
                payload={
                    "id": playbook_id, "name": name,
                    "description": description, "status": status,
                    "metadata_json": metadata_json,
                },
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
    return {
        "id": playbook_id, "name": name, "description": description,
        "status": status, "created_at": created_at,
    }


# -- playbook.list -------------------------------------------------


def _playbook_list(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    limit = int(args.get("limit", 100))
    if limit < 1 or limit > 1000:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "limit must be in [1, 1000]",
            details={"field": "limit", "value": limit},
        )
    with db_for_args(args) as db:
        rows = db.connection.execute(
            "SELECT id, name, description, status, created_at "
            "FROM playbooks ORDER BY name LIMIT ?", (limit,),
        ).fetchall()
    items = [
        {"id": r[0], "name": r[1], "description": r[2],
         "status": r[3], "created_at": r[4]}
        for r in rows
    ]
    return {"items": items, "count": len(items), "truncated": len(items) == limit}


# -- playbook.show -------------------------------------------------


def _playbook_rule_guidance(*, has_rules: bool) -> str:
    if has_rules:
        return (
            "Linked playbook_rule nodes are discoverable below. Next: use "
            "decision.record_adherence with this playbook_version_id and a "
            "rule_node_id when evaluating a decision; use memory.recall to "
            "retrieve broader playbook_rule context."
        )
    return (
        "No playbook_rule nodes are linked to this version yet. Next: use "
        "memory.retain(node_type='playbook_rule') to create rule memory, "
        "then decision.record_adherence with playbook_version_id and "
        "rule_node_id to establish the existing read-side linkage."
    )


def _rule_summaries_by_version(conn: Any, version_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not version_ids:
        return {}
    placeholders = ",".join("?" for _ in version_ids)
    rows = conn.execute(
        "SELECT DISTINCT dpr.playbook_version_id, mn.id, mn.title, mn.body "
        "FROM decision_playbook_rules dpr "
        "JOIN memory_nodes mn ON mn.id = dpr.rule_node_id "
        f"WHERE dpr.playbook_version_id IN ({placeholders}) "
        "AND mn.node_type = 'playbook_rule' "
        "ORDER BY dpr.playbook_version_id, mn.created_at, mn.id",
        tuple(version_ids),
    ).fetchall()
    summaries: dict[str, list[dict[str, Any]]] = {version_id: [] for version_id in version_ids}
    for row in rows:
        summaries.setdefault(row[0], []).append({
            "id": row[1],
            "title": row[2],
            "body": row[3],
        })
    return summaries


def _enrich_version(row: Any, rule_summaries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    summaries = rule_summaries or []
    return {
        "id": row[0], "version": row[1], "parent_version_id": row[2],
        "provenance_reflection_node_id": row[3], "description": row[4],
        "created_at": row[5],
        "playbook_rule_summaries": summaries,
        "playbook_rule_count": len(summaries),
        "next_call_guidance": _playbook_rule_guidance(has_rules=bool(summaries)),
    }


def _empty_rule_discoverability_fields() -> dict[str, Any]:
    return {
        "playbook_rule_summaries": [],
        "playbook_rule_count": 0,
        "next_call_guidance": _playbook_rule_guidance(has_rules=False),
    }


def _playbook_show(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    playbook_id = require(args, "playbook_id")
    with db_for_args(args) as db:
        row = db.connection.execute(
            "SELECT id, name, description, status, created_at "
            "FROM playbooks WHERE id = ?", (playbook_id,),
        ).fetchone()
        if row is None:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                f"playbook {playbook_id!r} not found",
                details={"entity_kind": "playbook",
                         "playbook_id": playbook_id},
            )
        versions = db.connection.execute(
            "SELECT id, version, parent_version_id, "
            "provenance_reflection_node_id, description, created_at "
            "FROM playbook_versions WHERE playbook_id = ? "
            "ORDER BY version", (playbook_id,),
        ).fetchall()
        rules_by_version = _rule_summaries_by_version(
            db.connection, [v[0] for v in versions],
        )
    return {
        "id": row[0], "name": row[1], "description": row[2],
        "status": row[3], "created_at": row[4],
        "versions": [_enrich_version(v, rules_by_version.get(v[0], [])) for v in versions],
    }


# -- playbook.list_versions ----------------------------------------


def _playbook_list_versions(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    playbook_id = require(args, "playbook_id")
    with db_for_args(args) as db:
        # Validate playbook exists.
        row = db.connection.execute(
            "SELECT 1 FROM playbooks WHERE id = ?", (playbook_id,),
        ).fetchone()
        if row is None:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                f"playbook {playbook_id!r} not found",
                details={"entity_kind": "playbook",
                         "playbook_id": playbook_id},
            )
        rows = db.connection.execute(
            "SELECT id, version, parent_version_id, "
            "provenance_reflection_node_id, description, created_at "
            "FROM playbook_versions WHERE playbook_id = ? "
            "ORDER BY version", (playbook_id,),
        ).fetchall()
        rules_by_version = _rule_summaries_by_version(
            db.connection, [r[0] for r in rows],
        )
    items = [_enrich_version(r, rules_by_version.get(r[0], [])) for r in rows]
    return {"items": items, "count": len(items)}


# -- playbook.propose_version --------------------------------------


_PLAYBOOK_PROPOSE_VERSION_ALLOWED_ARGS = frozenset({
    "playbook_id",
    "provenance_reflection_node_id",
    "description",
    "metadata_json",
    # Internal replay support for journal import/export. The public tool
    # schema does not advertise this; live callers normally let the runtime
    # auto-increment the version number.
    "version",
    "idempotency_key",
    "parent_version_id",
    "id",
    # Transport/test controls consumed by the shared dispatcher/helpers.
    "home",
    "confirm",
    "_confirm",
    "_dry_run",
    "_allow_no_idempotency",
})


def _reject_unknown_propose_version_args(args: dict[str, Any]) -> None:
    unknown_fields = sorted(
        key for key in args if key not in _PLAYBOOK_PROPOSE_VERSION_ALLOWED_ARGS
    )
    if unknown_fields:
        details: dict[str, Any] = {"unknown_fields": unknown_fields}
        if len(unknown_fields) == 1:
            details["field"] = unknown_fields[0]
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "playbook.propose_version received unsupported field(s): "
            + ", ".join(unknown_fields),
            details=details,
        )


def _playbook_propose_version(
    args: dict[str, Any], ctx: ToolContext,
) -> dict[str, Any]:
    """Append a new playbook version row. Required:
    `provenance_reflection_node_id` — the reflection that motivated the
    rule update. The version number auto-increments (max + 1) inside the
    transaction; `parent_version_id` defaults to the prior version (if
    any) so the lineage chain stays explicit.
    """

    _reject_unknown_propose_version_args(args)

    playbook_id = require(args, "playbook_id")
    reflection_node_id = require(args, "provenance_reflection_node_id")
    description = args.get("description")
    # Per bead trade-trace-7j1l: scan version description (long-form
    # free-text). The reflection_node_id is a reference, not free text.
    reject_if_contains_secrets(description, field="description")
    metadata_json = store_metadata_json(args)
    idempotency_key = args.get("idempotency_key")

    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            _require_playbook(uow.conn, playbook_id)
            _require_reflection_node(uow.conn, reflection_node_id)

            replay = check_idempotency_replay(
                uow, event_type="playbook.proposed_version",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                version_id = replay["id"]
                emit_event(
                    uow, event_type="playbook.proposed_version",
                    subject_kind="playbook_version",
                    subject_id=version_id,
                    payload=replay,
                    actor_id=ctx.actor_id,
                    idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT version, parent_version_id, description, "
                    "created_at FROM playbook_versions WHERE id = ?",
                    (version_id,),
                ).fetchone()
                return {
                    "id": version_id, "playbook_id": playbook_id,
                    "version": row[0], "parent_version_id": row[1],
                    "provenance_reflection_node_id": reflection_node_id,
                    "description": row[2], "created_at": row[3],
                    **_empty_rule_discoverability_fields(),
                }

            # Auto-increment version number; auto-link parent.
            max_row = uow.conn.execute(
                "SELECT id, version FROM playbook_versions "
                "WHERE playbook_id = ? ORDER BY version DESC LIMIT 1",
                (playbook_id,),
            ).fetchone()
            if args.get("version") is not None:
                try:
                    next_version = int(args["version"])
                except (TypeError, ValueError):
                    raise ToolError(
                        ErrorCode.VALIDATION_ERROR,
                        "version must be an integer when provided",
                        details={"field": "version", "value": args.get("version")},
                    ) from None
                if next_version < 1:
                    raise ToolError(
                        ErrorCode.VALIDATION_ERROR,
                        "version must be >= 1 when provided",
                        details={"field": "version", "value": args.get("version")},
                    )
            elif max_row is None:
                next_version = 1
                parent_version_id = args.get("parent_version_id")
            else:
                next_version = max_row[1] + 1
                parent_version_id = args.get("parent_version_id") or max_row[0]

            if args.get("version") is not None:
                parent_version_id = args.get("parent_version_id") or (max_row[0] if max_row is not None else None)

            version_id = args.get("id") or new_id("pbv")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO playbook_versions(id, playbook_id, version, "
                "parent_version_id, provenance_reflection_node_id, "
                "description, metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (version_id, playbook_id, next_version, parent_version_id,
                 reflection_node_id, description, metadata_json,
                 created_at, ctx.actor_id),
            )
            emit_event(
                uow, event_type="playbook.proposed_version",
                subject_kind="playbook_version", subject_id=version_id,
                payload={
                    "id": version_id,
                    "playbook_id": playbook_id,
                    "version": next_version,
                    "parent_version_id": parent_version_id,
                    "provenance_reflection_node_id": reflection_node_id,
                    "description": description,
                    "metadata_json": metadata_json,
                },
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
    return {
        "id": version_id, "playbook_id": playbook_id,
        "version": next_version, "parent_version_id": parent_version_id,
        "provenance_reflection_node_id": reflection_node_id,
        "description": description, "created_at": created_at,
        **_empty_rule_discoverability_fields(),
    }


# -- decision.record_adherence -------------------------------------


def _decision_record_adherence(
    args: dict[str, Any], ctx: ToolContext,
) -> dict[str, Any]:
    """Append one `decision_playbook_rules` row + emit the matching
    `playbook_rule.<status>` event. The rule_node_id MUST reference a
    memory_nodes row with node_type='playbook_rule'; the tool layer
    validates this since SQLite cannot enforce the node_type subset."""

    decision_id = require(args, "decision_id")
    playbook_version_id = require(args, "playbook_version_id")
    rule_node_id = require(args, "rule_node_id")
    status = require(args, "status")
    reason = args.get("reason")
    # Per bead trade-trace-7j1l: adherence `reason` is long-form free
    # text (the override justification); scan it for credentials.
    reject_if_contains_secrets(reason, field="reason")
    idempotency_key = args.get("idempotency_key")

    if status not in ADHERENCE_STATUSES:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"status must be one of {ADHERENCE_STATUSES}; got {status!r}",
            details={"field": "status", "value": status,
                     "allowed": list(ADHERENCE_STATUSES)},
        )
    metadata_json = store_metadata_json(args)

    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            _require_decision(uow.conn, decision_id)
            _require_playbook_version(uow.conn, playbook_version_id)
            _require_playbook_rule_node(uow.conn, rule_node_id)

            event_type = (
                "playbook_rule.overridden" if status == "overridden"
                else "playbook_rule.followed"
            )
            replay = check_idempotency_replay(
                uow, event_type=event_type,
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                adherence_id = replay["id"]
                emit_event(
                    uow, event_type=event_type,
                    subject_kind="decision_playbook_rule",
                    subject_id=adherence_id,
                    payload=replay,
                    actor_id=ctx.actor_id,
                    idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT created_at FROM decision_playbook_rules "
                    "WHERE id = ?", (adherence_id,),
                ).fetchone()
                return {
                    "id": adherence_id, "decision_id": decision_id,
                    "playbook_version_id": playbook_version_id,
                    "rule_node_id": rule_node_id, "status": status,
                    "reason": reason, "created_at": row[0],
                }

            adherence_id = args.get("id") or new_id("adh")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO decision_playbook_rules(id, decision_id, "
                "playbook_version_id, rule_node_id, status, reason, "
                "metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (adherence_id, decision_id, playbook_version_id,
                 rule_node_id, status, reason, metadata_json,
                 created_at, ctx.actor_id),
            )
            emit_event(
                uow, event_type=event_type,
                subject_kind="decision_playbook_rule",
                subject_id=adherence_id,
                payload={
                    "id": adherence_id,
                    "decision_id": decision_id,
                    "playbook_version_id": playbook_version_id,
                    "rule_node_id": rule_node_id,
                    "status": status,
                    "reason": reason,
                },
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
    return {
        "id": adherence_id, "decision_id": decision_id,
        "playbook_version_id": playbook_version_id,
        "rule_node_id": rule_node_id, "status": status,
        "reason": reason, "created_at": created_at,
    }


# -- playbook.adherence (thin wrapper around report.playbook_adherence)


def _playbook_adherence(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Thin wrapper that scopes report.playbook_adherence to a single
    playbook (all versions of it). Optional `strategy_id` further
    narrows the adherence rows by the linked decision's strategy."""

    from trade_trace.reports.playbook_adherence import report_playbook_adherence

    playbook_id = require(args, "playbook_id")
    strategy_id = args.get("strategy_id")
    with db_for_args(args) as db:
        # Confirm the playbook exists so the report doesn't silently
        # return zero rows for a typo.
        _require_playbook(db.connection, playbook_id)
        return report_playbook_adherence(
            db.connection,
            playbook_id=playbook_id,
            strategy_id=strategy_id,
        )


# -- registration --------------------------------------------------


def register_playbook_tools(registry: ToolRegistry) -> None:
    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    registry.register(
        "playbook.create",
        _playbook_create,
        is_write=True,
        **_examples_for("playbook.create"),
        description=(
            "Register a named playbook. `name` is unique; duplicate "
            "raises VALIDATION_ERROR with details.field='name'. Optional "
            "`status` is enum-validated against {active, archived} and "
            "defaults to 'active'. The row carries no rules of its own — "
            "rules live in memory_nodes(node_type='playbook_rule') and are "
            "wired to the playbook via versions (playbook.propose_version)."
        ),
        json_schema=_PLAYBOOK_CREATE_SCHEMA,
    )
    registry.register(
        "playbook.list",
        _playbook_list,
        description="List every playbook. Sorted by name.",
        json_schema=_PLAYBOOK_LIST_SCHEMA
    )
    registry.register(
        "playbook.show",
        _playbook_show,
        description=(
            "Return one playbook row plus its full version history "
            "(ordered ascending). NOT_FOUND on bad playbook_id."
        ),
        json_schema=_PLAYBOOK_SHOW_SCHEMA
    )
    registry.register(
        "playbook.list_versions",
        _playbook_list_versions,
        description=(
            "Return versions for a playbook in ascending order. Used by "
            "an agent inspecting the rule lineage independently of "
            "playbook.show."
        ),
        json_schema=_PLAYBOOK_LIST_VERSIONS_SCHEMA
    )
    registry.register(
        "playbook.propose_version",
        _playbook_propose_version,
        is_write=True,
        **_examples_for("playbook.propose_version"),
        description=(
            "Append a new playbook_versions row anchored to a reflection "
            "node (provenance_reflection_node_id, required). The version "
            "number auto-increments; parent_version_id defaults to the "
            "prior head. Emits playbook.proposed_version event."
        ),
        json_schema=_PLAYBOOK_PROPOSE_VERSION_SCHEMA,
        usage_summary="Append the next playbook version using a reflection node as provenance; parent defaults to current head.",
        examples=("tt playbook propose_version --playbook-id pb_... --provenance-reflection-node-id mem_... --idempotency-key <uuid>",),
        common_failures=("provenance_reflection_node_id must reference an existing reflection memory node.",),
        next_actions=("Run playbook.show or playbook.list_versions to inspect lineage before proposing another version.",),
    )
    registry.register(
        "playbook.adherence",
        _playbook_adherence,
        description=(
            "Scoped wrapper around report.playbook_adherence: returns the "
            "adherence panel narrowed to a single playbook (all versions). "
            "Optional strategy_id filter further narrows by decision "
            "strategy_id."
        ),
        example_minimal={"playbook_id": "pb_example", "strategy_id": "strat_example"},
        optional_keys=("strategy_id",),
    )
    registry.register(
        "decision.record_adherence",
        _decision_record_adherence,
        is_write=True,
        **_examples_for("decision.record_adherence"),
        description=(
            "Record one normalized adherence row per "
            "(decision, playbook_version, rule_node). status ∈ "
            "{considered, followed, overridden, not_applicable}. "
            "Emits playbook_rule.overridden when status='overridden', "
            "playbook_rule.followed for every other status. Advisory only "
            "— no auto-rejection of the decision."
        ),
        json_schema=_DECISION_RECORD_ADHERENCE_SCHEMA
    )
