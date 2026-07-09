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

import heapq
import json
import math
import re
import sqlite3
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

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
    parse_int_arg,
    reject_credential_metadata,
    reject_if_contains_secrets,
    require,
    store_metadata_json,
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

MIN_RECALL_RANKING_CANDIDATES: Final[int] = 100
"""Minimum per-strategy rank window retained before fused top-k scoring."""

RECALL_RANKING_CANDIDATE_MULTIPLIER: Final[int] = 10
"""Per-strategy candidate multiplier over requested recall k."""

_EMBEDDING_IN_CLAUSE_CHUNK: Final[int] = 900
"""Max node_ids per `node_id IN (...)` chunk in `_semantic_rank` so the
bound-parameter count (chunk + 1 for `provider`) stays under SQLite's default
`SQLITE_MAX_VARIABLE_NUMBER` of 999 on older builds (trade-trace-zsi8)."""

_LOCAL_ONNX_EMBEDDER_CACHE: dict[Path, Any] = {}
_ScoreRow = tuple[str, float] | tuple[str, float, Any]


def _score_sort_key(row: _ScoreRow) -> tuple[float, str]:
    """Sort memory-score pairs by score descending, then id ascending."""

    return -row[1], row[0]


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
    strategy_id = scope.get("strategy_id")
    strategy_ids = scope.get("strategy_ids")
    strategy_scope = scope.get("strategy_scope")
    has_meaningful_strategy_scope = (
        (isinstance(strategy_id, str) and bool(strategy_id.strip()))
        or (
            isinstance(strategy_ids, list)
            and bool(strategy_ids)
            and all(isinstance(value, str) and bool(value.strip()) for value in strategy_ids)
        )
        or (isinstance(strategy_scope, str) and bool(strategy_scope.strip()))
    )
    if not has_meaningful_strategy_scope:
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
        "derived_from": {
            "type": "array", "items": {"type": "string"},
            "description": "Memory-node id(s) this reflection was synthesized from; writes a derived_from edge from the reflection to each.",
        },
        "supports": {
            "type": "array", "items": {"type": "string"},
            "description": "Memory-node id(s) this reflection provides positive evidence for; writes a supports edge from the reflection to each.",
        },
        "contradicts": {
            "type": "array", "items": {"type": "string"},
            "description": "Memory-node id(s) this reflection provides negative evidence against; writes a contradicts edge from the reflection to each.",
        },
        "supersedes": {
            "type": "array", "items": {"type": "string"},
            "description": "Older memory-node id(s) this reflection replaces; writes a supersedes edge from the reflection to each (the old nodes stay readable but are discounted at recall).",
        },
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
        "Edge-sugar fields derived_from/supports/contradicts/supersedes each take a memory-node id "
        "or list of ids and write the named edge type from the reflection to each, in the same "
        "transaction (use memory.link for edges that do not originate at this reflection)."
    ),
}

_MEMORY_LINK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source_kind": {"type": "string", "enum": list(VALID_MEMORY_ENDPOINTS)},
        "source_id": {"type": "string"},
        "target_kind": {"type": "string", "enum": list(VALID_MEMORY_ENDPOINTS)},
        "target_id": {"type": "string"},
        "edge_type": {"type": "string", "enum": list(EDGE_TYPES)},
        "metadata_json": {"type": "object"},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": [
        "source_kind",
        "source_id",
        "target_kind",
        "target_id",
        "edge_type",
        "idempotency_key",
    ],
    "description": (
        "Create an explicit typed edge between memory/ledger endpoints. "
        "source_kind and target_kind must each be one of the endpoint kinds "
        "(memory_node, signal, strategy, decision, thesis, forecast, outcome, "
        "snapshot, instrument, venue, source, review, playbook_version); "
        "edge_type must be one of about/supports/contradicts/supersedes/"
        "derived_from/violates/follows. Both endpoint rows must already exist."
    ),
}

