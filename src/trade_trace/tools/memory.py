"""M3 memory graph tools per bead trade-trace-e86 and memory-layer.md.

Surfaces: `memory.retain`, `memory.reflect`, `memory.link`, `memory.recall`.

The memory layer turns the journal into a graph the agent can think with:

- `retain` writes a typed node (observation, reflection, playbook_rule) with
  bi-temporal validity and optional importance/decay overrides.
- `reflect` is the safe path for the most common case — a retrospective
  reflection bound to a row in the journal. It writes the reflection AND
  the `about` edge in one transaction so reflections can never end up as
  orphan prose (per the bead's runnable invariant).
- `link` writes an explicit typed edge between two memory_node or ledger
  endpoints with kind validation.
- `recall` ranks nodes by a combination of BM25 (via FTS5), temporal
  decay, and graph proximity, all behind a bi-temporal `as_of` filter,
  then logs a `memory_recall_events` row that the rebuildable
  `memory_node_stats` projection consumes.

The retrieval-constants (k_rrf=60, importance_boost slope, supersession
discount=0.25) live in `trade_trace.memory.constants` so the tem bead can
own a single editable surface. No embeddings code lives here; the
embeddings opt-in path is the subject of bead ubp.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

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
from trade_trace.tools.errors import ToolError

# -- retrieval constants (locked per bead tem) ----------------------

K_RRF: Final[int] = 60
"""Reciprocal-rank-fusion constant — RRF score for rank r is `1/(K_RRF + r)`."""

IMPORTANCE_BOOST_SLOPE: Final[float] = 0.05
"""Per-step linear boost: `1.0 + (importance - 5) * IMPORTANCE_BOOST_SLOPE`.
importance=10 → 1.25; importance=1 → 0.80."""

SUPERSESSION_DISCOUNT: Final[float] = 0.25
"""Multiplier applied to nodes that have been superseded but not invalidated."""

NODE_TYPES: Final[tuple[str, ...]] = ("observation", "reflection", "playbook_rule")

POLICY_CANDIDATE_STATUSES: Final[tuple[str, ...]] = (
    "raw_reflection",
    "candidate_policy",
    "quarantined",
    "needs_more_evidence",
    "rejected",
    "promoted_to_playbook",
    "superseded",
)

EDGE_TYPES: Final[tuple[str, ...]] = (
    "about", "supports", "contradicts", "supersedes",
    "derived_from", "violates", "follows",
)

VALID_MEMORY_ENDPOINTS: Final[tuple[str, ...]] = (
    "memory_node", "signal", "strategy",
    "decision", "thesis", "forecast", "outcome", "snapshot",
    "instrument", "venue", "source", "review", "playbook_version",
)
"""Endpoint kinds for memory edges. Matches the edges table CHECK
constraint; `memory.link` validates the target row exists before writing."""


def _parse_memory_meta_json_object(
    value: Any,
    *,
    include_value_type_detail: bool = True,
) -> dict[str, Any]:
    """Normalize memory-node ``meta_json`` to an object.

    This helper is intentionally memory-local: strategy/playbook surfaces
    have distinct ``metadata_json`` behavior and must not share this path.
    ``include_value_type_detail`` preserves legacy caller-specific error
    details for non-object values.
    """

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "meta_json must be valid JSON when supplied as a string",
                details={"field": "meta_json", "reason": "invalid_json"},
            ) from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        details = {"field": "meta_json"}
        if include_value_type_detail:
            details["value_type"] = type(value).__name__
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "meta_json must decode to an object",
            details=details,
        )
    return value


def _validate_policy_candidate_meta(meta_json: dict[str, Any], *, node_type: str) -> None:
    """Validate optional reflection policy-candidate lifecycle metadata.

    Transitions remain append-only: write a new reflection/memory node and link
    it (for example with ``supersedes``) rather than updating an old node.
    Presence of this metadata never creates or mutates playbooks.
    """

    if "policy_candidate" not in meta_json:
        return
    if node_type != "reflection":
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "meta_json.policy_candidate is only valid on reflection memory_nodes",
            details={"field": "meta_json.policy_candidate", "node_type": node_type},
        )
    candidate = meta_json["policy_candidate"]
    if not isinstance(candidate, dict):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "meta_json.policy_candidate must be an object",
            details={"field": "meta_json.policy_candidate"},
        )
    status = candidate.get("status")
    if status not in POLICY_CANDIDATE_STATUSES:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "policy_candidate.status must be one of "
            f"{POLICY_CANDIDATE_STATUSES}",
            details={
                "field": "meta_json.policy_candidate.status",
                "value": status,
                "allowed": list(POLICY_CANDIDATE_STATUSES),
            },
        )
    if status == "raw_reflection":
        return
    statement = candidate.get("candidate_statement")
    if not isinstance(statement, str) or not statement.strip():
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "policy candidates require candidate_statement prose",
            details={"field": "meta_json.policy_candidate.candidate_statement"},
        )
    scope = candidate.get("scope")
    if not isinstance(scope, dict) or not scope:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "policy candidates require explicit scope metadata",
            details={"field": "meta_json.policy_candidate.scope"},
        )
    if not any(key in scope for key in ("strategy_id", "strategy_ids", "strategy_scope")):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "policy candidates must explicitly scope strategy applicability",
            details={
                "field": "meta_json.policy_candidate.scope.strategy",
                "reason": "missing_strategy_scope",
            },
        )
    if status in {"candidate_policy", "quarantined", "needs_more_evidence", "promoted_to_playbook"}:
        evidence = candidate.get("evidence")
        if not isinstance(evidence, dict):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "policy candidates require evidence metadata, even when caveated/missing",
                details={"field": "meta_json.policy_candidate.evidence"},
            )
        for field in ("reflection_ids", "caveats"):
            values = evidence.get(field)
            if values is not None and (
                not isinstance(values, list)
                or not all(isinstance(value, str) for value in values)
            ):
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    f"policy_candidate.evidence.{field} must be a list of strings when present",
                    details={"field": f"meta_json.policy_candidate.evidence.{field}"},
                )
    if status == "promoted_to_playbook" and not candidate.get("playbook_version_id"):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "promoted_to_playbook metadata must cite an explicit playbook_version_id; metadata alone never creates or modifies a playbook",
            details={"field": "meta_json.policy_candidate.playbook_version_id"},
        )
    if status == "rejected" and not candidate.get("rejection_reason"):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "rejected policy candidates require rejection_reason",
            details={"field": "meta_json.policy_candidate.rejection_reason"},
        )
    if status == "superseded" and not candidate.get("superseded_by"):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "superseded policy candidates require superseded_by",
            details={"field": "meta_json.policy_candidate.superseded_by"},
        )


_MEMORY_REFLECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target_kind": {"type": "string", "enum": list(VALID_MEMORY_ENDPOINTS)},
        "target_id": {"type": "string"},
        "target": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": list(VALID_MEMORY_ENDPOINTS)}, "id": {"type": "string"}},
            "description": "Sugar equivalent to target_kind + target_id.",
        },
        "body": {"type": "string"},
        "insight": {"type": "string", "description": "Sugar equivalent to body."},
        "strength_tags": {"type": "array", "items": {"type": "string"}},
        "weakness_tags": {"type": "array", "items": {"type": "string"}},
        "title": {"type": "string"},
        "importance": {"type": "integer", "minimum": 1, "maximum": 10},
        "confidence_base": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "decay_rate_per_day": {"type": "number"},
        "valid_from": {"type": "string"},
        "valid_to": {"type": "string"},
        "meta_json": {
            "type": "object",
            "description": (
                "Optional reflection metadata. When policy_candidate is present, "
                "status must be exactly one of raw_reflection, candidate_policy, "
                "quarantined, needs_more_evidence, rejected, promoted_to_playbook, "
                "superseded; candidate statuses require explicit scope/evidence."
            ),
        },
        "parent_node_id": {"type": "string"},
        "edge_id": {"type": "string"},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["idempotency_key"],
    "description": (
        "Write a reflection node plus about-edge. Use either canonical "
        "target_kind/target_id/body or sugar target={kind,id}/insight. "
        "At least one target shape and one body/insight value are required at runtime. "
        "strength_tags and weakness_tags are folded into meta_json.tags. "
        "Edge-sugar fields derived_from/supports/contradicts/supersedes are deferred; use memory.link."
    ),
}

ENDPOINT_TABLES: Final[dict[str, str]] = {
    "memory_node": "memory_nodes",
    "decision": "decisions",
    "thesis": "theses",
    "forecast": "forecasts",
    "outcome": "outcomes",
    "snapshot": "snapshots",
    "instrument": "instruments",
    "venue": "venues",
    "source": "sources",
    "signal": "signals",
    "strategy": "strategies",
    # `playbook_version` was wired up with the M4 playbook infrastructure
    # (bead trade-trace-40dz). Edges into a phantom playbook_version
    # previously passed unchecked, weakening playbook provenance and
    # review-bundle traceability.
    "playbook_version": "playbook_versions",
}
"""Tables we can verify rows in. `review` is the only endpoint without
a backing table in MVP; `review.bundle` produces ephemeral packets
rather than a persisted row. For `review` we accept the id without an
existence check and let downstream consumers branch on it. `strategy`
was added with the M3 strategies table (bead ubp). `playbook_version`
was added with the M4 playbook infrastructure (bead trade-trace-40dz)."""


# -- memory.retain --------------------------------------------------


def _memory_retain(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Create a memory_node row. Per bead e86 acceptance:
    - node_type ∈ {observation, reflection, playbook_rule}
    - meta_json shape is per-type but not enforced server-side in MVP
      (Pydantic discriminator is the aa2 design; the M3 minimum is
      `node_type` enforcement plus the bi-temporal validity columns)
    - reflections written via this raw path are caller-responsible for
      attaching an `about` edge; the safe path is `memory.reflect`.
    """

    node_type = require(args, "node_type")
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            return _memory_retain_in_uow(args, ctx, uow, node_type=node_type)
    finally:
        db.close()


