"""Local-only `market.bind` tool for the v0.0.2 PM catalog.

This is intentionally a manual/local binding surface. It records market metadata
in the existing `markets` table and makes no adapter, HTTP, scheduler, broker,
wallet, or market-data calls.
"""

from __future__ import annotations

import json
from typing import Any

from trade_trace.adapters.polymarket.config import load_config
from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    emit_event,
    new_id,
    now_iso,
    open_db_for_args,
    require,
    store_metadata_json,
)
from trade_trace.tools.adapter_polymarket import _upsert_market
from trade_trace.tools.errors import ToolError

_ALLOWED_SOURCES = {"polymarket", "kalshi", "manifold", "predictit", "manual"}
_ALLOWED_STATES = {"open", "closed_for_trading", "resolving", "resolved", "voided", "ambiguous"}
_ALLOWED_MECHANISMS = {"clob", "amm", "scalar", "hybrid"}
_ALLOWED_RESOLUTION_SOURCES = {"market_contract", "oracle_feed", "manual_review", "arbitration"}
_ALLOWED_AMBIGUITY_KINDS = {
    "market_rules_unclear",
    "oracle_dispute",
    "event_happened_but_label_ambiguous",
    "event_null_and_void",
}


def _optional_enum(args: dict[str, Any], field: str, allowed: set[str]) -> str | None:
    value = args.get(field)
    if value is None:
        return None
    if value not in allowed:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"{field} must be one of {sorted(allowed)!r}",
            details={"field": field, "value": value, "allowed": sorted(allowed)},
        )
    return str(value)


def _required_enum(args: dict[str, Any], field: str, allowed: set[str]) -> str:
    value = require(args, field)
    if value not in allowed:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"{field} must be one of {sorted(allowed)!r}",
            details={"field": field, "value": value, "allowed": sorted(allowed)},
        )
    return str(value)