# AX-060: memory.retain was registered with **_examples_for(...) and no
# explicit json_schema, so its MCP schema auto-derived from example_minimal
# advertised node_type as a bare string even though the runtime enum-validates
# it against NODE_TYPES with a self-documenting error (the AX-051/054/055
# auto-derived-schema class). The optional knobs the runtime accepts
# (importance/confidence_base/decay_rate_per_day/validity/title/meta_json) were
# also undiscoverable. This explicit schema mirrors the runtime.
_MEMORY_RETAIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "node_type": {
            "type": "string",
            "enum": list(NODE_TYPES),
            "description": "Typed memory node kind; one of the documented enum.",
        },
        "body": {"type": "string", "description": "Memory body text; free-text fields are scanned for embedded sensitive values at write time."},
        "title": {"type": "string"},
        "importance": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Importance 1-10; defaults to 5."},
        "confidence_base": {"type": "number", "minimum": 0.0, "maximum": 1.0, "description": "Base confidence 0.0-1.0; defaults to 1.0."},
        "decay_rate_per_day": {"type": "number", "description": "Optional per-day exponential confidence decay rate (default no decay). At recall time the node's effective confidence is confidence_base * exp(-decay_rate_per_day * age_days), where age_days is the elapsed time from created_at to the recall's as_of; the min_confidence filter compares against this decayed value, so a high decay rate drops the node below the threshold sooner."},
        "valid_from": {"type": "string", "description": "Optional bi-temporal validity start; defaults to created_at."},
        "valid_to": {"type": "string", "description": "Optional bi-temporal validity end."},
        "parent_node_id": {"type": "string"},
        "meta_json": {"type": "object", "description": "Optional structured metadata (reflections may carry policy_candidate lifecycle metadata)."},
        "idempotency_key": {"type": "string"},
        "agent_id": {"type": "string"},
        "model_id": {"type": "string"},
        "run_id": {"type": "string"},
        "environment": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["node_type", "body", "idempotency_key"],
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
    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            result = _memory_retain_in_uow(args, ctx, uow, node_type=node_type)
    from trade_trace.logging import get_logger

    get_logger("trade_trace.tools.memory").info(
        "memory retained",
        extra={
            "actor": ctx.actor_id,
            "tool": ctx.tool,
            "subject": "memory_node",
            "verb": "retain",
            "record_id": result["id"],
            "node_type": node_type,
        },
    )
    return result


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
    if valid_from is not None and valid_to is not None and valid_to < valid_from:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "valid_to must be greater than or equal to valid_from",
            details={
                "field": "valid_to",
                "valid_to": valid_to,
                "valid_from": valid_from,
                "reason": "invalid_interval",
            },
        )
    # Validate meta_json shape at the direct retain boundary per
    # trade-trace-arcx. Adjacent normalization (memory.reflect ergonomics)
    # already enforces this, but the raw retain path used to `json.dumps`
    # whatever was passed, so a list/scalar would persist and confuse
    # downstream consumers that assume object-shaped metadata.
    meta_input = _parse_memory_meta_json_object(args.get("meta_json"))
    reject_credential_metadata(meta_input, field="meta_json")
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
        "parent_node_id, title, body, meta_json, metadata_json, confidence_base, "
        "decay_rate_per_day, importance, valid_from, valid_to, "
        "invalidated_at, invalidated_by, agent_id, model_id, "
        "environment, run_id, created_at, actor_id) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)",
        (
            node_id, node_type, args.get("version", 1), parent_node_id,
            title, body, meta_json, meta_json, confidence_base, decay_rate_per_day,
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

# Per bead trade-trace-qikt: docs/memory-layer.md §10 enumerates these
# edge-sugar params on memory.reflect. Each names one edge type written
# FROM the new reflection node TO the listed memory-node ids, in the same
# transaction as the reflection + about-edge. The field name maps 1:1 to
# the edge_type so callers can write multi-edge reflections without a
# separate memory.link round-trip. Previously these raised
# UNSUPPORTED_CAPABILITY (deferred to P1+); now implemented.
_REFLECT_EDGE_SUGAR_FIELDS: Final[tuple[str, ...]] = (
    "derived_from", "supports", "contradicts", "supersedes",
)
# Private key on the normalized args carrying the parsed sugar edges as a
# list of (edge_type, target_memory_node_id) pairs for the writer. Not a
# public field; stripped before the retain helper sees the args.
_REFLECT_EDGES_KEY = "_reflect_sugar_edges"


def _normalize_reflect_edge_sugar(normalized: dict[str, Any]) -> None:
    """Parse the memory-layer.md §10 edge-sugar fields
    (``derived_from`` / ``supports`` / ``contradicts`` / ``supersedes``)
    off ``normalized`` and stash the resulting (edge_type, target_id)
    pairs under ``_REFLECT_EDGES_KEY`` for the reflect writer.

    Each field accepts a memory-node id string or a list of memory-node
    id strings; both are folded into one ordered, de-duplicated edge list
    so the same id under the same edge type is never written twice. The
    raw sugar fields are popped so they do not leak into the retain path.
    """

    edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for field in _REFLECT_EDGE_SUGAR_FIELDS:
        if field not in normalized:
            continue
        value = normalized.pop(field)
        if value is None:
            continue
        ids = [value] if isinstance(value, str) else value
        if not isinstance(ids, list) or not all(
            isinstance(i, str) for i in ids
        ):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"memory.reflect `{field}` must be a memory-node id "
                "string or a list of memory-node id strings",
                details={"field": field, "value": value},
            )
        for target_id in ids:
            key = (field, target_id)
            if key in seen:
                continue
            seen.add(key)
            edges.append(key)
    if edges:
        normalized[_REFLECT_EDGES_KEY] = edges


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

    _normalize_reflect_edge_sugar(normalized)

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
    structured tag-aware recall path can find them later.

    The docs/memory-layer.md §10 edge-sugar fields (`derived_from`,
    `supports`, `contradicts`, `supersedes`) each accept a memory-node
    id or list of ids and write the named edge type FROM the new
    reflection node TO each id, atomically in the same transaction as
    the reflection node and about-edge (bead trade-trace-qikt). This
    lets a caller write a multi-edge reflection in one call instead of
    a reflect + N memory.link round-trips; memory.link remains the
    interface for edges that do not originate at a reflection node.
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
    # Force node_type=reflection on this path; the body / importance /
    # bi-temporal args pass through to memory.retain's shared transactional
    # implementation. The node row, node event, about-edge row, and edge
    # event below are all committed or rolled back together.
    retain_args = {**args, "node_type": "reflection"}
    retain_args.pop("target_kind", None)
    retain_args.pop("target_id", None)
    retain_args.pop(_REFLECT_EDGES_KEY, None)

    with db_for_args(args) as db:
        # Run the endpoint existence check on this same connection
        # (bead trade-trace-yt45) instead of opening a second handle just
        # for the probe; the retain/write path below reuses it too.
        _verify_endpoint_exists(
            args, target_kind=target_kind, target_id=target_id,
            conn=db.connection,
        )
        with UnitOfWork(db.connection) as uow:
            result = _memory_retain_in_uow(retain_args, ctx, uow, node_type="reflection")
            node_id = result["id"]

            # Make the about-edge co-idempotent with the retain
            # (trade-trace-5udu). _memory_retain_in_uow replays the
            # existing node_id on a same-key retry, but the edge INSERT +
            # edge.created emit below ran unconditionally, so N reflect
            # calls with the same idempotency_key wrote N about-edges for
            # the same (memory_node, target) pair. SELECT any existing
            # about-edge from this node to this target first; on a hit,
            # reuse its edge_id and skip both the INSERT and the re-emit.
            existing_edge = uow.conn.execute(
                "SELECT id FROM edges WHERE source_kind = 'memory_node' "
                "AND source_id = ? AND target_kind = ? AND target_id = ? "
                "AND edge_type = 'about' LIMIT 1",
                (node_id, target_kind, target_id),
            ).fetchone()
            if existing_edge is not None:
                edge_id = existing_edge[0]
            else:
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

            # Write the memory-layer.md §10 edge-sugar edges in the same
            # transaction (bead trade-trace-qikt). Each is a typed edge
            # FROM the reflection node TO a memory-node id the caller
            # named; like the about-edge they are co-idempotent — a
            # same-key reflect retry reuses any existing identical edge
            # rather than inserting a duplicate.
            sugar_edges = _emit_reflect_sugar_edges(
                uow, ctx, node_id, args.get(_REFLECT_EDGES_KEY) or [],
            )
    result["edge_id"] = edge_id
    result["target_kind"] = target_kind
    result["target_id"] = target_id
    if sugar_edges:
        result["edges"] = sugar_edges
    return result


