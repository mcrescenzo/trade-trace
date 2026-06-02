"""`thesis.add` handler.

Extracted from the monolithic `tools/ledger.py` per bead
trade-trace-dh3b. Folded into `forecast.add` as the `rationale_body`
field under v0.0.2 (bead trade-trace-sx4n catalog); the `theses` table
itself is dropped by bead trade-trace-4lki. Kept here through the
foundation phase so the existing surface keeps working.
"""

from __future__ import annotations

from typing import Any

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
from trade_trace.tools.ledger._shared import examples_for


def _thesis_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    instrument_id = require(args, "instrument_id")
    side = require(args, "side")
    body = require(args, "body")
    reject_if_contains_secrets(body, field="body")
    # Long-form thesis free-text fields per bead trade-trace-7j1l;
    # narrow enum-shaped columns (side, confidence_label, …) are
    # exempt by design (see docs/architecture/security.md §6.5).
    for field in ("falsification_criteria", "exit_triggers", "risk_notes",
                  "invalidation_condition", "risk_unit_label"):
        reject_if_contains_secrets(args.get(field), field=field)
    parent = args.get("parent_thesis_id")
    version = args.get("version", 1)
    idempotency_key = args.get("idempotency_key")
    time_horizon_at = normalize_timestamp(args, "time_horizon_at")
    valid_to = normalize_timestamp(args, "valid_to")
    seg = common_metadata(args)
    metadata_json = store_metadata_json(args)

    def _payload(tid: str, valid_from: str) -> dict[str, Any]:
        return {
            "id": tid,
            "instrument_id": instrument_id,
            "version": version,
            "parent_thesis_id": parent,
            "side": side,
            "time_horizon_at": time_horizon_at,
            "confidence_label": args.get("confidence_label"),
            "body": body,
            "falsification_criteria": args.get("falsification_criteria"),
            "exit_triggers": args.get("exit_triggers"),
            "risk_notes": args.get("risk_notes"),
            "strategy_id": args.get("strategy_id"),
            "valid_from": valid_from,
            "valid_to": valid_to,
            "metadata_json": metadata_json,
        }

    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="thesis.created",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                thesis_id = replay["id"]
                row = uow.conn.execute(
                    "SELECT valid_from, created_at FROM theses WHERE id = ?",
                    (thesis_id,),
                ).fetchone()
                emit_event(
                    uow, event_type="thesis.created",
                    subject_kind="thesis", subject_id=thesis_id,
                    payload=_payload(thesis_id, row[0]),
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                )
                return {"id": thesis_id, "instrument_id": instrument_id,
                        "version": version, "side": side, "created_at": row[1]}

            thesis_id = args.get("id") or new_id("th")
            created_at = now_iso()
            valid_from = normalize_timestamp(args, "valid_from") or created_at
            uow.execute(
                "INSERT INTO theses(id, instrument_id, version, parent_thesis_id, side, "
                "time_horizon_at, confidence_label, body, falsification_criteria, "
                "exit_triggers, risk_notes, strategy_id, valid_from, valid_to, "
                "agent_id, model_id, environment, run_id, metadata_json, "
                "created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    thesis_id, instrument_id, version, parent, side,
                    time_horizon_at, args.get("confidence_label"), body,
                    args.get("falsification_criteria"), args.get("exit_triggers"),
                    args.get("risk_notes"), args.get("strategy_id"),
                    valid_from, valid_to,
                    seg["agent_id"], seg["model_id"], seg["environment"], seg["run_id"],
                    metadata_json, created_at, ctx.actor_id,
                ),
            )
            emit_event(
                uow, event_type="thesis.created",
                subject_kind="thesis", subject_id=thesis_id,
                payload=_payload(thesis_id, valid_from),
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
            # Emit a `supersedes` edge if parent thesis specified.
            if parent:
                edge_id = new_id("edg")
                uow.execute(
                    "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
                    "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (edge_id, "thesis", thesis_id, "thesis", parent,
                     "supersedes", created_at, ctx.actor_id),
                )
                emit_event(
                    uow, event_type="edge.created",
                    subject_kind="edge", subject_id=edge_id,
                    payload={
                        "id": edge_id, "source_kind": "thesis", "source_id": thesis_id,
                        "target_kind": "thesis", "target_id": parent,
                        "edge_type": "supersedes",
                    },
                    actor_id=ctx.actor_id, idempotency_key=None, ctx=ctx,
                )
    return {"id": thesis_id, "instrument_id": instrument_id, "version": version,
            "side": side, "created_at": created_at}


def register_thesis_tools(registry: ToolRegistry) -> None:
    registry.register(
        "thesis.add", _thesis_add, is_write=True, **examples_for("thesis.add"),
    )
