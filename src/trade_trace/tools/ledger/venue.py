"""`venue.add` handler.

Extracted from the monolithic `tools/ledger.py` per bead
trade-trace-dh3b. The v0.0.2 catalog reconciliation (bead
trade-trace-sx4n) KILLs `venue.add` once `market.bind` lands, but the
handler stays here through the foundation phase so the existing tool
surface keeps working until `rooi` consolidates the catalog.
"""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    db_for_args,
    emit_event,
    new_id,
    now_iso,
    require,
    store_metadata_json,
)
from trade_trace.tools.ledger._shared import examples_for


def _venue_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    name = require(args, "name")
    kind = require(args, "kind")
    metadata_json = store_metadata_json(args)
    idempotency_key = args.get("idempotency_key")
    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="venue.created",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                venue_id = replay["id"]
                payload = {"id": venue_id, "name": name, "kind": kind,
                           "metadata_json": metadata_json}
                emit_event(
                    uow, event_type="venue.created",
                    subject_kind="venue", subject_id=venue_id,
                    payload=payload, actor_id=ctx.actor_id,
                    idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT name, kind, created_at FROM venues WHERE id = ?",
                    (venue_id,),
                ).fetchone()
                return {"id": venue_id, "name": row[0], "kind": row[1],
                        "created_at": row[2]}

            venue_id = args.get("id") or new_id("ven")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (venue_id, name, kind, metadata_json, created_at, ctx.actor_id),
            )
            payload = {"id": venue_id, "name": name, "kind": kind,
                       "metadata_json": metadata_json}
            emit_event(
                uow, event_type="venue.created",
                subject_kind="venue", subject_id=venue_id,
                payload=payload, actor_id=ctx.actor_id,
                idempotency_key=idempotency_key, ctx=ctx,
            )
    return {"id": venue_id, "name": name, "kind": kind, "created_at": created_at}


def register_venue_tools(registry: ToolRegistry) -> None:
    registry.register(
        "venue.add", _venue_add, is_write=True, **examples_for("venue.add"),
    )