def _memory_retain_in_uow(
    args: dict[str, Any],
    ctx: ToolContext,
    uow: UnitOfWork,
    *,
    node_type: str | None = None,
) -> dict[str, Any]:
    """Create a memory_node row using an existing transaction."""

    node_type = node_type or require(args, "node_type")
    if node_type not in NODE_TYPES:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"node_type must be one of {NODE_TYPES}; got {node_type!r}",
            details={"field": "node_type", "value": node_type,
                     "allowed": list(NODE_TYPES)},
        )
    body = require(args, "body")
    reject_if_contains_secrets(body, field="body")
    reject_if_contains_secrets(args.get("title"), field="title")

    importance = args.get("importance", 5)
    if not isinstance(importance, int) or not (1 <= importance <= 10):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "importance must be an integer in [1, 10]",
            details={"field": "importance", "value": importance},
        )
    confidence_base = args.get("confidence_base", 1.0)
    if not isinstance(confidence_base, (int, float)) or not (0.0 <= confidence_base <= 1.0):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "confidence_base must be a float in [0.0, 1.0]",
            details={"field": "confidence_base", "value": confidence_base},
        )
    decay_rate_per_day = args.get("decay_rate_per_day")
    valid_from = normalize_timestamp(args, "valid_from")
    valid_to = normalize_timestamp(args, "valid_to")
    # Validate meta_json shape at the direct retain boundary per
    # trade-trace-arcx. Adjacent normalization (memory.reflect ergonomics)
    # already enforces this, but the raw retain path used to `json.dumps`
    # whatever was passed, so a list/scalar would persist and confuse
    # downstream consumers that assume object-shaped metadata.
    meta_input = _parse_memory_meta_json_object(args.get("meta_json"))
    _validate_policy_candidate_meta(meta_input, node_type=node_type)
    meta_json = json.dumps(meta_input, sort_keys=True)
    title = args.get("title")
    parent_node_id = args.get("parent_node_id")
    idempotency_key = args.get("idempotency_key")
    seg = common_metadata(args)

    replay = check_idempotency_replay(
        uow, event_type="memory_node.retained",
        actor_id=ctx.actor_id, idempotency_key=idempotency_key,
    )
    if replay is not None:
        node_id = replay["id"]
        # Per bead trade-trace-e62: when the caller omitted `valid_from`
        # the original write stored `valid_from = created_at`. The
        # retry's args still have `valid_from = None`; passing that into
        # _emit_retained would produce a payload whose `valid_from`
        # differs from the original and the EventWriter would raise
        # IDEMPOTENCY_CONFLICT. Re-use the stored payload's
        # `valid_from` so a pure retry replays cleanly.
        replay_valid_from = replay.get("valid_from") if valid_from is None else valid_from
        _emit_retained(uow, ctx, node_id, args, body, title,
                       node_type, importance, confidence_base,
                       decay_rate_per_day, replay_valid_from, valid_to,
                       meta_json, parent_node_id, idempotency_key)
        row = uow.conn.execute(
            "SELECT created_at FROM memory_nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        return _retain_result(node_id, node_type, body, importance,
                              confidence_base, row[0])

    node_id = args.get("id") or new_id("mem")
    created_at = now_iso()
    effective_valid_from = valid_from or created_at
    uow.execute(
        "INSERT INTO memory_nodes(id, node_type, version, "
        "parent_node_id, title, body, meta_json, confidence_base, "
        "decay_rate_per_day, importance, valid_from, valid_to, "
        "invalidated_at, invalidated_by, agent_id, model_id, "
        "environment, run_id, created_at, actor_id) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)",
        (
            node_id, node_type, args.get("version", 1), parent_node_id,
            title, body, meta_json, confidence_base, decay_rate_per_day,
            importance, effective_valid_from, valid_to,
            seg["agent_id"], seg["model_id"], seg["environment"],
            seg["run_id"], created_at, ctx.actor_id,
        ),
    )
    _emit_retained(uow, ctx, node_id, args, body, title, node_type,
                   importance, confidence_base, decay_rate_per_day,
                   effective_valid_from, valid_to, meta_json,
                   parent_node_id, idempotency_key)
    return _retain_result(node_id, node_type, body, importance,
                          confidence_base, created_at)


