"""First-class local paper fill ledger tools.

Paper fills are deterministic caller-supplied local evidence. This module has no
venue client, no private account fetch, no signing, no order placement, no
cancellation, and no custody/fund movement path.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES
from trade_trace.tools._helpers import (
    canonical_json as _canonical_json,
)
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    db_for_args,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    reject_credential_metadata,
    reject_if_contains_secrets,
    require,
    store_metadata_json,
)
from trade_trace.tools.errors import ToolError

_EVENT = "paper_fill.recorded"
_SCHEMA_VERSION = "paper_fill.v1"
_CONFIDENCE = {"low", "medium", "high", "unknown"}
_STALENESS = {"fresh", "stale", "missing", "unknown"}
_SELECT = "id, schema_version, semantic_key, material_hash, environment_label, account_label, market_id, instrument_id, pretrade_intent_id, side, outcome_side, requested_quantity, filled_quantity, remaining_quantity, limit_price, average_fill_price, fee_amount, slippage_cap_bps, quote_id, book_id, snapshot_id, snapshot_as_of, order_as_of, freshness_status, fill_status, conservative_fill_model, mark_source, mark_as_of, confidence_label, staleness_status, source_precedence, caveats_json, evidence_json, provenance_json, recorded_at, idempotency_key, actor_id"
_PAPER_EXPOSURE_BOUNDARY_CAVEAT = (
    "Paper-only local fill evidence and cost-basis math; imported/live account truth, "
    "live execution, settlement, redemption, fund movement, and trading advice are excluded."
)


def _json_arg(args: dict[str, Any], field: str, default: Any) -> Any:
    value = args.get(field, default)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            reject_if_contains_secrets(value, field=field)
            raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be valid JSON", details={"field": field}) from exc
    return value


def _list_arg(args: dict[str, Any], field: str) -> list[Any]:
    value = _json_arg(args, field, [])
    if not isinstance(value, list):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an array", details={"field": field})
    reject_credential_metadata(value, field=field)
    return value


def _dict_arg(args: dict[str, Any], field: str) -> dict[str, Any]:
    value = _json_arg(args, field, {})
    if not isinstance(value, dict):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an object", details={"field": field})
    reject_credential_metadata(value, field=field)
    return value


def _safe_text(args: dict[str, Any], field: str, *, required: bool = False) -> str | None:
    value = require(args, field) if required else args.get(field)
    if value is None:
        return None
    text = str(value)
    reject_if_contains_secrets(text, field=field)
    return text


def _decimal(value: Any, field: str, *, required: bool = True) -> Decimal | None:
    if value is None and not required:
        return None
    try:
        dec = Decimal(str(require({field: value}, field) if required else value))
    except (InvalidOperation, ValueError, OverflowError, TypeError) as exc:
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be numeric", details={"field": field, "code": "malformed_payload_quarantined"}) from exc
    if not dec.is_finite():
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be finite", details={"field": field, "code": "impossible_payload_quarantined"})
    return dec


def _non_negative_decimal(value: Any, field: str, *, required: bool = True) -> Decimal | None:
    dec = _decimal(value, field, required=required)
    if dec is not None and dec < 0:
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be non-negative", details={"field": field, "code": "impossible_payload_quarantined"})
    return dec


def _positive_decimal(value: Any, field: str, *, required: bool = True) -> Decimal | None:
    dec = _decimal(value, field, required=required)
    if dec is not None and dec <= 0:
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be positive", details={"field": field, "code": "impossible_payload_quarantined"})
    return dec


def _non_negative_int(value: Any, field: str, *, default: int | None = None) -> int:
    if value is None:
        if default is None:
            raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} is required", details={"field": field})
        value = default
    try:
        parsed = int(value)
    except (InvalidOperation, ValueError, OverflowError, TypeError) as exc:
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an integer", details={"field": field, "code": "malformed_payload_quarantined"}) from exc
    if parsed < 0:
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be non-negative", details={"field": field, "code": "impossible_payload_quarantined"})
    return parsed


def _dt(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(text).astimezone(UTC)


def _hash_material(material: dict[str, Any]) -> str:
    return hashlib.sha256(f"paper_fill:{_canonical_json(material)}".encode()).hexdigest()


def _model_fill(args: dict[str, Any], caveats: list[Any]) -> tuple[Decimal, Decimal | None, str, str]:
    side = str(require(args, "side"))
    qty = _positive_decimal(args.get("requested_quantity"), "requested_quantity")
    limit_price = _non_negative_decimal(args.get("limit_price"), "limit_price")
    if qty is None or limit_price is None:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "requested_quantity and limit_price are required")
    levels = _list_arg(args, "book_levels")
    if not levels:
        caveats.append({"code": "missing_depth_no_fill", "message": "No caller-supplied depth; conservative paper model records no fill."})
        return Decimal(0), None, "no_fill", "missing"
    snapshot_as_of = normalize_timestamp(args, "snapshot_as_of")
    order_as_of = normalize_timestamp(args, "order_as_of", required=True)
    freshness = "unknown"
    max_age = _non_negative_int(args.get("max_snapshot_age_seconds"), "max_snapshot_age_seconds", default=60)
    if snapshot_as_of and order_as_of:
        order_dt = _dt(order_as_of)
        snapshot_dt = _dt(snapshot_as_of)
        if order_dt is not None and snapshot_dt is not None:
            age = abs((order_dt - snapshot_dt).total_seconds())
            freshness = "fresh" if age <= max_age else "stale"
        if freshness == "stale":
            caveats.append({"code": "stale_depth_no_fill", "message": "Depth snapshot is stale; conservative paper model records no fill."})
            return Decimal(0), None, "no_fill", freshness
    filled = Decimal(0)
    notional = Decimal(0)
    for level in levels:
        if not isinstance(level, dict):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "book_levels entries must be objects")
        price = _non_negative_decimal(level.get("price"), "book_levels.price")
        available = _non_negative_decimal(level.get("quantity"), "book_levels.quantity")
        if price is None or available is None:
            raise ToolError(ErrorCode.VALIDATION_ERROR, "book level price/quantity invalid")
        fillable = price <= limit_price if side == "buy" else price >= limit_price
        if not fillable:
            continue
        take = min(qty - filled, available)
        filled += take
        notional += take * price
        if filled >= qty:
            break
    if filled == 0:
        caveats.append({"code": "limit_price_not_fillable", "message": "No supplied depth level met the paper limit price."})
        return filled, None, "no_fill", freshness
    avg = notional / filled
    ref = _decimal(args.get("reference_mid_price"), "reference_mid_price", required=False)
    cap = _non_negative_decimal(args.get("slippage_cap_bps"), "slippage_cap_bps", required=False)
    if ref and cap is not None and ref > 0:
        bps = ((avg - ref) / ref * Decimal(10000)) if side == "buy" else ((ref - avg) / ref * Decimal(10000))
        if bps > cap:
            caveats.append({"code": "slippage_cap_exceeded_conservative_fill", "message": "Computed paper fill exceeded caller slippage cap; conservative model records no fill."})
            return Decimal(0), None, "no_fill", freshness
    status = "full" if filled == qty else "partial"
    if status == "partial":
        caveats.append({"code": "insufficient_depth_partial_fill", "message": "Caller-supplied depth supported only a partial conservative paper fill."})
    return filled, avg, status, freshness


def _row_to_response(row: Any) -> dict[str, Any]:
    return {
        "id": row[0], "schema_version": row[1], "semantic_key": row[2], "material_hash": row[3],
        "environment_label": row[4], "account_label": row[5], "market_id": row[6], "instrument_id": row[7], "pretrade_intent_id": row[8],
        "side": row[9], "outcome_side": row[10], "requested_quantity": row[11], "filled_quantity": row[12], "remaining_quantity": row[13],
        "limit_price": row[14], "average_fill_price": row[15], "fee_amount": row[16], "slippage_cap_bps": row[17],
        "quote_id": row[18], "book_id": row[19], "snapshot_id": row[20], "snapshot_as_of": row[21], "order_as_of": row[22],
        "freshness_status": row[23], "fill_status": row[24], "conservative_fill_model": row[25], "mark_source": row[26],
        "mark_as_of": row[27], "confidence_label": row[28], "staleness_status": row[29], "source_precedence": row[30],
        "caveats": json.loads(row[31]), "evidence": json.loads(row[32]), "provenance": json.loads(row[33]), "recorded_at": row[34],
        "idempotency_key": row[35], "actor_id": row[36], "record_kind": "local_paper_fill", "environment": "paper",
        "local_evidence_only": True, "paper_only": True, "non_executing": True, "not_imported_account_truth": True,
    }


def _response(conn: Any, record_id: str) -> dict[str, Any]:
    row = conn.execute(f"SELECT {_SELECT} FROM paper_fill_records WHERE id = ?", (record_id,)).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "paper fill not found", details={"id": record_id})
    return _row_to_response(row)


def _paper_fill_record(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    schema_version = str(args.get("schema_version") or _SCHEMA_VERSION)
    if schema_version != _SCHEMA_VERSION:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unsupported paper fill schema_version")
    if str(require(args, "side")) not in {"buy", "sell"}:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "side must be buy or sell")
    if args.get("outcome_side") and str(args["outcome_side"]) not in {"yes", "no"}:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "outcome_side must be yes or no")
    order_as_of = normalize_timestamp(args, "order_as_of", required=True)
    snapshot_as_of = normalize_timestamp(args, "snapshot_as_of")
    caveats = _list_arg(args, "caveats")
    filled, avg, fill_status, freshness = _model_fill(args, caveats)
    qty = _decimal(args.get("requested_quantity"), "requested_quantity") or Decimal(0)
    remaining = qty - filled
    confidence = str(args.get("confidence_label") or ("medium" if fill_status != "no_fill" and freshness == "fresh" else "low"))
    staleness = str(args.get("staleness_status") or freshness)
    if confidence not in _CONFIDENCE or staleness not in _STALENESS:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown confidence/staleness label")
    evidence = _dict_arg(args, "evidence_json")
    evidence.setdefault("book_levels", _list_arg(args, "book_levels"))
    provenance = json.loads(store_metadata_json(args, "provenance_json"))
    safe = {f: _safe_text(args, f, required=f in {"semantic_key", "account_label"}) for f in ("semantic_key", "account_label", "market_id", "instrument_id", "pretrade_intent_id", "quote_id", "book_id", "snapshot_id", "mark_source")}
    fee_amount = _non_negative_decimal(args.get("fee_amount", 0), "fee_amount")
    slippage_cap_bps = _non_negative_decimal(args.get("slippage_cap_bps"), "slippage_cap_bps", required=False)
    source_precedence = _non_negative_int(args.get("source_precedence"), "source_precedence", default=1000)
    material = {
        "schema_version": schema_version, "semantic_key": safe["semantic_key"], "environment_label": "paper", "account_label": safe["account_label"],
        "market_id": safe["market_id"], "instrument_id": safe["instrument_id"], "pretrade_intent_id": safe["pretrade_intent_id"],
        "side": str(args["side"]), "outcome_side": args.get("outcome_side"), "requested_quantity": str(qty), "filled_quantity": str(filled),
        "remaining_quantity": str(remaining), "limit_price": str(_decimal(args.get("limit_price"), "limit_price")), "average_fill_price": str(avg) if avg is not None else None,
        "fee_amount": str(fee_amount), "slippage_cap_bps": str(slippage_cap_bps) if slippage_cap_bps is not None else None,
        "quote_id": safe["quote_id"], "book_id": safe["book_id"], "snapshot_id": safe["snapshot_id"], "snapshot_as_of": snapshot_as_of, "order_as_of": order_as_of,
        "freshness_status": freshness, "fill_status": fill_status, "conservative_fill_model": "limit_depth_v1", "mark_source": safe["mark_source"] or "paper_fill_average_or_limit",
        "mark_as_of": normalize_timestamp(args, "mark_as_of") or order_as_of, "confidence_label": confidence, "staleness_status": staleness,
        "source_precedence": source_precedence, "caveats": caveats, "evidence": evidence, "provenance": provenance,
    }
    material_hash = args.get("material_hash") or _hash_material(material)
    if material_hash != _hash_material(material):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "material_hash does not match canonical paper fill")
    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(uow, event_type=_EVENT, actor_id=ctx.actor_id, idempotency_key=args.get("idempotency_key"))
            if replay is not None:
                if replay.get("material_hash") != material_hash or replay.get("semantic_key") != material["semantic_key"]:
                    raise ToolError(ErrorCode.IDEMPOTENCY_CONFLICT, "idempotency_key already used for materially different paper fill", details={"code": "idempotency_conflict", "idempotency_key": args.get("idempotency_key"), "existing_id": replay.get("id")})
                return _response(uow.conn, replay["id"])
            existing = uow.conn.execute("SELECT id, material_hash FROM paper_fill_records WHERE semantic_key = ?", (material["semantic_key"],)).fetchone()
            if existing is not None:
                if existing[1] == material_hash:
                    return _response(uow.conn, existing[0])
                raise ToolError(ErrorCode.IDEMPOTENCY_CONFLICT, "semantic_key already has materially different paper fill", details={"semantic_key": material["semantic_key"], "existing_id": existing[0], "code": "semantic_conflict"})
            record_id = args.get("id") or new_id("pfr")
            recorded_at = now_iso()
            uow.execute(
                "INSERT INTO paper_fill_records(id, schema_version, semantic_key, material_hash, environment_label, account_label, market_id, instrument_id, pretrade_intent_id, side, outcome_side, requested_quantity, filled_quantity, remaining_quantity, limit_price, average_fill_price, fee_amount, slippage_cap_bps, quote_id, book_id, snapshot_id, snapshot_as_of, order_as_of, freshness_status, fill_status, conservative_fill_model, mark_source, mark_as_of, confidence_label, staleness_status, source_precedence, caveats_json, evidence_json, provenance_json, recorded_at, idempotency_key, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record_id, schema_version, material["semantic_key"], material_hash, "paper", material["account_label"], material["market_id"], material["instrument_id"], material["pretrade_intent_id"], material["side"], material["outcome_side"], float(qty), float(filled), float(remaining), float(Decimal(str(material["limit_price"]))), float(avg) if avg is not None else None, float(Decimal(str(material["fee_amount"]))), float(Decimal(str(material["slippage_cap_bps"]))) if material["slippage_cap_bps"] is not None else None, material["quote_id"], material["book_id"], material["snapshot_id"], snapshot_as_of, order_as_of, freshness, fill_status, material["conservative_fill_model"], material["mark_source"], material["mark_as_of"], confidence, staleness, material["source_precedence"], _canonical_json(caveats), _canonical_json(evidence), _canonical_json(provenance), recorded_at, args.get("idempotency_key"), ctx.actor_id),
            )
            emit_event(uow, event_type=_EVENT, subject_kind="paper_fill", subject_id=record_id, payload={"id": record_id, **material, "material_hash": material_hash}, actor_id=ctx.actor_id, idempotency_key=args.get("idempotency_key"), ctx=ctx)
            return _response(uow.conn, record_id)


def _paper_fill_get(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    with db_for_args(args) as db:
        return _response(db.connection, require(args, "id"))


def _paper_fill_list(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    limit = min(int(args.get("limit", 50)), 200)
    where = ["environment_label = 'paper'"]
    params: list[Any] = []
    for field in ("account_label", "market_id", "instrument_id", "fill_status"):
        if args.get(field):
            where.append(f"{field} = ?")
            params.append(args[field])
    with db_for_args(args) as db:
        rows = db.connection.execute(f"SELECT {_SELECT} FROM paper_fill_records WHERE {' AND '.join(where)} ORDER BY order_as_of DESC, recorded_at DESC, id DESC LIMIT ?", (*params, limit)).fetchall()
        return {"records": [_row_to_response(r) for r in rows], "count": len(rows), "environment": "paper", "paper_only": True, "not_imported_account_truth": True}


def _paper_exposure_report(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    result = _paper_fill_list(args, ctx)
    records = result["records"]
    # Only count rows that actually filled. no_fill rows (and cancelled-order
    # partials, if ever introduced) must not inflate the exposure quantity.
    counted = [r for r in records if r["fill_status"] in ("full", "partial")]
    buy_quantity = sum(float(r["filled_quantity"]) for r in counted if r["side"] == "buy")
    sell_quantity = sum(float(r["filled_quantity"]) for r in counted if r["side"] == "sell")
    buy_fees = sum(float(r["fee_amount"] or 0) for r in counted if r["side"] == "buy")
    sell_fees = sum(float(r["fee_amount"] or 0) for r in counted if r["side"] == "sell")
    buy_notional = sum(float(r["filled_quantity"]) * float(r["average_fill_price"] or 0) for r in counted if r["side"] == "buy")
    sell_notional = sum(float(r["filled_quantity"]) * float(r["average_fill_price"] or 0) for r in counted if r["side"] == "sell")
    # Buys: fees increase the cost basis. Sells: fees reduce the proceeds.
    buy_cost_basis = buy_notional + buy_fees
    sell_proceeds = sell_notional - sell_fees
    net_quantity = buy_quantity - sell_quantity
    cost_basis_plus_fees = buy_cost_basis - sell_proceeds
    return {
        "environment": "paper",
        "account_label": args.get("account_label"),
        "as_of": args.get("as_of") or now_iso(),
        "mark_source": "paper_fill_records",
        "confidence_label": "low" if any(r["staleness_status"] != "fresh" for r in records) else "medium",
        "staleness_statuses": sorted({r["staleness_status"] for r in records}),
        "source_precedence": "paper_fill_records_only; imported/live account truth excluded",
        "paper_exposure": {"net_quantity": net_quantity, "buy_quantity": buy_quantity, "sell_quantity": sell_quantity, "buy_cost_basis": buy_cost_basis, "sell_proceeds": sell_proceeds, "buy_fees": buy_fees, "sell_fees": sell_fees, "cost_basis_plus_fees": cost_basis_plus_fees},
        "records": records,
        "boundary_caveat": _PAPER_EXPOSURE_BOUNDARY_CAVEAT,
        "paper_only": True,
        "not_imported_account_truth": True,
        "local_evidence_only": True,
        "non_executing": True,
        "credential_blind": True,
        "advice_free": True,
        "no_live_execution_claims": True,
        "no_settlement_or_redemption_claims": True,
    }


def register_paper_fill_tools(registry: ToolRegistry) -> None:
    examples = WRITE_TOOL_EXAMPLES.get("paper_fill.record", {})
    props = {"semantic_key": {"type": "string"}, "account_label": {"type": "string"}, "market_id": {"type": "string"}, "instrument_id": {"type": "string"}, "pretrade_intent_id": {"type": "string"}, "side": {"type": "string", "enum": ["buy", "sell"]}, "outcome_side": {"type": "string", "enum": ["yes", "no"]}, "requested_quantity": {"type": "number"}, "limit_price": {"type": "number"}, "book_levels": {"type": "array"}, "reference_mid_price": {"type": "number"}, "slippage_cap_bps": {"type": "number"}, "fee_amount": {"type": "number"}, "quote_id": {"type": "string"}, "book_id": {"type": "string"}, "snapshot_id": {"type": "string"}, "snapshot_as_of": {"type": "string"}, "order_as_of": {"type": "string"}, "max_snapshot_age_seconds": {"type": "integer"}, "mark_source": {"type": "string"}, "mark_as_of": {"type": "string"}, "confidence_label": {"type": "string", "enum": ["low", "medium", "high", "unknown"]}, "staleness_status": {"type": "string", "enum": ["fresh", "stale", "missing", "unknown"]}, "source_precedence": {"type": "integer"}, "caveats": {"type": "array"}, "evidence_json": {"type": "object"}, "provenance_json": {"type": "object"}, "idempotency_key": {"type": "string"}, "home": {"type": "string"}}
    registry.register("paper_fill.record", _paper_fill_record, is_write=True, example_minimal=examples.get("minimal"), example_rich=examples.get("rich"), description="Record one local paper-only conservative fill from caller-supplied quote/book/snapshot facts; no live order execution, account access, signing, cancellation, settlement, or fund movement.", json_schema={"type": "object", "properties": props, "required": ["semantic_key", "account_label", "side", "requested_quantity", "limit_price", "order_as_of"]})
    registry.register("paper_fill.get", _paper_fill_get, description="Read one local paper-only fill record; not imported/live account truth.", json_schema={"type": "object", "properties": {"id": {"type": "string"}, "home": {"type": "string"}}, "required": ["id"]})
    registry.register("paper_fill.list", _paper_fill_list, description="List local paper-only fill records separately from imported/live account truth.", json_schema={"type": "object", "properties": {"account_label": {"type": "string"}, "market_id": {"type": "string"}, "instrument_id": {"type": "string"}, "fill_status": {"type": "string"}, "limit": {"type": "integer"}, "home": {"type": "string"}}})
    registry.register("report.paper_exposure", _paper_exposure_report, description="Report paper-only exposure/P&L basis from local paper_fill_records with mark source, as_of, confidence/staleness, and explicit exclusion of imported/live truth, live execution, settlement/redemption, fund movement, and advice claims.", json_schema={"type": "object", "properties": {"account_label": {"type": "string"}, "market_id": {"type": "string"}, "instrument_id": {"type": "string"}, "as_of": {"type": "string"}, "limit": {"type": "integer"}, "home": {"type": "string"}}, "required": []})


__all__ = ["register_paper_fill_tools"]
