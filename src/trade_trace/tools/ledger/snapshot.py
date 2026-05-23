"""`snapshot.add` handler.

Extracted from the monolithic `tools/ledger.py` per bead
trade-trace-dh3b. Stays as the manual snapshot path under v0.0.2 with
`snapshot.fetch` / `snapshot.fetch_series` joining it as the
adapter-driven primitives (bead trade-trace-sx4n catalog).
"""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.tool_registry import ToolContext
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    common_metadata,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    open_db_for_args,
    require,
    store_metadata_json,
)


def _snapshot_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    instrument_id = require(args, "instrument_id")
    captured_at = normalize_timestamp(args, "captured_at", required=True)
    idempotency_key = args.get("idempotency_key")
    source = args.get("source", "manual")
    liquidity_depth_json = store_metadata_json(args, "liquidity_depth_json")
    metadata_json = store_metadata_json(args)
    seg = common_metadata(args)
    payload_common = {
        "instrument_id": instrument_id,
        "captured_at": captured_at,
        "source": source,
        "source_url": args.get("source_url"),
        "price": args.get("price"),
        "bid": args.get("bid"),
        "ask": args.get("ask"),
        "mid": args.get("mid"),
        "spread": args.get("spread"),
        "volume": args.get("volume"),
        "open_interest": args.get("open_interest"),
        "implied_probability": args.get("implied_probability"),
        "liquidity_depth_json": liquidity_depth_json,
        "agent_id": seg["agent_id"],
        "model_id": seg["model_id"],
        "environment": seg["environment"],
        "run_id": seg["run_id"],
        "metadata_json": metadata_json,
    }
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="snapshot.added",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                snap_id = replay["id"]
                emit_event(
                    uow, event_type="snapshot.added",
                    subject_kind="snapshot", subject_id=snap_id,
                    payload={"id": snap_id, **payload_common},
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                )
                return {"id": snap_id, "instrument_id": instrument_id,
                        "captured_at": captured_at}

            snap_id = args.get("id") or new_id("snp")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO snapshots(id, instrument_id, captured_at, source, source_url, "
                "price, bid, ask, mid, spread, volume, open_interest, implied_probability, "
                "liquidity_depth_json, agent_id, model_id, environment, run_id, "
                "metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snap_id, instrument_id, captured_at, source,
                    args.get("source_url"), args.get("price"), args.get("bid"),
                    args.get("ask"), args.get("mid"), args.get("spread"),
                    args.get("volume"), args.get("open_interest"),
                    args.get("implied_probability"),
                    liquidity_depth_json,
                    seg["agent_id"], seg["model_id"], seg["environment"], seg["run_id"],
                    metadata_json, created_at, ctx.actor_id,
                ),
            )
            emit_event(
                uow, event_type="snapshot.added",
                subject_kind="snapshot", subject_id=snap_id,
                payload={"id": snap_id, **payload_common},
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
    finally:
        db.close()
    return {"id": snap_id, "instrument_id": instrument_id, "captured_at": captured_at}