def _emit_reflect_sugar_edges(uow, ctx, node_id: str,
                              edges: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Write the parsed memory.reflect edge-sugar edges (each a
    ``(edge_type, target_memory_node_id)`` pair) FROM ``node_id`` inside
    the caller's open UnitOfWork. Verifies each target memory_node row
    exists, reuses an existing identical edge on a same-key retry, and
    emits one `edge.created` event per newly-inserted edge. Returns the
    written edges as ``{edge_type, target_id, edge_id}`` dicts in input
    order so the reflect response surfaces what was wired."""

    written: list[dict[str, str]] = []
    for edge_type, target_id in edges:
        exists = uow.conn.execute(
            "SELECT 1 FROM memory_nodes WHERE id = ?", (target_id,),
        ).fetchone()
        if exists is None:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                f"memory.reflect {edge_type} target memory_node "
                f"{target_id!r} not found",
                details={"edge_type": edge_type, "target_id": target_id,
                         "target_kind": "memory_node"},
            )
        existing = uow.conn.execute(
            "SELECT id FROM edges WHERE source_kind = 'memory_node' "
            "AND source_id = ? AND target_kind = 'memory_node' "
            "AND target_id = ? AND edge_type = ? LIMIT 1",
            (node_id, target_id, edge_type),
        ).fetchone()
        if existing is not None:
            written.append({"edge_type": edge_type, "target_id": target_id,
                            "edge_id": existing[0]})
            continue
        edge_id = new_id("edg")
        created_at = now_iso()
        uow.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, "
            "target_id, edge_type, metadata_json, created_at, actor_id) "
            "VALUES (?, 'memory_node', ?, 'memory_node', ?, ?, '{}', ?, ?)",
            (edge_id, node_id, target_id, edge_type, created_at,
             ctx.actor_id),
        )
        emit_event(
            uow, event_type="edge.created",
            subject_kind="edge", subject_id=edge_id,
            payload={
                "id": edge_id,
                "source_kind": "memory_node", "source_id": node_id,
                "target_kind": "memory_node", "target_id": target_id,
                "edge_type": edge_type,
            },
            actor_id=ctx.actor_id, idempotency_key=None, ctx=ctx,
        )
        written.append({"edge_type": edge_type, "target_id": target_id,
                        "edge_id": edge_id})
    return written


def _verify_endpoint_exists(
    args,
    *,
    target_kind: str,
    target_id: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Verify an endpoint row exists.

    When `conn` is supplied the caller's already-open connection is
    reused for the existence probe instead of opening a fresh database
    handle (bead trade-trace-yt45). memory.link previously opened three
    separate connections (two endpoint checks + the write) and
    memory.reflect two (one endpoint check + the write); reusing the
    caller's connection collapses those to a single open per call. When
    `conn` is None the legacy self-opening behavior is preserved for any
    caller that has no connection in hand.
    """

    table = ENDPOINT_TABLES.get(target_kind)
    if table is None:
        # review has no backing table; review.bundle produces ephemeral packets
        # rather than persisted rows. Accept without existence check.
        return
    if conn is not None:
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (target_id,),
        ).fetchone()
    else:
        with db_for_args(args) as db:
            row = db.connection.execute(
                f"SELECT 1 FROM {table} WHERE id = ?", (target_id,),
            ).fetchone()
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
    # Route memory.link metadata through the shared dual-layer guard so the
    # edge's metadata_json gets the same secret scan + credential-key
    # rejection every other write tool applies (bead trade-trace-jm14 /
    # INV-6); previously this used a bare json.dumps that bypassed both.
    metadata_json = store_metadata_json(args, "metadata_json")
    idempotency_key = args.get("idempotency_key")

    with db_for_args(args) as db:
        # Reuse this connection for both endpoint existence checks
        # (bead trade-trace-yt45) — previously each opened its own handle,
        # so a single memory.link opened three connections total.
        _verify_endpoint_exists(
            args, target_kind=source_kind, target_id=source_id,
            conn=db.connection,
        )
        _verify_endpoint_exists(
            args, target_kind=target_kind, target_id=target_id,
            conn=db.connection,
        )
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

    with db_for_args(args) as db:
        provider = _embeddings_provider(db.connection)
        if provider != "none" and "semantic" not in options.requested_strategies:
            options = RecallOptions(
                **{**options.__dict__, "requested_strategies": [*options.requested_strategies, "semantic"]}
            )
        in_scope_rows = _load_in_scope_nodes(
            db.connection, as_of=options.as_of, node_types=options.node_types,
        )
        rankings = _build_recall_rankings(db.connection, options, in_scope_rows, provider)
        scored = _score_ranked_nodes(
            db.connection, rankings, in_scope_rows,
            as_of=options.as_of, limit=options.limit_k,
        )
        items, _chars_used = _shape_recall_items(
            db.connection, scored[:options.limit_k], in_scope_rows, options,
        )
        recall_id, created_at = _write_recall_event_and_stats(
            db.connection, items=items, rankings=rankings, options=options,
            ctx=ctx, seg=seg,
        )

    response = _build_recall_response(
        recall_id=recall_id, rankings=rankings, options=options,
        items=items, in_scope_rows=in_scope_rows,
    )
    _set_recall_meta_hints(ctx, created_at=created_at, rankings=rankings, options=options)
    return response


