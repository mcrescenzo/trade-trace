"""Lightweight capture-now / enrich-later market idea wrapper.

`idea.capture` deliberately does not introduce a first-class draft lifecycle or
new tables. It composes existing local/auditable primitives:

- `source.add` stores the raw captured text/provenance as an inline manual note.
- `memory.retain` stores a draft/needs_enrichment observation node.
- `source.attach_to_memory_node` links source -> memory_node so later promotion
  into instrument/snapshot/thesis/forecast/decision rows can preserve lineage.

No external data fetch, trade execution, advice generation, or broker/wallet
integration is performed here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    normalize_timestamp,
    open_db_for_args,
    reject_if_contains_secrets,
    require,
)
from trade_trace.tools.ledger import (
    _source_add_in_uow,
    _source_attach_to_memory_node_in_uow,
)
from trade_trace.tools.memory import _memory_retain_in_uow

_IDEA_CAPTURE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "thought": {
            "type": "string",
            "description": "Raw market thought exactly as captured. This is not investment advice.",
        },
        "title": {"type": "string"},
        "captured_at": {"type": "string"},
        "uri": {"type": "string"},
        "source_ref": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "importance": {"type": "integer", "minimum": 1, "maximum": 10},
        "confidence_base": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "metadata_json": {"type": "object"},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["thought", "idempotency_key"],
    "description": (
        "Capture a rough market idea as local draft primitives: source.add + "
        "memory.retain(observation) + source.attach_to_memory_node. No advice, "
        "no external market data, and no first-class draft table."
    ),
}


def _child_key(parent: str | None, suffix: str) -> str | None:
    if parent is None:
        return None
    return f"{parent}:idea.capture:{suffix}"


def _capture_content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idea_capture(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Capture an un-enriched market idea using existing primitives.

    This is intentionally wrapper-first. The response tells the caller exactly
    which local rows were created and how to promote them while preserving the
    returned source/memory provenance ids.
    """

    thought = require(args, "thought")
    reject_if_contains_secrets(thought, field="thought")
    reject_if_contains_secrets(args.get("title"), field="title")
    captured_at = normalize_timestamp(args, "captured_at")
    idempotency_key = args.get("idempotency_key")

    tags = args.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        from trade_trace.contracts.errors import ErrorCode
        from trade_trace.tools.errors import ToolError

        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "tags must be a list of strings (or comma-separated CLI string)",
            details={"field": "tags", "value": tags},
        )

    base_meta = args.get("metadata_json") or {}
    if not isinstance(base_meta, dict):
        from trade_trace.contracts.errors import ErrorCode
        from trade_trace.tools.errors import ToolError

        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "metadata_json must be an object for idea.capture",
            details={"field": "metadata_json", "value_type": type(base_meta).__name__},
        )

    provenance_meta = {
        **base_meta,
        "trade_trace_flow": "idea.capture",
        "draft_state": "needs_enrichment",
        "no_advice": True,
        "external_fetch_performed": False,
        "promotion_status": "unpromoted",
        "promotion_targets": ["venue", "instrument", "snapshot", "thesis", "forecast", "decision"],
        "tags": ["draft", "needs_enrichment", *tags],
    }

    common_passthrough = {
        k: args[k]
        for k in ("home", "agent_id", "model_id", "environment", "run_id")
        if k in args
    }

    capture_marker = _capture_content_hash(
        {
            "thought": thought,
            "title": args.get("title"),
            "tags": tags,
            "metadata_json": base_meta,
            "uri": args.get("uri"),
            "source_ref": args.get("source_ref"),
        }
    )

    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            source = _source_add_in_uow(
                {
                    **common_passthrough,
                    "kind": "note",
                    "stance": "neutral",
                    "title": args.get("title") or "Market idea capture",
                    "note": thought,
                    "summary": thought[:500],
                    "uri": args.get("uri"),
                    "ref": args.get("source_ref"),
                    "captured_at": captured_at,
                    "metadata_json": {**provenance_meta, "idea_capture_hash": capture_marker},
                    "content_hash": capture_marker,
                    "hash_algorithm": "sha256",
                    "idempotency_key": _child_key(idempotency_key, "source"),
                    "_allow_no_idempotency": args.get("_allow_no_idempotency"),
                },
                ctx,
                uow,
            )

            memory = _memory_retain_in_uow(
                {
                    **common_passthrough,
                    "node_type": "observation",
                    "title": args.get("title") or "Draft market idea (needs enrichment)",
                    "body": thought,
                    "importance": args.get("importance", 5),
                    "confidence_base": args.get("confidence_base", 0.5),
                    "valid_from": captured_at,
                    "meta_json": {
                        **provenance_meta,
                        "source_id": source["id"],
                        "idea_capture_hash": capture_marker,
                    },
                    "idempotency_key": _child_key(idempotency_key, "memory"),
                    "_allow_no_idempotency": args.get("_allow_no_idempotency"),
                },
                ctx,
                uow,
                node_type="observation",
            )

            attach = _source_attach_to_memory_node_in_uow(
                {
                    **common_passthrough,
                    "source_id": source["id"],
                    "target_id": memory["id"],
                    "metadata_json": {
                        "trade_trace_flow": "idea.capture",
                        "provenance_role": "raw_capture_source",
                    },
                    "idempotency_key": _child_key(idempotency_key, "source-memory-edge"),
                    "_allow_no_idempotency": args.get("_allow_no_idempotency"),
                },
                ctx,
                uow,
            )
    finally:
        db.close()

    return {
        "capture_state": "draft_needs_enrichment",
        "source_id": source["id"],
        "memory_node_id": memory["id"],
        "source_memory_edge_id": attach["id"],
        "created_at": memory["created_at"],
        "provenance": {
            "raw_capture": {"kind": "source", "id": source["id"]},
            "draft_observation": {"kind": "memory_node", "id": memory["id"]},
            "edge": {"kind": "edge", "id": attach["id"], "edge_type": attach["edge_type"]},
        },
        "no_advice_boundary": {
            "external_fetch_performed": False,
            "trade_execution_performed": False,
            "advice_generated": False,
            "note": "This stores your thought locally for later enrichment; it is not investment advice.",
        },
        "next_actions": [
            "Use venue.add if the venue is not already recorded.",
            "Use instrument.add with metadata_json.provenance.source_id and/or attach the source to the promoted row.",
            "Use snapshot.add only with manually supplied market data; no external data was fetched by idea.capture.",
            "Use thesis.add / forecast.add / decision.add when ready, carrying metadata_json.draft_memory_node_id and metadata_json.raw_source_id.",
            "Use source.attach_to_thesis / source.attach_to_forecast / source.attach_to_decision to preserve source provenance on promoted rows.",
            "Use memory.link from this memory_node to promoted rows with edge_type='derived_from' or 'about' where appropriate.",
        ],
    }


def register_idea_tools(registry: ToolRegistry) -> None:
    """Register capture-now/enrich-later idea tools."""

    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    ex = WRITE_TOOL_EXAMPLES.get("idea.capture", {})
    registry.register(
        "idea.capture",
        _idea_capture,
        is_write=True,
        example_minimal=ex.get("minimal"),
        example_rich=ex.get("rich"),
        json_schema=_IDEA_CAPTURE_SCHEMA,
        description=(
            "Capture a rough market thought now and enrich it later. Wrapper-first: "
            "writes local source + draft observation memory_node + provenance edge; "
            "does not fetch market data, trade, advise, or create a draft table."
        ),
        usage_summary="Record a rough market idea as local draft/needs_enrichment primitives and return promotion guidance.",
        examples=(
            "tt idea capture --thought 'Rough idea to investigate later' --idempotency-key <uuid>",
        ),
        common_failures=(
            "journal must be initialized first with journal.init.",
            "thought/title/metadata must not contain private auth material.",
        ),
        next_actions=(
            "Promote later with venue.add, instrument.add, snapshot.add, thesis.add, forecast.add, and/or decision.add while carrying source_id and memory_node_id in metadata_json.",
        ),
    )
