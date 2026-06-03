"""Sanitized imported external execution-event receipt tools.

All records are caller-supplied imported claims. This module intentionally has
no venue client, private-auth fetch, signing, placement, cancellation, custody,
or remediation path.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES
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

_EVENT = "external_execution_receipt.imported"
_SCHEMA_VERSION = "external_execution_receipt.v1"
_LIFECYCLE_STATES = {
    "submitted", "accepted", "rejected", "partial_fill", "filled", "cancel_requested",
    "canceled", "expired", "failed", "corrected", "mismatch", "orphan",
}
_EVENT_TYPES = {"order", "fill", "cancel", "error", "correction", "status"}
_REPORT_STATES = {"submitted", "accepted", "partial_fill", "rejected", "failed", "mismatch", "orphan"}
_REF_TABLES = {
    "pretrade_intent_id": "pretrade_intents",
    "approval_ref_id": "approval_waiver_records",
    "market_id": "markets",
    "instrument_id": "instruments",
}
_SELECT = "id, schema_version, semantic_key, material_hash, lifecycle_state, external_event_type, pretrade_intent_id, approval_ref_id, market_id, instrument_id, external_order_ref, external_fill_ref, external_event_ref, source_system, source_run_id, retrieved_at, as_of, imported_at, artifact_hash, redacted_artifact_ref, sanitized_facts_json, caveats_json, provenance_json, quarantine_reason, idempotency_key, actor_id"


def _canonical_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"), default=str)


def _json_arg(args: dict[str, Any], field: str, default: Any) -> Any:
    value = args.get(field, default)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be valid JSON", details={"field": field, "code": "malformed_json_quarantined"}) from exc
    return value


def _dict_arg(args: dict[str, Any], field: str) -> dict[str, Any]:
    value = _json_arg(args, field, {})
    if not isinstance(value, dict):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an object", details={"field": field, "code": "malformed_payload_quarantined"})
    reject_credential_metadata(value, field=field)
    return value


def _list_arg(args: dict[str, Any], field: str) -> list[Any]:
    value = _json_arg(args, field, [])
    if not isinstance(value, list):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an array", details={"field": field, "code": "malformed_payload_quarantined"})
    reject_credential_metadata(value, field=field)
    return value


def _safe_text(args: dict[str, Any], field: str, *, required: bool = False) -> str | None:
    value = require(args, field) if required else args.get(field)
    if value is None:
        return None
    text = str(value)
    reject_if_contains_secrets(text, field=field)
    return text


def _hash_material(material: dict[str, Any]) -> str:
    return hashlib.sha256(f"external_execution_receipt:{_canonical_json(material)}".encode()).hexdigest()


def _artifact_hash(args: dict[str, Any], material_without_hash: dict[str, Any]) -> str:
    provided = args.get("artifact_hash") or args.get("content_hash")
    if provided:
        text = str(provided)
        reject_if_contains_secrets(text, field="artifact_hash")
        return text
    return hashlib.sha256(f"external_artifact:{_canonical_json(material_without_hash)}".encode()).hexdigest()


def _row_to_response(row: Any) -> dict[str, Any]:
    return {
        "id": row[0], "schema_version": row[1], "semantic_key": row[2], "material_hash": row[3],
        "lifecycle_state": row[4], "external_event_type": row[5], "pretrade_intent_id": row[6],
        "approval_ref_id": row[7], "market_id": row[8], "instrument_id": row[9],
        "external_order_ref": row[10], "external_fill_ref": row[11], "external_event_ref": row[12],
        "source_system": row[13], "source_run_id": row[14], "retrieved_at": row[15],
        "as_of": row[16], "imported_at": row[17], "artifact_hash": row[18],
        "redacted_artifact_ref": row[19], "sanitized_facts": json.loads(row[20]),
        "caveats": json.loads(row[21]), "provenance": json.loads(row[22]),
        "quarantine_reason": row[23], "idempotency_key": row[24], "actor_id": row[25],
        "record_kind": "sanitized_imported_external_execution_receipt", "non_executing": True,
        "credential_blind": True,
    }


def _response(conn: Any, receipt_id: str) -> dict[str, Any]:
    row = conn.execute(f"SELECT {_SELECT} FROM external_execution_receipts WHERE id = ?", (receipt_id,)).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "external receipt not found", details={"id": receipt_id})
    return _row_to_response(row)


def _validate_refs(conn: Any, args: dict[str, Any]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for field, table in _REF_TABLES.items():
        value = args.get(field)
        if value and conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (value,)).fetchone() is None:
            missing.append({"field": field, "id": str(value), "table": table})
    return missing


def _external_receipt_import(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    schema_version = str(args.get("schema_version") or _SCHEMA_VERSION)
    if schema_version != _SCHEMA_VERSION:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unsupported external receipt schema_version", details={"field": "schema_version", "code": "unsupported_schema_version"})
    state = str(require(args, "lifecycle_state"))
    event_type = str(require(args, "external_event_type"))
    if state not in _LIFECYCLE_STATES:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown imported external lifecycle_state", details={"field": "lifecycle_state"})
    if event_type not in _EVENT_TYPES:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown imported external_event_type", details={"field": "external_event_type"})
    as_of = normalize_timestamp(args, "as_of", required=True)
    retrieved_at = normalize_timestamp(args, "retrieved_at")
    if as_of is None:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "as_of is required", details={"field": "as_of"})
    sanitized_facts = _dict_arg(args, "sanitized_facts")
    caveats = _list_arg(args, "caveats")
    provenance = json.loads(store_metadata_json(args, "provenance_json"))
    safe_text = {
        field: _safe_text(args, field, required=field in {"semantic_key", "source_system"})
        for field in (
            "semantic_key", "pretrade_intent_id", "approval_ref_id", "market_id", "instrument_id",
            "source_system", "source_run_id", "external_order_ref", "external_fill_ref",
            "external_event_ref", "redacted_artifact_ref", "quarantine_reason",
        )
    }
    if not args.get("pretrade_intent_id"):
        caveats.append({"code": "orphan_external_receipt_no_matching_intent", "message": "Imported external receipt has no matching local pre-trade intent; report as caveat only."})
        if state != "orphan":
            caveats.append({"code": "external_receipt_outside_known_intent_scope", "message": "External activity is outside known local intent scope; Trade Trace does not remediate."})
    if state in {"mismatch", "orphan"}:
        caveats.append({"code": f"imported_external_{state}", "message": "External reconciliation tooling supplied this caveat state as imported evidence."})
    material_base = {
        "schema_version": schema_version, "semantic_key": safe_text["semantic_key"], "lifecycle_state": state,
        "external_event_type": event_type, "pretrade_intent_id": safe_text["pretrade_intent_id"],
        "approval_ref_id": safe_text["approval_ref_id"], "market_id": safe_text["market_id"], "instrument_id": safe_text["instrument_id"],
        "external_order_ref": safe_text["external_order_ref"], "external_fill_ref": safe_text["external_fill_ref"],
        "external_event_ref": safe_text["external_event_ref"], "source_system": safe_text["source_system"],
        "source_run_id": safe_text["source_run_id"], "retrieved_at": retrieved_at, "as_of": as_of,
        "redacted_artifact_ref": safe_text["redacted_artifact_ref"], "sanitized_facts": sanitized_facts,
        "caveats": caveats, "provenance": provenance, "quarantine_reason": safe_text["quarantine_reason"],
    }
    artifact_hash = _artifact_hash(args, material_base)
    material = {**material_base, "artifact_hash": artifact_hash}
    material_hash = args.get("material_hash") or _hash_material(material)
    if material_hash != _hash_material(material):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "material_hash does not match canonical external receipt", details={"field": "material_hash"})
    idempotency_key = args.get("idempotency_key")
    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            missing = _validate_refs(uow.conn, args)
            if missing:
                raise ToolError(ErrorCode.VALIDATION_ERROR, "external receipt references missing rows", details={"missing_refs": missing})
            replay = check_idempotency_replay(uow, event_type=_EVENT, actor_id=ctx.actor_id, idempotency_key=idempotency_key)
            if replay is not None:
                emit_event(uow, event_type=_EVENT, subject_kind="external_execution_receipt", subject_id=replay["id"], payload={"id": replay["id"], **material, "material_hash": material_hash, "idempotency_key": idempotency_key}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
                return _response(uow.conn, replay["id"])
            existing = uow.conn.execute("SELECT id, material_hash FROM external_execution_receipts WHERE semantic_key = ?", (material["semantic_key"],)).fetchone()
            if existing is not None:
                if existing[1] == material_hash:
                    return _response(uow.conn, existing[0])
                raise ToolError(ErrorCode.IDEMPOTENCY_CONFLICT, "semantic_key already has materially different external receipt", details={"semantic_key": material["semantic_key"], "existing_id": existing[0], "code": "semantic_conflict"})
            receipt_id = args.get("id") or new_id("eer")
            imported_at = now_iso()
            uow.execute(
                "INSERT INTO external_execution_receipts(id, schema_version, semantic_key, material_hash, lifecycle_state, external_event_type, pretrade_intent_id, approval_ref_id, market_id, instrument_id, external_order_ref, external_fill_ref, external_event_ref, source_system, source_run_id, retrieved_at, as_of, imported_at, artifact_hash, redacted_artifact_ref, sanitized_facts_json, caveats_json, provenance_json, quarantine_reason, idempotency_key, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (receipt_id, schema_version, material["semantic_key"], material_hash, state, event_type, material["pretrade_intent_id"], material["approval_ref_id"], material["market_id"], material["instrument_id"], material["external_order_ref"], material["external_fill_ref"], material["external_event_ref"], material["source_system"], material["source_run_id"], retrieved_at, as_of, imported_at, artifact_hash, material["redacted_artifact_ref"], _canonical_json(sanitized_facts), _canonical_json(caveats), _canonical_json(provenance), material["quarantine_reason"], idempotency_key, ctx.actor_id),
            )
            emit_event(uow, event_type=_EVENT, subject_kind="external_execution_receipt", subject_id=receipt_id, payload={"id": receipt_id, **material, "material_hash": material_hash, "idempotency_key": idempotency_key}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
            return _response(uow.conn, receipt_id)


def _external_receipt_get(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    with db_for_args(args) as db:
        return _response(db.connection, require(args, "id"))


def _external_receipt_list(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    limit = min(int(args.get("limit", 50)), 200)
    where: list[str] = []
    params: list[Any] = []
    for field in ("pretrade_intent_id", "market_id", "instrument_id", "lifecycle_state", "external_order_ref"):
        if args.get(field):
            where.append(f"{field} = ?")
            params.append(args[field])
    with db_for_args(args) as db:
        sql = f"SELECT {_SELECT} FROM external_execution_receipts"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY imported_at DESC, id DESC LIMIT ?"
        rows = db.connection.execute(sql, (*params, limit)).fetchall()
        return {"records": [_row_to_response(row) for row in rows], "count": len(rows), "record_kind": "sanitized_imported_external_execution_receipt"}


def _external_receipt_report(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    limit = min(int(args.get("limit", 100)), 500)
    states = _list_arg(args, "states") if args.get("states") else sorted(_REPORT_STATES)
    invalid = [state for state in states if state not in _LIFECYCLE_STATES]
    if invalid:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "states contains unknown lifecycle_state", details={"field": "states", "invalid": invalid})
    placeholders = ",".join("?" for _ in states)
    with db_for_args(args) as db:
        rows = db.connection.execute(
            f"SELECT {_SELECT} FROM external_execution_receipts WHERE lifecycle_state IN ({placeholders}) ORDER BY imported_at DESC, id DESC LIMIT ?",
            (*states, limit),
        ).fetchall()
        records = [_row_to_response(row) for row in rows]
        return {
            "records": records,
            "count": len(records),
            "included_states": states,
            "caveat_codes": sorted(str(c.get("code")) for r in records for c in r["caveats"] if isinstance(c, dict) and c.get("code")),
            "report_kind": "open_stale_partial_rejected_imported_external_receipts",
            "non_executing": True,
        }


def register_external_receipt_tools(registry: ToolRegistry) -> None:
    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    schema_props = {
        "schema_version": {"type": "string"}, "semantic_key": {"type": "string"},
        "lifecycle_state": {"type": "string", "enum": sorted(_LIFECYCLE_STATES)},
        "external_event_type": {"type": "string", "enum": sorted(_EVENT_TYPES)},
        "pretrade_intent_id": {"type": "string"}, "approval_ref_id": {"type": "string"},
        "market_id": {"type": "string"}, "instrument_id": {"type": "string"},
        "external_order_ref": {"type": "string"}, "external_fill_ref": {"type": "string"},
        "external_event_ref": {"type": "string"}, "source_system": {"type": "string"},
        "source_run_id": {"type": "string"}, "retrieved_at": {"type": "string"}, "as_of": {"type": "string"},
        "artifact_hash": {"type": "string"}, "content_hash": {"type": "string"},
        "redacted_artifact_ref": {"type": "string"}, "sanitized_facts": {"type": "object"},
        "caveats": {"type": "array"}, "provenance_json": {"type": "object"},
        "quarantine_reason": {"type": "string"}, "material_hash": {"type": "string"},
        "idempotency_key": {"type": "string"}, "home": {"type": "string"},
    }
    registry.register(
        "external_receipt.import", _external_receipt_import, is_write=True,
        **_examples_for("external_receipt.import"),
        description="Import one sanitized external execution-event receipt claim as local evidence only; no private-auth fetch, signing, placement, cancellation, custody movement, or remediation is performed.",
        json_schema={"type": "object", "properties": schema_props, "required": ["semantic_key", "lifecycle_state", "external_event_type", "source_system", "as_of"]},
    )
    registry.register(
        "external_receipt.get", _external_receipt_get,
        description="Read one sanitized imported external execution-event receipt claim from local storage.",
        json_schema={"type": "object", "properties": {"id": {"type": "string"}, "home": {"type": "string"}}, "required": ["id"]},
    )
    registry.register(
        "external_receipt.list", _external_receipt_list,
        description="List sanitized imported external execution-event receipt claims from local evidence.",
        json_schema={"type": "object", "properties": {"pretrade_intent_id": {"type": "string"}, "market_id": {"type": "string"}, "instrument_id": {"type": "string"}, "lifecycle_state": {"type": "string"}, "external_order_ref": {"type": "string"}, "limit": {"type": "integer"}, "home": {"type": "string"}}},
    )
    registry.register(
        "external_receipt.report", _external_receipt_report,
        description="Report open/stale/partial/rejected/mismatch/orphan imported external receipts from local evidence; report caveats only and do not remediate.",
        json_schema={"type": "object", "properties": {"states": {"type": "array", "items": {"type": "string", "enum": sorted(_LIFECYCLE_STATES)}}, "limit": {"type": "integer"}, "home": {"type": "string"}}},
    )


__all__ = ["register_external_receipt_tools"]