def _parse_recall_options(args: dict[str, Any]) -> RecallOptions:
    query = require(args, "query")
    limit_k = parse_int_arg(
        args,
        "k",
        10,
        minimum=1,
        maximum=100,
        message="k must be an integer in [1, 100]",
    )
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


def _recall_candidate_limit(*, k: int, corpus_size: int) -> int:
    return min(
        corpus_size,
        max(MIN_RECALL_RANKING_CANDIDATES, k * RECALL_RANKING_CANDIDATE_MULTIPLIER),
    )


def _build_recall_rankings(conn: sqlite3.Connection, options: RecallOptions, in_scope_rows: dict[str, dict[str, Any]], provider: str) -> dict[str, list[str]]:
    rankings: dict[str, list[str]] = {}
    candidate_limit = _recall_candidate_limit(
        k=options.limit_k, corpus_size=len(in_scope_rows),
    )
    if "bm25" in options.requested_strategies:
        rankings["bm25"] = _bm25_rank(conn, options.query, in_scope_rows)[:candidate_limit]
    if "temporal" in options.requested_strategies:
        rankings["temporal"] = _temporal_rank(
            in_scope_rows, as_of=options.as_of, limit=candidate_limit,
        )
    if "graph" in options.requested_strategies:
        rankings["graph"] = _graph_rank(
            conn, context=options.context, in_scope_rows=in_scope_rows,
        )[:candidate_limit]
    if "semantic" in options.requested_strategies and provider != "none":
        semantic_ranked = _semantic_rank(conn, options.query, provider, in_scope_rows)
        if semantic_ranked:
            rankings["semantic"] = semantic_ranked[:candidate_limit]
    return rankings


def _score_ranked_nodes(conn: sqlite3.Connection, rankings: dict[str, list[str]], in_scope_rows: dict[str, dict[str, Any]], *, as_of: str | None = None, limit: int | None = None) -> list[tuple[str, float, dict[str, list[int]]]]:
    rrf_limit = None
    if limit is not None:
        rrf_limit = _recall_candidate_limit(
            k=limit, corpus_size=sum(len(ranked) for ranked in rankings.values()),
        )
    combined = _rrf_combine(rankings, limit=rrf_limit)
    superseded = _superseded_node_ids(conn, as_of=as_of)
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
    if limit is None:
        scored.sort(key=_score_sort_key)
        return scored
    return heapq.nsmallest(limit, scored, key=_score_sort_key)


def _effective_confidence(row: dict[str, Any], *, as_of_iso: str) -> float:
    """Return the time-decayed confidence for a node at the recall's
    point-in-time, per memory-layer.md §6:

        effective = clamp(confidence_base * exp(-decay_rate_per_day * age_days), 0, 1)

    `age_days` is the elapsed wall-clock time between the node's
    `created_at` and the recall's effective timestamp (`as_of` when set,
    else "now"), measured in fractional days so sub-day recalls of a
    freshly-written node see no decay. A null/zero `decay_rate_per_day`
    is a no-op (`exp(0) == 1.0`), so a node retrieves with exactly its
    stored `confidence_base` — the previous behavior. A null
    `confidence_base` defaults to 1.0 (schema default). Recalls in the
    past relative to `created_at` (negative age) are clamped to age 0 so
    decay never *increases* confidence.

    The supersession discount is applied to the RRF ranking score in
    `_score_ranked_nodes`, not here; this function isolates the
    confidence/decay component that the `min_confidence` gate filters on.
    """

    confidence_base = row.get("confidence_base")
    if confidence_base is None:
        confidence_base = 1.0
    decay_rate = row.get("decay_rate_per_day") or 0.0
    if decay_rate <= 0.0:
        return max(0.0, min(1.0, float(confidence_base)))
    created_at = row.get("created_at")
    if not created_at:
        return max(0.0, min(1.0, float(confidence_base)))
    created_dt = datetime.fromisoformat(str(created_at))
    as_of_dt = datetime.fromisoformat(as_of_iso)
    age_days = max(0.0, (as_of_dt - created_dt).total_seconds() / 86400.0)
    effective = float(confidence_base) * math.exp(-float(decay_rate) * age_days)
    return max(0.0, min(1.0, effective))