def _json_text(value: Any, *, field: str) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{field} must be valid JSON object text",
                details={"field": field, "decode_error": str(exc)},
            ) from exc
        if not isinstance(parsed, dict):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{field} must be a JSON object",
                details={"field": field, "actual": type(parsed).__name__},
            )
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    if not isinstance(value, dict):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"{field} must be a JSON object",
            details={"field": field, "actual": type(value).__name__},
        )
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _market_bind(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Bind a local market row without any outbound network access."""

    source = _required_enum(args, "source", _ALLOWED_SOURCES)
    external_id = require(args, "external_id")
    if source == "polymarket" and args.get("bound_via") != "manual":
        probe_db = open_db_for_args(args)
        try:
            if load_config(probe_db.connection).enabled:
                return _upsert_market(args, ctx)
        finally:
            probe_db.close()
    state = _required_enum(args, "state", _ALLOWED_STATES)
    mechanism = _required_enum(args, "mechanism", _ALLOWED_MECHANISMS)
    resolution_source = _optional_enum(args, "resolution_source", _ALLOWED_RESOLUTION_SOURCES)
    ambiguity_kind = _optional_enum(args, "ambiguity_kind", _ALLOWED_AMBIGUITY_KINDS)
    bound_via = args.get("bound_via") or "manual"
    if bound_via != "manual":
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "market.bind is local/manual only in v0.0.2; adapters are implemented separately",
            details={"field": "bound_via", "value": bound_via, "allowed": ["manual"]},
        )
    idempotency_key = args.get("idempotency_key")
    metadata_json = store_metadata_json(args)
    venue_metadata_json = _json_text(args.get("venue_metadata_json"), field="venue_metadata_json")
    market_id = args.get("id") or new_id("mkt")
    created_at = now_iso()

    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow,
                event_type="market.bound",
                actor_id=ctx.actor_id,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                replay_id = replay.get("id") or replay.get("market_id")
                row = uow.conn.execute(
                    "SELECT id, source, external_id, title, question, url, state, mechanism, "
                    "resolution_source, ambiguity_kind, bound_via, opened_at, close_at, "
                    "closed_for_trading_at, resolving_at, resolved_at, voided_at, ambiguous_at, "
                    "venue_metadata_json, metadata_json, created_at, actor_id "
                    "FROM markets WHERE id = ?",
                    (replay_id,),
                ).fetchone()
                if row is not None:
                    replay_payload = dict(replay)
                    emit_event(
                        uow,
                        event_type="market.bound",
                        subject_kind="market",
                        subject_id=str(replay_id),
                        payload=replay_payload,
                        actor_id=ctx.actor_id,
                        idempotency_key=idempotency_key,
                        ctx=ctx,
                    )
                    return _market_row_dict(row) | {"idempotent_replay": True}

            existing = uow.conn.execute(
                "SELECT id, source, external_id, title, question, url, state, mechanism, "
                "resolution_source, ambiguity_kind, bound_via, opened_at, close_at, "
                "closed_for_trading_at, resolving_at, resolved_at, voided_at, ambiguous_at, "
                "venue_metadata_json, metadata_json, created_at, actor_id "
                "FROM markets WHERE source = ? AND external_id = ?",
                (source, external_id),
            ).fetchone()
            if existing is not None:
                payload = _market_row_dict(existing) | {"already_bound": True}
                existing_id = str(existing[0])
                emit_event(
                    uow,
                    event_type="market.bound",
                    subject_kind="market",
                    subject_id=existing_id,
                    payload=payload,
                    actor_id=ctx.actor_id,
                    idempotency_key=idempotency_key,
                    ctx=ctx,
                )
                return payload

            uow.execute(
                """
                INSERT INTO markets(
                    id, source, external_id, title, question, url, state, mechanism,
                    resolution_source, ambiguity_kind, bound_via, opened_at, close_at,
                    closed_for_trading_at, resolving_at, resolved_at, voided_at,
                    ambiguous_at, venue_metadata_json, metadata_json, created_at, actor_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market_id,
                    source,
                    external_id,
                    args.get("title"),
                    args.get("question"),
                    args.get("url"),
                    state,
                    mechanism,
                    resolution_source,
                    ambiguity_kind,
                    bound_via,
                    args.get("opened_at"),
                    args.get("close_at"),
                    args.get("closed_for_trading_at"),
                    args.get("resolving_at"),
                    args.get("resolved_at"),
                    args.get("voided_at"),
                    args.get("ambiguous_at"),
                    venue_metadata_json,
                    metadata_json,
                    created_at,
                    ctx.actor_id,
                ),
            )
            payload = {
                "id": market_id,
                "source": source,
                "external_id": external_id,
                "title": args.get("title"),
                "question": args.get("question"),
                "url": args.get("url"),
                "state": state,
                "mechanism": mechanism,
                "resolution_source": resolution_source,
                "ambiguity_kind": ambiguity_kind,
                "bound_via": bound_via,
                "metadata_json": metadata_json,
                "venue_metadata_json": venue_metadata_json,
                "created_at": created_at,
            }
            emit_event(
                uow,
                event_type="market.bound",
                subject_kind="market",
                subject_id=market_id,
                payload=payload,
                actor_id=ctx.actor_id,
                idempotency_key=idempotency_key,
                ctx=ctx,
            )
            return payload
    finally:
        db.close()


def _market_row_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "source": row[1],
        "external_id": row[2],
        "title": row[3],
        "question": row[4],
        "url": row[5],
        "state": row[6],
        "mechanism": row[7],
        "resolution_source": row[8],
        "ambiguity_kind": row[9],
        "bound_via": row[10],
        "opened_at": row[11],
        "close_at": row[12],
        "closed_for_trading_at": row[13],
        "resolving_at": row[14],
        "resolved_at": row[15],
        "voided_at": row[16],
        "ambiguous_at": row[17],
        "venue_metadata_json": row[18],
        "metadata_json": row[19],
        "created_at": row[20],
        "actor_id": row[21],
    }


def register_market_bind_tool(registry: ToolRegistry) -> None:
    registry.register(
        "market.bind",
        _market_bind,
        is_write=True,
        description=(
            "Bind a prediction/event market into the local markets table. "
            "Manual/local only: no network, adapter, broker, wallet, scheduler, or advice path."
        ),
        example_minimal={
            "source": "polymarket",
            "external_id": "example-market-1",
            "state": "open",
            "mechanism": "clob",
        },
        example_rich={
            "source": "polymarket",
            "external_id": "example-market-1",
            "title": "Will example happen?",
            "question": "Will example happen by 2026-12-31?",
            "url": "https://example.invalid/market/example-market-1",
            "state": "open",
            "mechanism": "clob",
            "resolution_source": "market_contract",
            "bound_via": "manual",
            "metadata_json": {"sources": []},
            "idempotency_key": "00000000-0000-4000-8000-marketbind01",
        },
    )