def _emit_retained(uow, ctx, node_id, args, body, title, node_type,
                   importance, confidence_base, decay_rate_per_day,
                   valid_from, valid_to, meta_json, parent_node_id,
                   idempotency_key):
    emit_event(
        uow, event_type="memory_node.retained",
        subject_kind="memory_node", subject_id=node_id,
        payload={
            "id": node_id,
            "node_type": node_type,
            "version": args.get("version", 1),
            "parent_node_id": parent_node_id,
            "title": title,
            "body": body,
            "importance": importance,
            "confidence_base": confidence_base,
            "decay_rate_per_day": decay_rate_per_day,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "meta_json": meta_json,
            "tags": args.get("tags"),
        },
        actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
    )


def _retain_result(node_id, node_type, body, importance, confidence_base,
                   created_at):
    return {
        "id": node_id, "node_type": node_type, "body": body,
        "importance": importance, "confidence_base": confidence_base,
        "created_at": created_at,
    }


# -- memory.reflect ------------------------------------------------

# Per bead trade-trace-m0h: docs/memory-layer.md §10 enumerates these
# edge-sugar params on memory.reflect, but they are deferred to P1+.
# Reject them up front with a typed error so docs-following agents
# don't get a confusing schema reject from Pydantic land.
_DEFERRED_REFLECT_EDGE_FIELDS = (
    "derived_from", "supports", "contradicts", "supersedes",
)


def _normalize_reflect_input(args: dict[str, Any]) -> dict[str, Any]:
    """Accept the README quickstart shape (`target={kind, id}`,
    `insight`, `strength_tags`, `weakness_tags`) alongside the
    canonical flat shape, and translate to the canonical form before
    `_memory_reflect` validates it.

    The canonical fields after normalization are: `target_kind`,
    `target_id`, `body`. `strength_tags`/`weakness_tags` are folded
    into `metadata_json.tags` so the structured-tag recall path can
    find them later.
    """

    normalized = dict(args)

    target_obj = normalized.pop("target", None)
    if target_obj is not None:
        if not isinstance(target_obj, dict):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "memory.reflect `target` must be an object with "
                "`kind` and `id` (README §quickstart)",
                details={"field": "target", "value": target_obj},
            )
        existing_kind = normalized.get("target_kind")
        existing_id = normalized.get("target_id")
        target_kind = target_obj.get("kind")
        target_id = target_obj.get("id")
        if target_kind is None or target_id is None:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "memory.reflect `target` must include `kind` and `id`",
                details={"field": "target", "value": target_obj},
            )
        if existing_kind is not None and existing_kind != target_kind:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "memory.reflect `target.kind` conflicts with `target_kind`",
                details={
                    "field": "target",
                    "target_kind": existing_kind,
                    "target_object_kind": target_kind,
                },
            )
        if existing_id is not None and existing_id != target_id:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "memory.reflect `target.id` conflicts with `target_id`",
                details={
                    "field": "target",
                    "target_id": existing_id,
                    "target_object_id": target_id,
                },
            )
        normalized["target_kind"] = target_kind
        normalized["target_id"] = target_id

    if "insight" in normalized:
        insight_value = normalized.pop("insight")
        if "body" in normalized and normalized["body"] != insight_value:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "memory.reflect `insight` conflicts with `body`",
                details={
                    "field": "insight",
                    "body": normalized["body"],
                    "insight": insight_value,
                },
            )
        normalized["body"] = insight_value

    strength_tags = normalized.pop("strength_tags", None)
    weakness_tags = normalized.pop("weakness_tags", None)
    if strength_tags is not None or weakness_tags is not None:
        # memory.retain serializes the `meta_json` key (not
        # metadata_json) for memory_nodes; per-bead memory-layer.md §10
        # the strength/weakness tags are persisted there as
        # meta_json.tags.
        meta_obj = _parse_memory_meta_json_object(
            normalized.get("meta_json"),
            include_value_type_detail=False,
        )
        tags = list(meta_obj.get("tags") or [])
        for value, kind in (
            (strength_tags, "strength_tags"),
            (weakness_tags, "weakness_tags"),
        ):
            if value is None:
                continue
            if not isinstance(value, list) or not all(
                isinstance(t, str) for t in value
            ):
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    f"{kind} must be a list of strings",
                    details={"field": kind, "value": value},
                )
            tags.extend(value)
        if tags:
            meta_obj["tags"] = tags
        normalized["meta_json"] = meta_obj

    for deferred in _DEFERRED_REFLECT_EDGE_FIELDS:
        if deferred in normalized:
            raise ToolError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                f"memory.reflect edge-sugar field {deferred!r} is "
                "documented in memory-layer.md §10 but not implemented "
                "in MVP; use memory.link to write the edge explicitly "
                "until the sugar lands (deferred to P1+).",
                details={"field": deferred,
                         "deferred_to": "P1+ (memory-layer.md §10)"},
            )

    return normalized