def _shape_recall_items(conn: sqlite3.Connection, scored_top: list[tuple[str, float, dict[str, list[int]]]], in_scope_rows: dict[str, dict[str, Any]], options: RecallOptions) -> tuple[list[dict[str, Any]], int]:
    filtered: list[tuple[str, float, dict[str, list[int]]]] = []
    as_of_iso = options.as_of or now_iso()
    for node_id, score, provenance in scored_top:
        if options.min_confidence is not None:
            conf = _effective_confidence(in_scope_rows[node_id], as_of_iso=as_of_iso)
            if conf < options.min_confidence:
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
        # `source_refs` is inserted here (right after `score`) as an empty
        # placeholder to preserve the original item key order; it is filled
        # from a single batched edges query below (trade-trace-jd0x) rather
        # than one `_source_refs_for` round-trip per item.
        item: dict[str, Any] = {"id": node_id, "node_type": row["node_type"], "title": row["title"], "importance": row["importance"], "score": round(score, 6), "source_refs": []}
        if options.include_body:
            item["body"] = body
        if options.include_provenance:
            item["strategy_provenance"] = provenance
        items.append(item)
    # Batch the per-item source_refs into a single query (trade-trace-jd0x):
    # the loop above can yield up to k=100 items, and issuing one edges
    # SELECT per item is an N+1 round-trip. Collect the final node_ids,
    # fetch all refs at once, and attach in a second pass. Output ordering
    # and shape are byte-identical to the per-node `_source_refs_for` path.
    refs_by_node = _source_refs_batch(conn, [it["id"] for it in items])
    for item in items:
        item["source_refs"] = refs_by_node[item["id"]]
    return items, chars_used


def _write_recall_event_and_stats(conn: sqlite3.Connection, *, items: list[dict[str, Any]], rankings: dict[str, list[str]], options: RecallOptions, ctx: ToolContext, seg: dict[str, Any]) -> tuple[str, str]:
    recall_id = new_id("rcl")
    created_at = now_iso()
    node_ids_returned = [it["id"] for it in items]
    with UnitOfWork(conn) as uow:
        uow.execute(
            "INSERT INTO memory_recall_events(recall_id, query, strategies_used, node_ids_returned, context_json, limit_k, as_of, created_at, actor_id, agent_id, model_id, environment, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (recall_id, options.query, json.dumps(list(rankings.keys()), sort_keys=True), json.dumps(node_ids_returned, sort_keys=False), json.dumps(options.context, sort_keys=True), options.limit_k, options.as_of, created_at, ctx.actor_id, seg["agent_id"], seg["model_id"], seg["environment"], seg["run_id"]),
        )
        for node_id in node_ids_returned:
            uow.execute(
                "INSERT INTO memory_node_stats(node_id, recall_count, last_recalled_at) VALUES (?, 1, ?) ON CONFLICT(node_id) DO UPDATE SET recall_count = memory_node_stats.recall_count + 1, last_recalled_at = excluded.last_recalled_at",
                (node_id, created_at),
            )
    return recall_id, created_at


