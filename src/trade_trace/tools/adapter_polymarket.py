"""Opt-in Polymarket adapter-backed v0.0.2 tools.

All outbound calls are isolated here and guarded by network.polymarket.enabled.
Disabled paths fail closed with ADAPTER_DISABLED except market.bind manual metadata,
which is implemented in market_bind.py.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from trade_trace.adapters.polymarket.cache import MARKET_CACHE_TTL_SECONDS
from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.adapters.polymarket.config import load_config
from trade_trace.adapters.polymarket.errors import AdapterError
from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    common_metadata,
    emit_event,
    new_id,
    now_iso,
    open_db_for_args,
    require,
    store_metadata_json,
)
from trade_trace.tools.errors import ToolError


def _tool_error(exc: AdapterError) -> ToolError:
    return ToolError(exc.code, exc.message, details=exc.details)


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _outcome_label(outcome: Any, external_id: str, index: int) -> str:
    if isinstance(outcome, str):
        return outcome.lower()
    if isinstance(outcome, dict):
        return str(outcome.get("name") or outcome.get("label") or outcome.get("outcome") or "").lower()
    raise ToolError(
        ErrorCode.ADAPTER_PROTOCOL_ERROR,
        "Polymarket adapter outcome elements must be objects or strings",
        details={"external_id": external_id, "outcome_index": index, "outcome_type": type(outcome).__name__},
    )


def _optional_float(value: Any, field: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ToolError(
            ErrorCode.ADAPTER_PROTOCOL_ERROR,
            "Polymarket book field must be numeric",
            details={"field": field, "value": value},
        ) from exc


def _market_cache_hit(state: str | None, metadata_json: str | None, created_at: str | None, *, now: str) -> bool:
    ttl = MARKET_CACHE_TTL_SECONDS.get(state or "")
    if ttl is None:
        return True
    if not ttl:
        return False
    try:
        metadata = json.loads(metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    cached_at = _parse_ts(metadata.get("adapter_cached_at") or created_at)
    now_dt = _parse_ts(now)
    if cached_at is None or now_dt is None:
        return False
    return (now_dt - cached_at).total_seconds() < ttl


def _market_payload(raw: dict[str, Any], external_id: str) -> dict[str, Any]:
    outcomes = raw.get("outcomes") or raw.get("tokens") or []
    if raw.get("market_type") == "scalar" or raw.get("type") == "scalar" or raw.get("isScalar"):
        raise ToolError(ErrorCode.ADAPTER_PROTOCOL_ERROR, "Polymarket scalar markets are not supported in v0.0.2", details={"external_id": external_id, "market_type": "scalar"})
    if len(outcomes) not in (0, 2):
        raise ToolError(ErrorCode.ADAPTER_PROTOCOL_ERROR, "Polymarket adapter accepts only binary markets in v0.0.2", details={"external_id": external_id, "outcome_count": len(outcomes)})
    labels = [_outcome_label(o, external_id, idx) for idx, o in enumerate(outcomes)]
    if labels and set(labels) != {"yes", "no"}:
        raise ToolError(ErrorCode.ADAPTER_PROTOCOL_ERROR, "Polymarket adapter accepts only YES/NO binary markets", details={"external_id": external_id, "labels": labels})
    state = "open"
    if raw.get("voided") or raw.get("outcome", {}).get("status") == "void":
        state = "voided"
    elif raw.get("ambiguous") or raw.get("outcome", {}).get("status") == "ambiguous":
        state = "ambiguous"
    elif raw.get("resolved") or raw.get("closed") and raw.get("winningOutcome"):
        state = "resolved"
    elif raw.get("closed"):
        state = "closed_for_trading"
    mechanism = "amm" if raw.get("amm") or raw.get("ammCurve") or raw.get("mechanism") == "amm" else "clob"
    out = raw.get("outcome") or {}
    return {
        "source": "polymarket", "external_id": external_id,
        "title": raw.get("title") or raw.get("question"), "question": raw.get("question") or raw.get("title"),
        "url": raw.get("url") or raw.get("marketUrl"), "state": state, "mechanism": mechanism,
        "resolution_source": out.get("resolution_source") or ("arbitration" if raw.get("disputed") else "market_contract"),
        "ambiguity_kind": out.get("ambiguity_kind"), "bound_via": "adapter",
        "opened_at": raw.get("startDate") or raw.get("opened_at"), "close_at": raw.get("endDate") or raw.get("close_at"),
        "closed_for_trading_at": raw.get("closed_for_trading_at"), "resolving_at": raw.get("resolving_at"),
        "resolved_at": raw.get("resolved_at") or raw.get("resolvedAt"), "voided_at": raw.get("voided_at"),
        "ambiguous_at": raw.get("ambiguous_at"), "venue_metadata_json": _json(raw), "metadata_json": _json({"adapter": "polymarket"}),
    }


def _fetch_market(client: PolymarketClient, external_id: str) -> dict[str, Any]:
    raw = client.gamma_get(f"/markets/{external_id}")
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if isinstance(raw, dict) and "market" in raw and isinstance(raw["market"], dict):
        raw = raw["market"]
    if not isinstance(raw, dict) or not raw:
        raise ToolError(ErrorCode.ADAPTER_PROTOCOL_ERROR, "Gamma API returned no market object", details={"external_id": external_id})
    return raw


def _upsert_market(args: dict[str, Any], ctx: ToolContext, *, refresh_market_id: str | None = None) -> dict[str, Any]:
    db = open_db_for_args(args)
    try:
        cfg = load_config(db.connection)
        client = PolymarketClient(cfg)
        try:
            if refresh_market_id:
                row = db.connection.execute("SELECT external_id,state,metadata_json,created_at FROM markets WHERE id=?", (refresh_market_id,)).fetchone()
                if not row:
                    raise ToolError(ErrorCode.NOT_FOUND, "market_id not found", details={"market_id": refresh_market_id})
                external_id = row[0]
                current_now = now_iso()
                if _market_cache_hit(row[1], row[2], row[3], now=current_now):
                    cached = db.connection.execute("SELECT id,source,external_id,title,question,url,state,mechanism,resolution_source,ambiguity_kind,bound_via,metadata_json,venue_metadata_json,created_at FROM markets WHERE id=?", (refresh_market_id,)).fetchone()
                    return {
                        "id": cached[0],
                        "source": cached[1],
                        "external_id": cached[2],
                        "title": cached[3],
                        "question": cached[4],
                        "url": cached[5],
                        "state": cached[6],
                        "mechanism": cached[7],
                        "resolution_source": cached[8],
                        "ambiguity_kind": cached[9],
                        "bound_via": cached[10],
                        "metadata_json": cached[11],
                        "venue_metadata_json": cached[12],
                        "created_at": cached[13],
                        "cache_hit": True,
                        "state_changed": False,
                    }
            else:
                external_id = require(args, "external_id")
            payload = _market_payload(_fetch_market(client, str(external_id)), str(external_id))
        except AdapterError as exc:
            raise _tool_error(exc) from exc
        with UnitOfWork(db.connection) as uow:
            existing = uow.conn.execute("SELECT id,state,mechanism,resolution_source,ambiguity_kind FROM markets WHERE source=? AND external_id=?", ("polymarket", str(external_id))).fetchone()
            market_id = refresh_market_id or (existing[0] if existing else args.get("id") or new_id("mkt"))
            created_at = now_iso()
            payload["metadata_json"] = _json({"adapter": "polymarket", "adapter_cached_at": created_at, "cache_ttl_seconds": MARKET_CACHE_TTL_SECONDS.get(str(payload.get("state") or ""))})
            if existing:
                changed = any(existing[i] != payload[k] for i, k in enumerate(("id","state","mechanism","resolution_source","ambiguity_kind")) if k != "id")
                uow.execute("UPDATE markets SET title=?,question=?,url=?,state=?,mechanism=?,resolution_source=?,ambiguity_kind=?,bound_via='adapter',opened_at=?,close_at=?,closed_for_trading_at=?,resolving_at=?,resolved_at=?,voided_at=?,ambiguous_at=?,venue_metadata_json=?,metadata_json=? WHERE id=?", (payload["title"],payload["question"],payload["url"],payload["state"],payload["mechanism"],payload["resolution_source"],payload["ambiguity_kind"],payload["opened_at"],payload["close_at"],payload["closed_for_trading_at"],payload["resolving_at"],payload["resolved_at"],payload["voided_at"],payload["ambiguous_at"],payload["venue_metadata_json"],payload["metadata_json"],market_id))
            else:
                changed = True
                uow.execute("INSERT INTO markets(id,source,external_id,title,question,url,state,mechanism,resolution_source,ambiguity_kind,bound_via,opened_at,close_at,closed_for_trading_at,resolving_at,resolved_at,voided_at,ambiguous_at,venue_metadata_json,metadata_json,created_at,actor_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (market_id,"polymarket",str(external_id),payload["title"],payload["question"],payload["url"],payload["state"],payload["mechanism"],payload["resolution_source"],payload["ambiguity_kind"],"adapter",payload["opened_at"],payload["close_at"],payload["closed_for_trading_at"],payload["resolving_at"],payload["resolved_at"],payload["voided_at"],payload["ambiguous_at"],payload["venue_metadata_json"],payload["metadata_json"],created_at,ctx.actor_id))
            out = {"id": market_id, **payload, "state_changed": changed}
            emit_event(uow, event_type="market.refreshed" if refresh_market_id else "market.bound", subject_kind="market", subject_id=market_id, payload=out, actor_id=ctx.actor_id, idempotency_key=args.get("idempotency_key"), ctx=ctx)
            return out
    finally:
        db.close()


def _market_refresh(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return _upsert_market(args, ctx, refresh_market_id=require(args, "market_id"))


def _ensure_market_instrument(uow: UnitOfWork, market_id: str, *, actor_id: str) -> None:
    """Ensure public market IDs satisfy legacy snapshot/outcome FKs.

    v0.0.2 public tools take `market_id`, while the existing ledger storage still
    stores snapshots/outcomes under `instrument_id`. Create an idempotent
    compatibility instrument with the same ID as the market before writing those
    tables. This is local-only bookkeeping, not a new public venue/instrument
    surface.
    """

    row = uow.conn.execute(
        "SELECT source, external_id, title, question, close_at, metadata_json FROM markets WHERE id=?",
        (market_id,),
    ).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "market_id not found", details={"market_id": market_id})
    source, external_id, title, question, close_at, metadata_json = row
    created_at = now_iso()
    venue_id = f"venue_{source}"
    uow.execute(
        "INSERT OR IGNORE INTO venues(id,name,kind,metadata_json,created_at,actor_id) VALUES (?,?,?,?,?,?)",
        (venue_id, str(source), "prediction_market", _json({"source": source}), created_at, actor_id),
    )
    uow.execute(
        "INSERT OR IGNORE INTO instruments(id,venue_id,external_id,symbol,title,asset_class,currency_or_collateral,expiration_or_resolution_at,resolution_criteria_text,contract_multiplier,metadata_json,created_at,actor_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            market_id,
            venue_id,
            external_id,
            external_id,
            title or question or external_id or market_id,
            "prediction_market",
            "USDC",
            close_at,
            question,
            1.0,
            metadata_json or "{}",
            created_at,
            actor_id,
        ),
    )



def _snapshot_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    bid = raw.get("bestBid") or raw.get("bid")
    ask = raw.get("bestAsk") or raw.get("ask")
    price = raw.get("price") or raw.get("last") or raw.get("mid")
    bidf = _optional_float(bid, "bestBid")
    askf = _optional_float(ask, "bestAsk")
    pricef = _optional_float(price, "price")
    mid = (bidf + askf) / 2 if bidf is not None and askf is not None else pricef
    return {"price": pricef if pricef is not None else mid, "bid": bidf, "ask": askf, "mid": mid, "spread": (askf-bidf) if bidf is not None and askf is not None else None, "volume": raw.get("volume"), "open_interest": raw.get("openInterest"), "implied_probability": raw.get("impliedProbability") or mid, "liquidity_depth_json": raw.get("book") or raw.get("liquidity") or raw}


def _insert_snapshot(args: dict[str, Any], ctx: ToolContext, market_id: str, snap: dict[str, Any], captured_at: str) -> dict[str, Any]:
    seg = common_metadata(args)
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            _ensure_market_instrument(uow, market_id, actor_id=ctx.actor_id)
            sid = args.get("id") or new_id("snp")
            created_at = now_iso()
            uow.execute("INSERT INTO snapshots(id,instrument_id,captured_at,source,source_url,price,bid,ask,mid,spread,volume,open_interest,implied_probability,liquidity_depth_json,agent_id,model_id,environment,run_id,metadata_json,created_at,actor_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (sid,market_id,captured_at,"polymarket",args.get("source_url"),snap.get("price"),snap.get("bid"),snap.get("ask"),snap.get("mid"),snap.get("spread"),snap.get("volume"),snap.get("open_interest"),snap.get("implied_probability"),_json(snap.get("liquidity_depth_json")),seg["agent_id"],seg["model_id"],seg["environment"],seg["run_id"],store_metadata_json(args),created_at,ctx.actor_id))
            emit_event(uow,event_type="snapshot.added",subject_kind="snapshot",subject_id=sid,payload={"id":sid,"instrument_id":market_id,"captured_at":captured_at,"source":"polymarket"},actor_id=ctx.actor_id,idempotency_key=args.get("idempotency_key"),ctx=ctx)
            return {"id": sid, "instrument_id": market_id, "captured_at": captured_at, **snap}
    finally:
        db.close()


def _snapshot_fetch(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if args.get("at") not in (None, "now"):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "snapshot.fetch supports only at=now in v0.0.2", details={"field":"at"})
    db = open_db_for_args(args)
    try:
        client = PolymarketClient(load_config(db.connection))
        market_id = require(args,"market_id")
        row = db.connection.execute("SELECT external_id FROM markets WHERE id=?", (market_id,)).fetchone()
        if not row:
            raise ToolError(ErrorCode.NOT_FOUND,"market_id not found",details={"market_id":market_id})
        try:
            raw = client.gamma_get(f"/markets/{row[0]}/book")
        except AdapterError as exc:
            raise _tool_error(exc) from exc
    finally:
        db.close()
    return _insert_snapshot(args, ctx, market_id, _snapshot_from_raw(raw if isinstance(raw, dict) else {}), now_iso())


def _snapshot_fetch_series(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    # v0.0.2 adapter primitive stores returned points; Gamma path is intentionally generic for fixture-backed tests.
    db = open_db_for_args(args)
    try:
        client = PolymarketClient(load_config(db.connection))
        market_id=require(args,"market_id")
        row = db.connection.execute("SELECT external_id FROM markets WHERE id=?", (market_id,)).fetchone()
        if not row:
            raise ToolError(ErrorCode.NOT_FOUND,"market_id not found",details={"market_id":market_id})
        try:
            raw = client.gamma_get(f"/markets/{row[0]}/prices?from={require(args,'from')}&to={require(args,'to')}")
        except AdapterError as exc:
            raise _tool_error(exc) from exc
    finally:
        db.close()
    points = raw.get("points", raw) if isinstance(raw, dict) else raw
    items = []
    for idx, point in enumerate(points or []):
        item_args = dict(args)
        item_args["idempotency_key"] = f"{args.get('idempotency_key', 'snapshot.fetch_series')}:{idx}"
        items.append(
            _insert_snapshot(
                item_args,
                ctx,
                market_id,
                _snapshot_from_raw(point),
                point.get("captured_at") or point.get("timestamp") or now_iso(),
            )
        )
    return {"items": items, "count": len(items)}


def _outcome_fetch(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    db = open_db_for_args(args)
    try:
        client = PolymarketClient(load_config(db.connection))
        market_id=require(args,"market_id")
        row = db.connection.execute("SELECT venue_metadata_json FROM markets WHERE id=?", (market_id,)).fetchone()
        if not row:
            raise ToolError(ErrorCode.NOT_FOUND,"market_id not found",details={"market_id":market_id})
        meta = json.loads(row[0] or "{}")
        out = meta.get("outcome") or {}
        existing = db.connection.execute("SELECT id FROM outcomes WHERE instrument_id=? AND source='polymarket'", (market_id,)).fetchone()
        if existing:
            return {"id": existing[0], "instrument_id": market_id, "idempotent_replay": True, "cache_hit": True}
        try:
            tx_hash = out.get("tx_hash") or meta.get("resolution_tx")
            rpc = client.polygon_rpc("eth_getTransactionReceipt", [tx_hash]) if tx_hash else client.check_resolution_available()
        except AdapterError as exc:
            raise _tool_error(exc) from exc
        status = out.get("status") or ("void" if meta.get("voided") else "resolved_final")
        label = out.get("label") or meta.get("winningOutcome") or meta.get("winning_outcome") or "unknown"
    finally:
        db.close()
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            _ensure_market_instrument(uow, market_id, actor_id=ctx.actor_id)
            oid=args.get("id") or new_id("out")
            created_at=now_iso()
            metadata=_json({"polygon_rpc": rpc, "tx_hash": tx_hash})
            uow.execute("INSERT INTO outcomes(id,instrument_id,resolved_at,outcome_label,outcome_value,status,source,confidence,agent_id,model_id,environment,run_id,metadata_json,created_at,actor_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (oid,market_id,out.get("resolved_at") or now_iso(),label,out.get("value"),status,"polymarket",out.get("confidence"),None,None,None,None,metadata,created_at,ctx.actor_id))
            emit_event(uow,event_type="outcome.recorded",subject_kind="outcome",subject_id=oid,payload={"id":oid,"instrument_id":market_id,"status":status,"outcome_label":label},actor_id=ctx.actor_id,idempotency_key=args.get("idempotency_key"),ctx=ctx)
            return {"id":oid,"instrument_id":market_id,"status":status,"outcome_label":label,"metadata_json":metadata}
    finally:
        db.close()


def register_adapter_polymarket_tools(registry: ToolRegistry) -> None:
    registry.register("market.refresh", _market_refresh, is_write=True, example_minimal={"market_id":"mkt_..."})
    registry.register("snapshot.fetch", _snapshot_fetch, is_write=True, example_minimal={"market_id":"mkt_...","at":"now"})
    registry.register("snapshot.fetch_series", _snapshot_fetch_series, is_write=True, example_minimal={"market_id":"mkt_...","from":"2026-01-01T00:00:00Z","to":"2026-01-02T00:00:00Z"})
    registry.register("outcome.fetch", _outcome_fetch, is_write=True, example_minimal={"market_id":"mkt_..."})
