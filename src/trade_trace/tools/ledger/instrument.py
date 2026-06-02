"""`instrument.add` handler.

Extracted from the monolithic `tools/ledger.py` per bead
trade-trace-dh3b. Folded into `market.bind` under the v0.0.2 catalog
(bead trade-trace-sx4n) — kept here until that rename lands so the
existing surface keeps working.
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
    normalize_timestamp,
    now_iso,
    reject_if_contains_secrets,
    require,
    store_metadata_json,
)
from trade_trace.tools.ledger._shared import examples_for


def _instrument_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    venue_id = require(args, "venue_id")
    asset_class = require(args, "asset_class")
    title = require(args, "title")
    # Scan long-form instrument free-text per bead trade-trace-7j1l.
    # Narrow enum / id fields (asset_class, currency_or_collateral,
    # external_id, symbol) are exempt: they pass through to controlled
    # vocabularies and rejecting common identifiers would break ledger
    # flow. resolution_criteria_text is the one true free-text field.
    reject_if_contains_secrets(title, field="title")
    reject_if_contains_secrets(
        args.get("resolution_criteria_text"), field="resolution_criteria_text",
    )
    idempotency_key = args.get("idempotency_key")
    expiration = normalize_timestamp(args, "expiration_or_resolution_at")
    metadata_json = store_metadata_json(args)
    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            payload_common = {
                "venue_id": venue_id,
                "external_id": args.get("external_id"),
                "symbol": args.get("symbol"),
                "title": title,
                "asset_class": asset_class,
                "currency_or_collateral": args.get("currency_or_collateral"),
                "expiration_or_resolution_at": expiration,
                "resolution_criteria_text": args.get("resolution_criteria_text"),
                "contract_multiplier": args.get("contract_multiplier"),
                "metadata_json": metadata_json,
            }
            replay = check_idempotency_replay(
                uow, event_type="instrument.created",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                inst_id = replay["id"]
                payload = {"id": inst_id, **payload_common}
                emit_event(
                    uow, event_type="instrument.created",
                    subject_kind="instrument", subject_id=inst_id,
                    payload=payload, actor_id=ctx.actor_id,
                    idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT created_at FROM instruments WHERE id = ?", (inst_id,)
                ).fetchone()
                return {
                    "id": inst_id, "venue_id": venue_id,
                    "asset_class": asset_class, "title": title,
                    "created_at": row[0],
                }

            inst_id = args.get("id") or new_id("ins")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO instruments(id, venue_id, external_id, symbol, title, "
                "asset_class, currency_or_collateral, expiration_or_resolution_at, "
                "resolution_criteria_text, contract_multiplier, metadata_json, "
                "created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    inst_id,
                    venue_id,
                    args.get("external_id"),
                    args.get("symbol"),
                    title,
                    asset_class,
                    args.get("currency_or_collateral"),
                    expiration,
                    args.get("resolution_criteria_text"),
                    args.get("contract_multiplier"),
                    metadata_json,
                    created_at,
                    ctx.actor_id,
                ),
            )
            payload = {"id": inst_id, **payload_common}
            emit_event(
                uow, event_type="instrument.created",
                subject_kind="instrument", subject_id=inst_id,
                payload=payload, actor_id=ctx.actor_id,
                idempotency_key=idempotency_key, ctx=ctx,
            )
    return {
        "id": inst_id,
        "venue_id": venue_id,
        "asset_class": asset_class,
        "title": title,
        "created_at": created_at,
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


def register_instrument_tools(registry: ToolRegistry) -> None:
    registry.register(
        "instrument.add",
        _instrument_add,
        is_write=True,
        json_schema=_INSTRUMENT_ADD_SCHEMA,
        **examples_for("instrument.add"),
    )
