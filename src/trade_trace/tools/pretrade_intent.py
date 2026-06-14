"""Immutable local audit packets for non-executing pre-trade intents."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
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

_EVENT = "pretrade_intent.recorded"
_APPROVAL_STATES = {
    "not_requested", "pending_external_review", "approved_elsewhere", "waived_elsewhere", "rejected_elsewhere",
}
_REF_TABLES = {
    "market_id": "markets",
    "instrument_id": "instruments",
    "snapshot_id": "snapshots",
    "thesis_id": "theses",
    "forecast_id": "forecasts",
    "decision_id": "decisions",
    "risk_check_receipt_id": "risk_check_receipts",
    "strategy_id": "strategies",
    "playbook_version_id": "playbook_versions",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"), default=str)


def _json_arg(args: dict[str, Any], field: str, default: Any) -> Any:
    value = args.get(field, default)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be valid JSON", details={"field": field}) from exc
    return value


def _list_arg(args: dict[str, Any], field: str) -> list[Any]:
    value = _json_arg(args, field, [])
    if not isinstance(value, list):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an array", details={"field": field})
    return value


def _dict_arg(args: dict[str, Any], field: str) -> dict[str, Any]:
    value = _json_arg(args, field, {})
    if not isinstance(value, dict):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an object", details={"field": field})
    return value


def _hash_material(material: dict[str, Any]) -> str:
    return hashlib.sha256(f"pretrade_intent:{_canonical_json(material)}".encode()).hexdigest()


def _validate_refs(conn: Any, args: dict[str, Any]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for field, table in _REF_TABLES.items():
        value = args.get(field)
        if value and conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (value,)).fetchone() is None:
            missing.append({"field": field, "id": str(value), "table": table})
    source_ids = _list_arg(args, "source_ids")
    for source_id in source_ids:
        if conn.execute("SELECT 1 FROM sources WHERE id = ?", (source_id,)).fetchone() is None:
            missing.append({"field": "source_ids", "id": str(source_id), "table": "sources"})
    return missing


def _evaluation_for(conn: Any, receipt_id: Any) -> dict[str, Any]:
    """Derive the intent's risk-evaluation lifecycle view from append-only rows.

    An intent is "evaluated" exactly when it links an immutable
    risk_check_receipts row written by risk.check_record (itself the persisted
    output of the deterministic risk.evaluate verdict). We never mutate the
    intent to record this; the receipt link is set at record time and the
    verdict status is read through here so pretrade_intent.get/list surface
    "intent awaiting check" (no receipt) vs "intent with check" (receipt +
    status) without a mutable status column (bead trade-trace-2g47;
    autonomous-trader-substrate.md §9).
    """

    if not receipt_id:
        return {"evaluated": False, "risk_check_receipt_id": None, "status": None}
    row = conn.execute(
        "SELECT status FROM risk_check_receipts WHERE id = ?",
        (receipt_id,),
    ).fetchone()
    # The FK is validated at write time, so a linked receipt is normally
    # present; if it is somehow missing we still report the link without
    # asserting a verdict rather than raising on a read path.
    return {
        "evaluated": row is not None,
        "risk_check_receipt_id": receipt_id,
        "status": row[0] if row is not None else None,
    }


def _row_to_response(row: Any, conn: Any) -> dict[str, Any]:
    return {
        "id": row[0], "semantic_key": row[1], "material_hash": row[2],
        "market_id": row[3], "instrument_id": row[4], "snapshot_id": row[5],
        "thesis_id": row[6], "forecast_id": row[7], "decision_id": row[8],
        "risk_check_receipt_id": row[9], "strategy_id": row[10], "playbook_version_id": row[11],
        "proposed_shape": json.loads(row[12]), "risk_budget": json.loads(row[13]),
        "evidence_refs": json.loads(row[14]), "source_ids": json.loads(row[15]),
        "caveats": json.loads(row[16]), "approval_state": row[17], "approval_ref_id": row[18],
        "as_of": row[19], "run_id": row[20], "idempotency_key": row[21],
        "provenance": json.loads(row[22]), "created_at": row[23], "actor_id": row[24],
        "evaluation": _evaluation_for(conn, row[9]),
        "record_kind": "proposed_local_pretrade_intent", "non_executing": True,
    }


def _response(conn: Any, intent_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, semantic_key, material_hash, market_id, instrument_id, snapshot_id, thesis_id, forecast_id, decision_id, risk_check_receipt_id, strategy_id, playbook_version_id, proposed_shape_json, risk_budget_json, evidence_refs_json, source_ids_json, caveats_json, approval_state, approval_ref_id, as_of, run_id, idempotency_key, provenance_json, created_at, actor_id FROM pretrade_intents WHERE id = ?",
        (intent_id,),
    ).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "pre-trade intent not found", details={"id": intent_id})
    return _row_to_response(row, conn)


def _material(args: dict[str, Any], as_of: str, proposed_shape: dict[str, Any], risk_budget: dict[str, Any], evidence_refs: list[Any], source_ids: list[Any], caveats: list[Any], provenance: dict[str, Any]) -> dict[str, Any]:
    return {
        "semantic_key": require(args, "semantic_key"), "market_id": args.get("market_id"), "instrument_id": args.get("instrument_id"),
        "snapshot_id": args.get("snapshot_id"), "thesis_id": args.get("thesis_id"), "forecast_id": args.get("forecast_id"),
        "decision_id": args.get("decision_id"), "risk_check_receipt_id": args.get("risk_check_receipt_id"),
        "strategy_id": args.get("strategy_id"), "playbook_version_id": args.get("playbook_version_id"),
        "proposed_shape": proposed_shape, "risk_budget": risk_budget, "evidence_refs": evidence_refs,
        "source_ids": source_ids, "caveats": caveats, "approval_state": args.get("approval_state", "not_requested"),
        "approval_ref_id": args.get("approval_ref_id"), "as_of": as_of, "run_id": args.get("run_id"), "provenance": provenance,
    }


def _pretrade_intent_record(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if not (args.get("market_id") or args.get("instrument_id")):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "market_id or instrument_id is required", details={"field": "market_id"})
    # semantic_key is a required, caller-supplied free-text field that is
    # persisted verbatim and hashed into the material packet; scan it for
    # credential-shaped substrings before any further work (bead
    # trade-trace-jm14 / INV-6).
    reject_if_contains_secrets(require(args, "semantic_key"), field="semantic_key")
    proposed_shape = _dict_arg(args, "proposed_shape")
    if not proposed_shape:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "proposed_shape must be explicit", details={"field": "proposed_shape"})
    approval_state = args.get("approval_state", "not_requested")
    if approval_state not in _APPROVAL_STATES:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown approval_state", details={"field": "approval_state"})
    as_of = normalize_timestamp(args, "as_of", required=True)
    if as_of is None:  # normalize_timestamp(required=True) narrows at runtime.
        raise ToolError(ErrorCode.VALIDATION_ERROR, "as_of is required", details={"field": "as_of"})
    risk_budget = _dict_arg(args, "risk_budget")
    evidence_refs = _list_arg(args, "evidence_refs")
    source_ids = _list_arg(args, "source_ids")
    caveats = _list_arg(args, "caveats")
    reject_credential_metadata(proposed_shape, field="proposed_shape")
    reject_credential_metadata(risk_budget, field="risk_budget")
    reject_credential_metadata(evidence_refs, field="evidence_refs")
    reject_credential_metadata(source_ids, field="source_ids")
    reject_credential_metadata(caveats, field="caveats")
    if not evidence_refs:
        caveats.append({"code": "missing_evidence_refs", "message": "No caller-supplied evidence references linked."})
    if args.get("evidence_stale") is True:
        caveats.append({"code": "stale_evidence", "message": "Caller marked evidence as stale."})
    provenance = json.loads(store_metadata_json(args, "provenance_json"))
    material = _material(args, as_of, proposed_shape, risk_budget, evidence_refs, source_ids, caveats, provenance)
    computed_hash = _hash_material(material)
    material_hash = args.get("material_hash") or computed_hash
    if material_hash != computed_hash:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "material_hash does not match canonical intent packet", details={"field": "material_hash"})
    idempotency_key = args.get("idempotency_key")

    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            missing = _validate_refs(uow.conn, args)
            if missing:
                raise ToolError(ErrorCode.VALIDATION_ERROR, "intent references missing rows", details={"missing_refs": missing})
            replay = check_idempotency_replay(uow, event_type=_EVENT, actor_id=ctx.actor_id, idempotency_key=idempotency_key)
            if replay is not None:
                emit_event(uow, event_type=_EVENT, subject_kind="pretrade_intent", subject_id=replay["id"], payload={"id": replay["id"], **material, "material_hash": material_hash, "idempotency_key": idempotency_key}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
                return _response(uow.conn, replay["id"])
            existing = uow.conn.execute("SELECT id, material_hash FROM pretrade_intents WHERE semantic_key = ?", (material["semantic_key"],)).fetchone()
            if existing is not None:
                if existing[1] == material_hash:
                    return _response(uow.conn, existing[0])
                raise ToolError(ErrorCode.IDEMPOTENCY_CONFLICT, "semantic_key already has materially different pre-trade intent", details={"semantic_key": material["semantic_key"], "existing_id": existing[0]})
            intent_id = args.get("id") or new_id("pti")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO pretrade_intents(id, semantic_key, material_hash, market_id, instrument_id, snapshot_id, thesis_id, forecast_id, decision_id, risk_check_receipt_id, strategy_id, playbook_version_id, proposed_shape_json, risk_budget_json, evidence_refs_json, source_ids_json, caveats_json, approval_state, approval_ref_id, as_of, run_id, idempotency_key, provenance_json, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (intent_id, material["semantic_key"], material_hash, material["market_id"], material["instrument_id"], material["snapshot_id"], material["thesis_id"], material["forecast_id"], material["decision_id"], material["risk_check_receipt_id"], material["strategy_id"], material["playbook_version_id"], _canonical_json(proposed_shape), _canonical_json(risk_budget), _canonical_json(evidence_refs), _canonical_json(source_ids), _canonical_json(caveats), approval_state, material["approval_ref_id"], as_of, material["run_id"], idempotency_key, _canonical_json(provenance), created_at, ctx.actor_id),
            )
            emit_event(uow, event_type=_EVENT, subject_kind="pretrade_intent", subject_id=intent_id, payload={"id": intent_id, **material, "material_hash": material_hash, "idempotency_key": idempotency_key}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
            return _response(uow.conn, intent_id)


def _pretrade_intent_get(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    intent_id = require(args, "id")
    with db_for_args(args) as db:
        return _response(db.connection, intent_id)


def _pretrade_intent_list(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    limit = min(int(args.get("limit", 50)), 200)
    with db_for_args(args) as db:
        where = []
        params: list[Any] = []
        for field in ("market_id", "instrument_id", "forecast_id", "decision_id"):
            if args.get(field):
                where.append(f"{field} = ?")
                params.append(args[field])
        sql = "SELECT id, semantic_key, material_hash, market_id, instrument_id, snapshot_id, thesis_id, forecast_id, decision_id, risk_check_receipt_id, strategy_id, playbook_version_id, proposed_shape_json, risk_budget_json, evidence_refs_json, source_ids_json, caveats_json, approval_state, approval_ref_id, as_of, run_id, idempotency_key, provenance_json, created_at, actor_id FROM pretrade_intents"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        rows = db.connection.execute(sql, (*params, limit)).fetchall()
        return {"records": [_row_to_response(row, db.connection) for row in rows], "count": len(rows), "record_kind": "proposed_local_pretrade_intent"}


def register_pretrade_intent_tools(registry: ToolRegistry) -> None:
    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    schema_props = {
        "semantic_key": {"type": "string"}, "market_id": {"type": "string"}, "instrument_id": {"type": "string"},
        "snapshot_id": {"type": "string"}, "thesis_id": {"type": "string"}, "forecast_id": {"type": "string"},
        "decision_id": {"type": "string"}, "risk_check_receipt_id": {"type": "string"}, "strategy_id": {"type": "string"},
        "playbook_version_id": {"type": "string"}, "proposed_shape": {
            "type": "object",
            "description": "Caller-authored, non-executing proposed intent shape for local audit only; Trade Trace does not submit, sign, place, approve, cancel, or route it.",
            "properties": {
                "venue_family": {"type": "string", "description": "Venue family or review context, e.g. polymarket."},
                "side": {"type": "string", "description": "Proposed directional side/stance, e.g. yes/no/buy/sell."},
                "limit_price": {"description": "Caller's proposed non-executing limit/threshold price."},
                "quantity": {"description": "Caller's proposed non-executing size/quantity."},
                "time_in_force": {"type": "string", "description": "Caller-supplied review horizon or intended time-in-force label."},
                "intent_type": {"type": "string", "description": "Optional non-executing intent type/shape label, e.g. limit_review."},
                "notes": {"type": "string", "description": "Optional notes about the proposed local intent; do not include private material."},
            },
            "additionalProperties": True,
        }, "risk_budget": {"type": "object"},
        "evidence_refs": {"type": "array"}, "source_ids": {"type": "array"}, "caveats": {"type": "array"},
        "evidence_stale": {"type": "boolean"}, "approval_state": {"type": "string", "enum": sorted(_APPROVAL_STATES)},
        "approval_ref_id": {"type": "string"}, "as_of": {"type": "string"}, "run_id": {"type": "string"},
        "provenance_json": {"type": "object"}, "material_hash": {"type": "string"}, "idempotency_key": {"type": "string"}, "home": {"type": "string"},
    }
    registry.register(
        "pretrade_intent.record", _pretrade_intent_record, is_write=True,
        **_examples_for("pretrade_intent.record"),
        description="Record an immutable local audit packet for a proposed non-executing pre-trade intent; Trade Trace does not place, sign, send, cancel, redeem, settle, deposit, withdraw, or approve activity.",
        json_schema={"type": "object", "properties": schema_props, "required": ["semantic_key", "proposed_shape", "as_of"]},
    )
    registry.register(
        "pretrade_intent.get", _pretrade_intent_get,
        description="Read one immutable local proposed pre-trade intent audit packet; this is not approved or external activity.",
        json_schema={"type": "object", "properties": {"id": {"type": "string"}, "home": {"type": "string"}}, "required": ["id"]},
    )
    registry.register(
        "pretrade_intent.list", _pretrade_intent_list,
        description="List local proposed pre-trade intent audit packets separately from approved activity, external receipts, fills, cancels, and reconciliations.",
        json_schema={"type": "object", "properties": {"market_id": {"type": "string"}, "instrument_id": {"type": "string"}, "forecast_id": {"type": "string"}, "decision_id": {"type": "string"}, "limit": {"type": "integer"}, "home": {"type": "string"}}},
    )


__all__ = ["register_pretrade_intent_tools"]