def _memory_reflect(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Write a reflection node + `about` edge atomically. The pair is
    written in one transaction so the bead's orphan invariant holds:
    `SELECT count(*) FROM memory_nodes n WHERE n.node_type='reflection'
    AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.source_kind='memory_node'
    AND e.source_id=n.id AND e.edge_type='about')` always returns 0.

    Accepts two equivalent input shapes per bead trade-trace-m0h:
    - Flat: `target_kind`, `target_id`, `body` (canonical).
    - Sugar: `target={kind, id}`, `insight` (README §quickstart shape).

    Plus the README's `strength_tags` and `weakness_tags` lists, which
    are folded into the reflection's `metadata_json` as `tags` so the
    structured tag-aware recall path can find them later. The
    docs/memory-layer.md §10 edge-sugar fields (`derived_from`,
    `supports`, `contradicts`, `supersedes`) are documented there as
    P1+ deferred work; passing them today raises VALIDATION_ERROR
    until that bead lands so the docs/impl drift cannot grow further.
    """

    args = _normalize_reflect_input(args)

    target_kind = require(args, "target_kind")
    target_id = require(args, "target_id")
    if target_kind not in VALID_MEMORY_ENDPOINTS:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"target_kind must be one of {VALID_MEMORY_ENDPOINTS}",
            details={"field": "target_kind", "value": target_kind,
                     "allowed": list(VALID_MEMORY_ENDPOINTS)},
        )
    _verify_endpoint_exists(
        # Open the DB just for the existence check; the retain path
        # opens its own connection.
        args, target_kind=target_kind, target_id=target_id,
    )

    # Force node_type=reflection on this path; the body / importance /
    # bi-temporal args pass through to memory.retain's shared transactional
    # implementation. The node row, node event, about-edge row, and edge
    # event below are all committed or rolled back together.
    retain_args = {**args, "node_type": "reflection"}
    retain_args.pop("target_kind", None)
    retain_args.pop("target_id", None)

    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            result = _memory_retain_in_uow(retain_args, ctx, uow, node_type="reflection")
            node_id = result["id"]

            # Allow the caller to pin the edge id (used by the fixture
            # seed for byte-identical replay); otherwise generate one.
            edge_id = args.get("edge_id") or new_id("edg")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO edges(id, source_kind, source_id, target_kind, "
                "target_id, edge_type, metadata_json, created_at, actor_id) "
                "VALUES (?, 'memory_node', ?, ?, ?, 'about', '{}', ?, ?)",
                (edge_id, node_id, target_kind, target_id,
                 created_at, ctx.actor_id),
            )
            emit_event(
                uow, event_type="edge.created",
                subject_kind="edge", subject_id=edge_id,
                payload={
                    "id": edge_id,
                    "source_kind": "memory_node", "source_id": node_id,
                    "target_kind": target_kind, "target_id": target_id,
                    "edge_type": "about",
                },
                actor_id=ctx.actor_id, idempotency_key=None, ctx=ctx,
            )
    finally:
        db.close()
    result["edge_id"] = edge_id
    result["target_kind"] = target_kind
    result["target_id"] = target_id
    return result


def _verify_endpoint_exists(args, *, target_kind: str, target_id: str) -> None:
    table = ENDPOINT_TABLES.get(target_kind)
    if table is None:
        # `review`, `playbook_version`, `strategy` — no backing table in
        # MVP. Accept without existence check; FK constraints will catch
        # later if/when those tables land.
        return
    db = open_db_for_args(args)
    try:
        row = db.connection.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (target_id,),
        ).fetchone()
    finally:
        db.close()
    if row is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"{target_kind} {target_id!r} not found",
            details={"entity_kind": target_kind, "target_id": target_id},
        )


# -- memory.link ----------------------------------------------------


def _memory_link(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Create an explicit typed edge between memory/ledger endpoints.
    Validates source_kind, target_kind, and edge_type against the
    documented enums; verifies the source and target rows exist."""

    source_kind = require(args, "source_kind")
    source_id = require(args, "source_id")
    target_kind = require(args, "target_kind")
    target_id = require(args, "target_id")
    edge_type = require(args, "edge_type")

    if source_kind not in VALID_MEMORY_ENDPOINTS:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"source_kind must be one of {VALID_MEMORY_ENDPOINTS}",
            details={"field": "source_kind", "value": source_kind,
                     "allowed": list(VALID_MEMORY_ENDPOINTS)},
        )
    if target_kind not in VALID_MEMORY_ENDPOINTS:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"target_kind must be one of {VALID_MEMORY_ENDPOINTS}",
            details={"field": "target_kind", "value": target_kind,
                     "allowed": list(VALID_MEMORY_ENDPOINTS)},
        )
    if edge_type not in EDGE_TYPES:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"edge_type must be one of {EDGE_TYPES}",
            details={"field": "edge_type", "value": edge_type,
                     "allowed": list(EDGE_TYPES)},
        )
    _verify_endpoint_exists(args, target_kind=source_kind, target_id=source_id)
    _verify_endpoint_exists(args, target_kind=target_kind, target_id=target_id)

    metadata_json = json.dumps(args.get("metadata_json") or {}, sort_keys=True)
    idempotency_key = args.get("idempotency_key")

    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="edge.created",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                edge_id = replay["id"]
                emit_event(
                    uow, event_type="edge.created",
                    subject_kind="edge", subject_id=edge_id,
                    payload={
                        "source_kind": source_kind, "source_id": source_id,
                        "target_kind": target_kind, "target_id": target_id,
                        "edge_type": edge_type, "weight": args.get("weight"),
                    },
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT created_at FROM edges WHERE id = ?", (edge_id,),
                ).fetchone()
                return {
                    "id": edge_id, "source_kind": source_kind, "source_id": source_id,
                    "target_kind": target_kind, "target_id": target_id,
                    "edge_type": edge_type, "created_at": row[0],
                }

            edge_id = args.get("id") or new_id("edg")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO edges(id, source_kind, source_id, target_kind, "
                "target_id, edge_type, metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (edge_id, source_kind, source_id, target_kind, target_id,
                 edge_type, metadata_json, created_at, ctx.actor_id),
            )
            emit_event(
                uow, event_type="edge.created",
                subject_kind="edge", subject_id=edge_id,
                payload={
                    "id": edge_id,
                    "source_kind": source_kind, "source_id": source_id,
                    "target_kind": target_kind, "target_id": target_id,
                    "edge_type": edge_type, "weight": args.get("weight"),
                },
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
    finally:
        db.close()
    return {
        "id": edge_id, "source_kind": source_kind, "source_id": source_id,
        "target_kind": target_kind, "target_id": target_id,
        "edge_type": edge_type, "created_at": created_at,
    }


# -- memory.recall --------------------------------------------------


@dataclass(frozen=True)
class RecallOptions:
    query: str
    limit_k: int
    max_chars: int | None
    compact: bool
    include_body: bool
    include_provenance: bool
    min_confidence: float | None
    node_types: list[str] | None
    mode: str
    as_of: str | None
    requested_strategies: list[str]
    context: dict[str, Any]


def _memory_recall(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Rank memory nodes by RRF over BM25 + temporal + graph strategies,
    apply bi-temporal `as_of` filter, return top-k with provenance, and
    log a `memory_recall_events` row that the rebuildable
    `memory_node_stats` projection consumes.
    """

    options = _parse_recall_options(args)
    seg = common_metadata(args)

    db = open_db_for_args(args)
    try:
        provider = _embeddings_provider(db.connection)
        if provider != "none" and "semantic" not in options.requested_strategies:
            options = RecallOptions(
                **{**options.__dict__, "requested_strategies": [*options.requested_strategies, "semantic"]}
            )
        in_scope_rows = _load_in_scope_nodes(db.connection, as_of=options.as_of)
        if options.node_types is not None:
            in_scope_rows = {
                nid: row for nid, row in in_scope_rows.items()
                if row["node_type"] in options.node_types
            }
        rankings = _build_recall_rankings(db.connection, options, in_scope_rows, provider)
        scored = _score_ranked_nodes(db.connection, rankings, in_scope_rows)
        items, _chars_used = _shape_recall_items(
            db.connection, scored[:options.limit_k], in_scope_rows, options,
        )
        recall_id, created_at = _write_recall_event_and_stats(
            db.connection, items=items, rankings=rankings, options=options,
            ctx=ctx, seg=seg,
        )
    finally:
        db.close()

    response = _build_recall_response(
        recall_id=recall_id, rankings=rankings, options=options,
        items=items, in_scope_rows=in_scope_rows,
    )
    _set_recall_meta_hints(ctx, created_at=created_at, rankings=rankings, options=options)
    return response


def _parse_recall_options(args: dict[str, Any]) -> RecallOptions:
    query = require(args, "query")
    limit_k = int(args.get("k", 10))
    if limit_k < 1 or limit_k > 100:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "k must be an integer in [1, 100]", details={"field": "k", "value": limit_k})
    max_chars = args.get("max_chars")
    if max_chars is not None and (not isinstance(max_chars, int) or max_chars < 1):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "max_chars must be a positive integer when set", details={"field": "max_chars", "value": max_chars})
    compact = args.get("compact", False)
    include_body = args.get("include_body", True)
    include_provenance = args.get("include_provenance", True)
    min_confidence = args.get("min_confidence")
    if min_confidence is not None and (not isinstance(min_confidence, (int, float)) or not (0.0 <= min_confidence <= 1.0)):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "min_confidence must be a float in [0.0, 1.0]", details={"field": "min_confidence", "value": min_confidence})
    node_types = args.get("node_types")
    if node_types is not None:
        if not isinstance(node_types, list) or not node_types:
            raise ToolError(ErrorCode.VALIDATION_ERROR, "node_types must be a non-empty list when set", details={"field": "node_types", "value": node_types})
        invalid_types = [t for t in node_types if t not in NODE_TYPES]
        if invalid_types:
            raise ToolError(ErrorCode.VALIDATION_ERROR, f"node_types must be drawn from {NODE_TYPES}", details={"field": "node_types", "invalid": invalid_types, "allowed": list(NODE_TYPES)})
    mode = args.get("mode", "fused")
    if mode not in ("fused", "per_strategy"):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "mode must be 'fused' or 'per_strategy'", details={"field": "mode", "value": mode, "allowed": ["fused", "per_strategy"]})
    as_of = normalize_timestamp(args, "as_of")
    requested_strategies = args.get("strategies") or ["bm25", "temporal", "graph"]
    if not isinstance(requested_strategies, list) or not requested_strategies:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "strategies must be a non-empty list", details={"field": "strategies", "value": requested_strategies})
    valid_strategies = {"bm25", "temporal", "graph", "semantic"}
    invalid = [strategy for strategy in requested_strategies if strategy not in valid_strategies]
    if invalid:
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"strategies must be drawn from {sorted(valid_strategies)}", details={"field": "strategies", "invalid": invalid, "allowed": sorted(valid_strategies)})
    context = args.get("context") or {}
    return RecallOptions(query, limit_k, max_chars, compact, include_body, include_provenance, min_confidence, node_types, mode, as_of, requested_strategies, context)


def _build_recall_rankings(conn: sqlite3.Connection, options: RecallOptions, in_scope_rows: dict[str, dict[str, Any]], provider: str) -> dict[str, list[str]]:
    rankings: dict[str, list[str]] = {}
    if "bm25" in options.requested_strategies:
        rankings["bm25"] = _bm25_rank(conn, options.query, in_scope_rows)
    if "temporal" in options.requested_strategies:
        rankings["temporal"] = _temporal_rank(in_scope_rows, as_of=options.as_of)
    if "graph" in options.requested_strategies:
        rankings["graph"] = _graph_rank(conn, context=options.context, in_scope_rows=in_scope_rows)
    if "semantic" in options.requested_strategies and provider != "none":
        semantic_ranked = _semantic_rank(conn, options.query, provider, in_scope_rows)
        if semantic_ranked:
            rankings["semantic"] = semantic_ranked
    return rankings


def _score_ranked_nodes(conn: sqlite3.Connection, rankings: dict[str, list[str]], in_scope_rows: dict[str, dict[str, Any]]) -> list[tuple[str, float, dict[str, list[int]]]]:
    combined = _rrf_combine(rankings)
    superseded = _superseded_node_ids(conn)
    scored: list[tuple[str, float, dict[str, list[int]]]] = []
    for node_id, base_score, provenance in combined:
        row = in_scope_rows.get(node_id)
        if row is None:
            continue
        importance = row["importance"]
        boost = 1.0 + (importance - 5) * IMPORTANCE_BOOST_SLOPE
        if node_id in superseded:
            boost *= SUPERSESSION_DISCOUNT
        scored.append((node_id, base_score * boost, provenance))
    scored.sort(key=lambda r: (-r[1], r[0]))
    return scored


def _shape_recall_items(conn: sqlite3.Connection, scored_top: list[tuple[str, float, dict[str, list[int]]]], in_scope_rows: dict[str, dict[str, Any]], options: RecallOptions) -> tuple[list[dict[str, Any]], int]:
    filtered: list[tuple[str, float, dict[str, list[int]]]] = []
    for node_id, score, provenance in scored_top:
        if options.min_confidence is not None:
            conf = in_scope_rows[node_id].get("confidence_base", 1.0)
            if conf is None or conf < options.min_confidence:
                continue
        filtered.append((node_id, score, provenance))
    items: list[dict[str, Any]] = []
    chars_used = 0
    for node_id, score, provenance in filtered:
        row = in_scope_rows[node_id]
        body = row["body"] or ""
        if options.compact and len(body) > 120:
            body = body[:117] + "..."
        if options.max_chars is not None and chars_used + len(body) > options.max_chars:
            break
        chars_used += len(body)
        item: dict[str, Any] = {"id": node_id, "node_type": row["node_type"], "title": row["title"], "importance": row["importance"], "score": round(score, 6), "source_refs": _source_refs_for(conn, node_id)}
        if options.include_body:
            item["body"] = body
        if options.include_provenance:
            item["strategy_provenance"] = provenance
        items.append(item)
    return items, chars_used


def _write_recall_event_and_stats(conn: sqlite3.Connection, *, items: list[dict[str, Any]], rankings: dict[str, list[str]], options: RecallOptions, ctx: ToolContext, seg: dict[str, Any]) -> tuple[str, str]:
    recall_id = new_id("rcl")
    created_at = now_iso()
    node_ids_returned = [it["id"] for it in items]
    conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT INTO memory_recall_events(recall_id, query, strategies_used, node_ids_returned, context_json, limit_k, as_of, created_at, actor_id, agent_id, model_id, environment, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (recall_id, options.query, json.dumps(list(rankings.keys()), sort_keys=True), json.dumps(node_ids_returned, sort_keys=False), json.dumps(options.context, sort_keys=True), options.limit_k, options.as_of, created_at, ctx.actor_id, seg["agent_id"], seg["model_id"], seg["environment"], seg["run_id"]),
        )
        for node_id in node_ids_returned:
            conn.execute(
                "INSERT INTO memory_node_stats(node_id, recall_count, last_recalled_at) VALUES (?, 1, ?) ON CONFLICT(node_id) DO UPDATE SET recall_count = memory_node_stats.recall_count + 1, last_recalled_at = excluded.last_recalled_at",
                (node_id, created_at),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return recall_id, created_at


def _build_recall_response(*, recall_id: str, rankings: dict[str, list[str]], options: RecallOptions, items: list[dict[str, Any]], in_scope_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    response: dict[str, Any] = {"recall_id": recall_id, "query": options.query, "strategies_used": sorted(rankings.keys()), "k": options.limit_k, "as_of": options.as_of, "mode": options.mode, "items": items, "total_in_scope": len(in_scope_rows)}
    if options.mode == "per_strategy":
        response["per_strategy"] = {strategy: ranked[:options.limit_k] for strategy, ranked in rankings.items()}
    return response


def _set_recall_meta_hints(ctx: ToolContext, *, created_at: str, rankings: dict[str, list[str]], options: RecallOptions) -> None:
    from trade_trace.version import __version__
    ctx.meta_hints["generated_at"] = created_at
    ctx.meta_hints["package_version"] = __version__
    ctx.meta_hints["retrieval_strategy_metadata"] = {"strategies_used": sorted(rankings.keys()), "k": options.limit_k, "max_chars": options.max_chars, "k_rrf": K_RRF, "importance_boost_slope": IMPORTANCE_BOOST_SLOPE, "supersession_discount": SUPERSESSION_DISCOUNT}


# -- ranking helpers -----------------------------------------------


def _load_in_scope_nodes(
    conn: sqlite3.Connection, *, as_of: str | None,
) -> dict[str, dict[str, Any]]:
    """Return `{id: row_dict}` for every node passing the bi-temporal
    `as_of` filter. When `as_of` is None, treat it as the current
    timestamp so recall reflects "right now"."""

    effective = as_of or now_iso()
    cur = conn.execute(
        """
        SELECT id, node_type, version, title, body, importance,
               confidence_base, decay_rate_per_day, valid_from, valid_to,
               invalidated_at, created_at
        FROM memory_nodes
        WHERE valid_from <= ?
          AND (valid_to IS NULL OR ? < valid_to)
          AND (invalidated_at IS NULL OR invalidated_at > ?)
        """,
        (effective, effective, effective),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cur.fetchall():
        out[row[0]] = {
            "id": row[0], "node_type": row[1], "version": row[2],
            "title": row[3], "body": row[4], "importance": row[5],
            "confidence_base": row[6], "decay_rate_per_day": row[7],
            "valid_from": row[8], "valid_to": row[9],
            "invalidated_at": row[10], "created_at": row[11],
        }
    return out


def _bm25_rank(
    conn: sqlite3.Connection, query: str, in_scope: dict[str, dict[str, Any]],
) -> list[str]:
    """Return node IDs ranked by FTS5 BM25 score (best first), filtered
    to the in-scope set."""

    if not in_scope:
        return []
    # FTS5 MATCH with bm25() rank. Empty queries fall back to no-op.
    if not query.strip():
        return []
    try:
        cur = conn.execute(
            "SELECT id FROM memory_node_fts "
            "WHERE memory_node_fts MATCH ? "
            "ORDER BY bm25(memory_node_fts) LIMIT 500",
            (query,),
        )
        rows = [r[0] for r in cur.fetchall()]
    except sqlite3.OperationalError:
        # Malformed MATCH expression — fall back to LIKE.
        like_q = f"%{query}%"
        cur = conn.execute(
            "SELECT id FROM memory_nodes WHERE body LIKE ? OR title LIKE ? "
            "LIMIT 500",
            (like_q, like_q),
        )
        rows = [r[0] for r in cur.fetchall()]
    return [r for r in rows if r in in_scope]


def _temporal_rank(
    in_scope: dict[str, dict[str, Any]], *, as_of: str | None,
) -> list[str]:
    """Rank in-scope nodes by recency relative to `as_of` (or now)."""

    effective = as_of or now_iso()
    effective_dt = datetime.fromisoformat(effective.replace("Z", "+00:00"))
    scored: list[tuple[str, float]] = []
    for node_id, row in in_scope.items():
        created_dt = datetime.fromisoformat(
            row["created_at"].replace("Z", "+00:00")
        )
        delta = abs((effective_dt - created_dt).total_seconds())
        # Smaller delta = better.
        scored.append((node_id, delta))
    scored.sort(key=lambda r: (r[1], r[0]))
    return [r[0] for r in scored]


def _graph_rank(
    conn: sqlite3.Connection,
    *,
    context: dict[str, Any],
    in_scope_rows: dict[str, dict[str, Any]],
) -> list[str]:
    """Rank in-scope nodes by edge connectivity to the supplied context.

    The context is an optional `{kind, id}` entrypoint (e.g.
    `{kind: "instrument", id: "ins_..."}`). Nodes with edges pointing
    to that entrypoint rank first; nodes with no graph connection rank
    after (in id order).

    Per bead trade-trace-ubp, `kind='strategy'` is a first-class context:
    matched memory_nodes are those with a direct edge to the strategy
    row OR with an edge to a decision/thesis carrying that strategy_id.
    """

    kind = context.get("kind")
    target_id = context.get("id")
    if not kind or not target_id:
        # No context → graph strategy degenerates to id order.
        return sorted(in_scope_rows.keys())
    if kind == "strategy":
        # Strategy scoping: direct edges to the strategy row PLUS edges
        # to row-backed scopes (decisions, theses) that carry the
        # matching strategy_id.
        cur = conn.execute(
            """
            SELECT DISTINCT source_id FROM edges
            WHERE source_kind = 'memory_node'
              AND (
                (target_kind = 'strategy' AND target_id = ?)
                OR (target_kind = 'decision' AND target_id IN (
                    SELECT id FROM decisions WHERE strategy_id = ?
                ))
                OR (target_kind = 'thesis' AND target_id IN (
                    SELECT id FROM theses WHERE strategy_id = ?
                ))
              )
            """,
            (target_id, target_id, target_id),
        )
    else:
        cur = conn.execute(
            """
            SELECT DISTINCT source_id FROM edges
            WHERE source_kind = 'memory_node'
              AND target_kind = ? AND target_id = ?
            """,
            (kind, target_id),
        )
    connected = [r[0] for r in cur.fetchall() if r[0] in in_scope_rows]
    connected_set = set(connected)
    rest = sorted(
        node_id for node_id in in_scope_rows if node_id not in connected_set
    )
    return [*sorted(connected), *rest]


def _embeddings_provider(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute(
            "SELECT value FROM config WHERE key = 'embeddings.provider'"
        ).fetchone()
    except sqlite3.OperationalError:
        return "none"
    return str(row[0]) if row and row[0] else "none"


def _float32_blob(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def _blob_to_float32(blob: bytes, dim: int) -> list[float]:
    if len(blob) != dim * 4:
        return []
    return list(struct.unpack(f"<{dim}f", blob))


def _query_embedding(query: str, *, dim: int, provider: str, model_id: str) -> list[float]:
    """Deterministic local embedding stub for opt-in offline operation."""

    _ = (provider, model_id)
    buckets = [0.0] * dim
    for i, byte in enumerate(query.encode("utf-8")):
        buckets[(byte + i) % dim] += float((byte % 31) + 1)
    norm = sum(v * v for v in buckets) ** 0.5
    return [v / norm for v in buckets] if norm else buckets


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    denom_a = sum(v * v for v in a) ** 0.5
    denom_b = sum(v * v for v in b) ** 0.5
    if denom_a == 0.0 or denom_b == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / (denom_a * denom_b)


def _semantic_rank(
    conn: sqlite3.Connection,
    query: str,
    provider: str,
    in_scope: dict[str, dict[str, Any]],
) -> list[str]:
    if not in_scope:
        return []
    if provider.startswith("api:"):
        from trade_trace.security.keyring import load_api_key

        # Resolve at call time and keep the secret in this stack frame only.
        # No caching and no return/error payload includes this value. For this
        # bead, api:openai support stops at keyring/key-presence gating: query
        # embeddings are still produced by the deterministic local stub below,
        # and no OpenAI/network embedding call is implemented here.
        if provider == "api:openai":
            service = "trade-trace:embeddings:openai"
        else:
            return []
        api_key = load_api_key(service)
        if not api_key:
            return []
        del api_key
    try:
        rows = conn.execute(
            "SELECT node_id, embedding, dim, model_id FROM memory_node_embeddings "
            "WHERE provider = ?",
            (provider,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    scored: list[tuple[str, float]] = []
    query_cache: dict[tuple[int, str], list[float]] = {}
    for node_id, blob, dim, model_id in rows:
        if node_id not in in_scope:
            continue
        key = (int(dim), str(model_id))
        if key not in query_cache:
            query_cache[key] = _query_embedding(query, dim=key[0], provider=provider, model_id=key[1])
        vec = _blob_to_float32(bytes(blob), key[0])
        if not vec:
            continue
        scored.append((node_id, _cosine(query_cache[key], vec)))
    scored.sort(key=lambda r: (-r[1], r[0]))
    return [node_id for node_id, score in scored if score > 0.0]


def _rrf_combine(
    rankings: dict[str, list[str]],
) -> list[tuple[str, float, dict[str, list[int]]]]:
    """Reciprocal-rank-fusion combine. Returns `(node_id, score,
    provenance)` triples where `provenance[strategy]` is the
    1-indexed rank in that strategy's ranking (only present if the
    strategy ranked the node)."""

    accumulated: dict[str, float] = {}
    provenance: dict[str, dict[str, list[int]]] = {}
    for strategy, ranked in rankings.items():
        for rank, node_id in enumerate(ranked, start=1):
            accumulated[node_id] = accumulated.get(node_id, 0.0) + 1.0 / (
                K_RRF + rank
            )
            provenance.setdefault(node_id, {})
            provenance[node_id][strategy] = [rank]
    out = [(node_id, accumulated[node_id], provenance.get(node_id, {}))
           for node_id in accumulated]
    out.sort(key=lambda r: (-r[1], r[0]))
    return out


def _superseded_node_ids(conn: sqlite3.Connection) -> set[str]:
    """Return memory_node ids that appear as the TARGET of a supersedes
    edge from another memory_node."""

    cur = conn.execute(
        """
        SELECT DISTINCT target_id FROM edges
        WHERE source_kind = 'memory_node'
          AND target_kind = 'memory_node'
          AND edge_type = 'supersedes'
        """
    )
    return {row[0] for row in cur.fetchall()}


def _source_refs_for(conn: sqlite3.Connection, node_id: str) -> list[dict[str, str]]:
    """Return every edge originating from the node (the node's
    provenance trail). Used by an agent inspecting a recall result to
    drill into the cited rows."""

    cur = conn.execute(
        """
        SELECT target_kind, target_id, edge_type FROM edges
        WHERE source_kind = 'memory_node' AND source_id = ?
        ORDER BY edge_type, target_kind, target_id
        """,
        (node_id,),
    )
    return [
        {"target_kind": tk, "target_id": tid, "edge_type": et}
        for tk, tid, et in cur.fetchall()
    ]


# -- registration --------------------------------------------------


def register_memory_tools(registry: ToolRegistry) -> None:
    """Register memory.* tools on the supplied registry (bead e86)."""

    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    registry.register(
        "memory.retain",
        _memory_retain,
        is_write=True,
        **_examples_for("memory.retain"),
        description=(
            "Create a typed memory_node row. node_type ∈ "
            "{observation, reflection, playbook_rule}. Carries bi-temporal "
            "validity (valid_from, valid_to), importance (1-10), "
            "confidence_base, and an optional decay_rate_per_day. "
            "Reflections written via this path are caller-responsible for "
            "the about-edge; prefer memory.reflect for the safe path. "
            "Reflection meta_json may carry policy_candidate lifecycle "
            "metadata; it is validation/read metadata only and never mutates "
            "playbooks automatically."
        ),
    )
    registry.register(
        "memory.reflect",
        _memory_reflect,
        is_write=True,
        **_examples_for("memory.reflect"),
        description=(
            "Write a reflection node + about-edge atomically against a "
            "ledger or memory endpoint (decision, thesis, forecast, outcome, "
            "memory_node, etc.). Enforces the orphan invariant: every "
            "reflection has an about-edge. Accepts canonical "
            "target_kind/target_id/body and README sugar target/insight. "
            "Optional meta_json.policy_candidate records the explicit "
            "reflection-to-policy quarantine lifecycle without creating or "
            "modifying playbook versions/rules."
        ),
        json_schema=_MEMORY_REFLECT_SCHEMA,
        usage_summary="Create one reflection memory node about an existing ledger or memory target and atomically attach the about-edge.",
        examples=("tt memory reflect --target-kind decision --target-id dec_... --body 'What changed?' --idempotency-key <uuid>",),
        common_failures=("target_kind/target_id must identify an existing row.",),
        next_actions=("Use memory.recall to find relevant prior nodes before writing reflections.",),
    )
    registry.register(
        "memory.link",
        _memory_link,
        is_write=True,
        **_examples_for("memory.link"),
        description=(
            "Create an explicit typed edge between memory/ledger endpoints. "
            "Validates source_kind, target_kind, and edge_type against the "
            "documented enums; verifies the rows exist."
        ),
    )
    registry.register(
        "memory.recall",
        _memory_recall,
        description=(
            "Rank memory_nodes by RRF over BM25 (FTS5) + temporal + graph "
            "strategies behind a bi-temporal as_of filter. Logs a "
            "memory_recall_events row and updates the memory_node_stats "
            "projection (recall_count, last_recalled_at). Returns top-k "
            "with id, body, score, strategy_provenance, source_refs."
        ),
        example_minimal={
            "query": "risk management",
            "context": {},
            "strategies": ["bm25", "temporal", "graph"],
            "k": 10,
            "max_chars": 8000,
            "compact": False,
            "include_body": True,
            "include_provenance": True,
            "min_confidence": 0.0,
            "node_types": ["reflection"],
            "mode": "fused",
            "as_of": "2025-01-01T00:00:00Z",
        },
        optional_keys=(
            "context",
            "strategies",
            "k",
            "max_chars",
            "compact",
            "include_body",
            "include_provenance",
            "min_confidence",
            "node_types",
            "mode",
            "as_of",
        ),
    )