def _build_recall_response(*, recall_id: str, rankings: dict[str, list[str]], options: RecallOptions, items: list[dict[str, Any]], in_scope_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    response: dict[str, Any] = {"recall_id": recall_id, "query": options.query, "strategies_used": sorted(rankings), "k": options.limit_k, "as_of": options.as_of, "mode": options.mode, "items": items, "total_in_scope": len(in_scope_rows)}
    if options.mode == "per_strategy":
        response["per_strategy"] = {strategy: ranked[:options.limit_k] for strategy, ranked in rankings.items()}
    return response


def _set_recall_meta_hints(ctx: ToolContext, *, created_at: str, rankings: dict[str, list[str]], options: RecallOptions) -> None:
    from trade_trace.version import __version__
    ctx.meta_hints["generated_at"] = created_at
    ctx.meta_hints["package_version"] = __version__
    ctx.meta_hints["retrieval_strategy_metadata"] = {"strategies_used": sorted(rankings), "k": options.limit_k, "max_chars": options.max_chars, "k_rrf": K_RRF, "importance_boost_slope": IMPORTANCE_BOOST_SLOPE, "supersession_discount": SUPERSESSION_DISCOUNT}


# -- ranking helpers -----------------------------------------------


def _load_in_scope_nodes(
    conn: sqlite3.Connection,
    *,
    as_of: str | None,
    node_types: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return `{id: row_dict}` for every node passing the bi-temporal
    `as_of` filter. When `as_of` is None, treat it as the current
    timestamp so recall reflects "right now".

    When `node_types` is supplied the type filter is pushed into the SQL
    `WHERE` clause (bead trade-trace-yt45) rather than materializing the
    full validity-scoped corpus and discarding non-matching rows in
    Python. The result is identical — the caller previously filtered the
    returned dict by the same `node_type IN ...` predicate — but the
    engine never builds row dicts for out-of-type nodes, which also keeps
    `total_in_scope` (len of this dict) at the same node-type-filtered
    value the post-filter produced.
    """

    effective = as_of or now_iso()
    params: list[Any] = [effective, effective, effective]
    type_clause = ""
    if node_types:
        placeholders = ", ".join("?" for _ in node_types)
        type_clause = f"\n          AND node_type IN ({placeholders})"
        params.extend(node_types)
    cur = conn.execute(
        f"""
        SELECT id, node_type, version, title, body, importance,
               confidence_base, decay_rate_per_day, valid_from, valid_to,
               invalidated_at, created_at
        FROM memory_nodes
        WHERE valid_from <= ?
          AND (valid_to IS NULL OR ? < valid_to)
          AND (invalidated_at IS NULL OR invalidated_at > ?){type_clause}
        """,
        tuple(params),
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
    rows = _fts_match(conn, query, in_scope=in_scope)
    if not rows:
        # Two ways the raw MATCH yields nothing usable, both common for
        # natural-language recall (trade-trace-95ry):
        #   * rows == []  : syntactically valid but FTS5's implicit-AND means
        #                   no single node holds EVERY token (e.g. a phrase
        #                   where one word is absent), so bm25 silently
        #                   contributes nothing and recall degrades to
        #                   temporal/graph.
        #   * rows is None: the expression was malformed — a bare dotted or
        #                   hyphenated identifier (forecast.add, BTC-USD) is an
        #                   FTS5 syntax error, not a literal.
        # In both cases retry with an OR-combined, quoted-token query so the
        # best partial lexical match still surfaces (ranked by bm25) before
        # giving up. Quoting neutralizes operators/punctuation and makes
        # dotted/hyphenated tokens match the way they were indexed.
        or_query = _or_token_query(query)
        or_rows = (
            _fts_match(conn, or_query, in_scope=in_scope)
            if or_query is not None else None
        )
        if or_rows:
            rows = or_rows
        elif rows is None:
            # Raw expression malformed and OR retry didn't recover — LIKE net.
            rows = _like_fallback(conn, query, in_scope=in_scope)
        else:
            rows = []
    # `_fts_match`/`_like_fallback` already restrict to the in-scope set in
    # SQL when it fits one IN-clause; this post-filter is the safety net for
    # the large-corpus chunked path (trade-trace-ukwy / yt45).
    return [r for r in rows if r in in_scope]


def _scope_in_clause(
    in_scope: dict[str, dict[str, Any]] | None, *, reserved_params: int,
) -> tuple[str, tuple[str, ...]] | None:
    """Build an ``AND id IN (?, ?, ...)`` fragment + bound params for the
    in-scope node ids, or ``None`` when the scope is absent or too large to
    bind in a single statement.

    When ``None`` is returned the caller keeps the original
    fetch-then-Python-filter path (correct, just unoptimized) so the
    bound-parameter count never exceeds SQLite's
    ``SQLITE_MAX_VARIABLE_NUMBER`` ceiling. ``reserved_params`` is the number
    of parameters the surrounding query already binds (e.g. the MATCH query
    or the LIKE patterns) so the chunk budget accounts for them
    (trade-trace-ukwy, mirrors the chunking discipline in ``_semantic_rank``
    per trade-trace-zsi8)."""

    if not in_scope:
        return None
    if len(in_scope) > _EMBEDDING_IN_CLAUSE_CHUNK - reserved_params:
        return None
    ids = tuple(in_scope)
    placeholders = ",".join("?" for _ in ids)
    return f" AND id IN ({placeholders})", ids


def _fts_match(
    conn: sqlite3.Connection,
    query: str,
    *,
    in_scope: dict[str, dict[str, Any]] | None = None,
) -> list[str] | None:
    """Run an FTS5 MATCH ranked by bm25(); return ranked ids, or None when the
    expression is malformed (caller decides the fallback).

    When ``in_scope`` is supplied and fits one IN-clause, the scope filter is
    pushed into the SQL so the ``LIMIT 500`` applies AFTER the bi-temporal
    scope join rather than to the raw top-500 (which the caller then
    discarded in Python). This stops a busy corpus from filling the 500-row
    window with out-of-scope hits and starving the in-scope ones
    (trade-trace-ukwy / yt45). The global bm25 order is preserved because it
    is still a single ``ORDER BY bm25() LIMIT 500`` statement."""

    scope = _scope_in_clause(in_scope, reserved_params=1)
    scope_clause, scope_params = scope if scope is not None else ("", ())
    try:
        cur = conn.execute(
            "SELECT id FROM memory_node_fts "
            "WHERE memory_node_fts MATCH ?" + scope_clause + " "
            "ORDER BY bm25(memory_node_fts) LIMIT 500",
            (query, *scope_params),
        )
        return [r[0] for r in cur.fetchall()]
    except sqlite3.OperationalError:
        return None


def _like_fallback(
    conn: sqlite3.Connection,
    query: str,
    *,
    in_scope: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    like_q = f"%{query}%"
    # The LIKE fallback runs only when FTS5 is unavailable, so it has no
    # bm25() relevance signal to order by. Without an explicit ORDER BY the
    # SQLite row order is indeterminate, which makes downstream RRF ranking
    # non-deterministic across runs. Impose a recency-first, id-tiebroken
    # order so the fallback is at least reproducible (it is NOT a relevance
    # ranking — it is a stable, recency-biased candidate list).
    #
    # Push the in-scope filter into SQL when it fits one IN-clause so the
    # LIMIT applies after scope filtering (trade-trace-ukwy); two LIKE
    # patterns are already bound, so reserve 2.
    scope = _scope_in_clause(in_scope, reserved_params=2)
    scope_clause, scope_params = scope if scope is not None else ("", ())
    cur = conn.execute(
        "SELECT id FROM memory_nodes WHERE (body LIKE ? OR title LIKE ?)"
        + scope_clause
        + " ORDER BY created_at DESC, id ASC LIMIT 500",
        (like_q, like_q, *scope_params),
    )
    return [r[0] for r in cur.fetchall()]


def _or_token_query(query: str) -> str | None:
    """Build an OR-combined FTS5 query from a multi-word natural-language
    string. Each token is wrapped as a quoted phrase so FTS operators and
    punctuation are inert and dotted/hyphenated identifiers tokenize the same
    way they were indexed. Returns None when fewer than two indexable tokens
    exist (single-token queries gain nothing — OR equals the original)."""

    tokens = [t for t in query.split() if re.search(r"\w", t)]
    if len(tokens) < 2:
        return None
    quoted = ['"' + t.replace('"', '""') + '"' for t in tokens]
    return " OR ".join(quoted)


def _temporal_rank(
    in_scope: dict[str, dict[str, Any]], *, as_of: str | None, limit: int | None = None,
) -> list[str]:
    """Rank in-scope nodes by recency relative to `as_of` (or now)."""

    effective = as_of or now_iso()
    effective_dt = datetime.fromisoformat(effective)
    scored = []
    for node_id, row in in_scope.items():
        created_dt = datetime.fromisoformat(
            row["created_at"].replace("Z", "+00:00")
        )
        delta = abs((effective_dt - created_dt).total_seconds())
        # Smaller delta = better.
        scored.append((node_id, delta))
    if limit is not None:
        scored = heapq.nsmallest(limit, scored, key=lambda r: (r[1], r[0]))
    else:
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

    Strategy semantics with no context (bead trade-trace-2iug): when the
    context carries no `kind` or no `id`, the graph strategy has no
    entrypoint to measure connectivity against, so an id-ordered ranking
    of the full corpus would be purely alphabetical — a zero-signal
    contribution that still forces RRF to iterate all N nodes. In that
    case the strategy abstains by returning an empty list: it stays a
    *requested* strategy (so it still appears in `strategies_used`) but
    contributes no ranks to the RRF fusion, which iterates only over the
    ranks each strategy actually supplies. BM25/temporal/semantic remain
    the active signals when no graph entrypoint is given.
    """

    kind = context.get("kind")
    target_id = context.get("id")
    if not kind or not target_id:
        # No graph entrypoint → no meaningful connectivity signal. Abstain
        # with an empty ranking rather than emitting a zero-signal id-order
        # sort of the whole corpus (bead trade-trace-2iug). _rrf_combine
        # skips empty rankings cleanly, so the strategy simply does not
        # contribute to fusion.
        return []
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
    """Embed a query using the opt-in local ONNX/tokenizers path.

    Missing optional dependencies or model assets return an empty vector so the
    semantic strategy simply drops out of recall. BM25/temporal/graph ranking
    remain unconditional and journal startup is never blocked by embeddings.
    """

    if provider != "local":
        return []
    try:
        from trade_trace.models.embeddings import LocalEmbeddingUnavailable, LocalOnnxEmbedder
    except Exception:  # noqa: BLE001 - optional embedding dependency absence disables semantic search
        return []
    try:
        model_dir = _local_model_dir_for_connection(_ACTIVE_SEMANTIC_CONNECTION)
        embedder = _LOCAL_ONNX_EMBEDDER_CACHE.get(model_dir)
        if embedder is None:
            embedder = LocalOnnxEmbedder(model_dir)
            _LOCAL_ONNX_EMBEDDER_CACHE[model_dir] = embedder
        vector = embedder.embed(query)
    except (LocalEmbeddingUnavailable, ToolError, OSError, sqlite3.Error):
        return []
    if dim and len(vector) != dim:
        return []
    _ = model_id
    return vector


_ACTIVE_SEMANTIC_CONNECTION: sqlite3.Connection | None = None


def _local_model_dir_for_connection(conn: sqlite3.Connection | None) -> Any:
    if conn is None:
        raise ToolError(ErrorCode.STORAGE_ERROR, "semantic connection is unavailable")
    row = conn.execute("PRAGMA database_list").fetchone()
    if row is None or not row[2]:
        raise ToolError(ErrorCode.STORAGE_ERROR, "database path is unavailable")
    home = Path(str(row[2])).resolve().parent.parent
    return home / "models" / "bge-small-en-v1.5"


def _l2_norm(v: list[float]) -> float:
    return sum(x * x for x in v) ** 0.5


def _cosine_with_query_norm(query: list[float], query_norm: float, doc: list[float]) -> float:
    """Cosine similarity with a precomputed query L2 norm.

    `_semantic_rank` calls this once per stored embedding while the query
    vector is fixed, so its norm is hoisted out of the loop instead of being
    recomputed N times (trade-trace-4xg1). For a unit query vector
    (query_norm == 1.0) this reduces to dot / denom_b; the formula is otherwise
    identical to `_cosine`.
    """

    if len(query) != len(doc) or not query:
        return 0.0
    denom_b = _l2_norm(doc)
    if query_norm == 0.0 or denom_b == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(query, doc, strict=True)) / (query_norm * denom_b)


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return _cosine_with_query_norm(a, _l2_norm(a), b)


def _semantic_rank(
    conn: sqlite3.Connection,
    query: str,
    provider: str,
    in_scope: dict[str, dict[str, Any]],
) -> list[str]:
    if not in_scope:
        return []
    if provider != "local":
        return []
    # Push the in_scope predicate into the DB scan via an IN-clause on the
    # node_ids rather than transferring every stored embedding blob to Python
    # and discarding out-of-scope rows afterwards (trade-trace-zsi8). For 10k
    # nodes with 384-dim float32 embeddings the old `WHERE provider = ?` scan
    # materialized ~15 MB of blobs even when only a handful were in scope.
    # in_scope is pre-built by _load_in_scope_nodes from memory_nodes'
    # bi-temporal filter, so the IN-clause is the in_scope set verbatim — the
    # result set is identical, only the out-of-scope blob transfer is removed.
    # node_ids are chunked to stay under SQLite's bound-parameter ceiling
    # (default SQLITE_MAX_VARIABLE_NUMBER is 999 on older builds).
    node_ids = list(in_scope)
    try:
        rows: list[tuple[Any, Any, Any, Any]] = []
        for chunk_start in range(0, len(node_ids), _EMBEDDING_IN_CLAUSE_CHUNK):
            chunk = node_ids[chunk_start:chunk_start + _EMBEDDING_IN_CLAUSE_CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            rows.extend(
                conn.execute(
                    "SELECT node_id, embedding, dim, model_id "
                    "FROM memory_node_embeddings "
                    f"WHERE provider = ? AND node_id IN ({placeholders})",
                    (provider, *chunk),
                ).fetchall()
            )
    except sqlite3.OperationalError:
        return []
    scored: list[tuple[str, float]] = []
    # Cache the query embedding AND its L2 norm per (dim, model) key. The query
    # vector is fixed across all stored embeddings, so its norm is computed once
    # here instead of being recomputed inside _cosine for every row
    # (trade-trace-4xg1). Local embeddings are L2-normalized at write time, so
    # query_norm is ~1.0 and scoring reduces to a dot product / doc-norm.
    query_cache: dict[tuple[int, str], tuple[list[float], float]] = {}
    global _ACTIVE_SEMANTIC_CONNECTION
    previous_conn = _ACTIVE_SEMANTIC_CONNECTION
    _ACTIVE_SEMANTIC_CONNECTION = conn
    try:
        for node_id, blob, dim, model_id in rows:
            # The IN-clause above already restricts rows to in_scope, so this
            # guard is now a defensive no-op kept for clarity of the invariant
            # (trade-trace-zsi8).
            if node_id not in in_scope:
                continue
            key = (int(dim), str(model_id))
            if key not in query_cache:
                query_vec = _query_embedding(query, dim=key[0], provider=provider, model_id=key[1])
                query_cache[key] = (query_vec, _l2_norm(query_vec))
            query_vec, query_norm = query_cache[key]
            if not query_vec:
                continue
            vec = _blob_to_float32(bytes(blob), key[0])
            if not vec:
                continue
            scored.append((node_id, _cosine_with_query_norm(query_vec, query_norm, vec)))
    finally:
        _ACTIVE_SEMANTIC_CONNECTION = previous_conn
    scored.sort(key=_score_sort_key)
    return [node_id for node_id, score in scored if score > 0.0]


def _rrf_combine(
    rankings: dict[str, list[str]], *, limit: int | None = None,
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
    if limit is not None:
        return heapq.nsmallest(limit, out, key=_score_sort_key)
    out.sort(key=_score_sort_key)
    return out


def _superseded_node_ids(conn: sqlite3.Connection, *, as_of: str | None = None) -> set[str]:
    """Return memory_node ids that appear as the TARGET of a supersedes
    edge from another memory_node.

    When `as_of` is provided, only supersedes edges whose `created_at`
    pre-dates (or equals) the recall's point-in-time count — a node is
    not "superseded" at a timestamp before the supersedes edge was
    written. This keeps the SUPERSESSION_DISCOUNT bi-temporally
    symmetric with `_load_in_scope_nodes`, which gates
    valid_from/valid_to/invalidated_at on the same `as_of`
    (trade-trace-lhaf). When `as_of` is None, recall reflects "right
    now" and every supersedes edge applies."""

    # This triple-predicate scan is served by the partial covering index
    # `idx_edges_supersedes` (migration 031, bead trade-trace-17k9):
    # `edges(source_kind, target_kind, created_at, target_id) WHERE
    # edge_type = 'supersedes'`. Keep the predicate order/columns aligned
    # with that index so the recall stays an index seek rather than a full
    # scan of the memory_node target partition.
    sql = """
        SELECT DISTINCT target_id FROM edges
        WHERE source_kind = 'memory_node'
          AND target_kind = 'memory_node'
          AND edge_type = 'supersedes'
    """
    params: tuple[str, ...] = ()
    if as_of is not None:
        sql += "  AND created_at <= ?\n"
        params = (as_of,)
    cur = conn.execute(sql, params)
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


def _source_refs_batch(
    conn: sqlite3.Connection, node_ids: list[str],
) -> dict[str, list[dict[str, str]]]:
    """Batched form of `_source_refs_for` (trade-trace-jd0x).

    Returns `{node_id: [edge_dict, ...]}` for every id in ``node_ids``,
    fetching all provenance edges in a single ``IN (...)`` query instead
    of one round-trip per node. Every id in the input gets an entry —
    nodes with no outgoing edges map to an empty list — and duplicate ids
    collapse to a single key. The per-node edge ordering
    (``edge_type, target_kind, target_id``) is byte-identical to
    ``_source_refs_for`` because the batched query orders by
    ``source_id, edge_type, target_kind, target_id`` (the leading
    ``source_id`` only groups rows; it does not reorder within a node).
    """

    # Seed every requested id so callers always get a list (even []),
    # and dedupe while preserving first-seen order for the IN-list params.
    refs: dict[str, list[dict[str, str]]] = {}
    for nid in node_ids:
        refs.setdefault(nid, [])
    if not refs:
        return refs
    unique_ids = list(refs)
    placeholders = ",".join("?" for _ in unique_ids)
    cur = conn.execute(
        f"""
        SELECT source_id, target_kind, target_id, edge_type FROM edges
        WHERE source_kind = 'memory_node' AND source_id IN ({placeholders})
        ORDER BY source_id, edge_type, target_kind, target_id
        """,
        tuple(unique_ids),
    )
    for source_id, tk, tid, et in cur.fetchall():
        refs[source_id].append(
            {"target_kind": tk, "target_id": tid, "edge_type": et}
        )
    return refs


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
        json_schema=_MEMORY_RETAIN_SCHEMA,
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
        json_schema=_MEMORY_LINK_SCHEMA,
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
