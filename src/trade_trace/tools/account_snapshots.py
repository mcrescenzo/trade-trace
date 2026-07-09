"""Sanitized imported external account snapshot tools.

All records are caller-supplied imported claims. This module intentionally has
no venue client, private-auth fetch, signing, placement, cancellation, custody,
fund movement, or remediation path.
"""

from __future__ import annotations

import hashlib
import json
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

_EVENT = "account_snapshot.imported"
_SCHEMA_VERSION = "account_snapshot.v1"
_CONFIDENCE = {"low", "medium", "high", "unknown"}
_STALENESS = {"fresh", "stale", "missing", "unknown"}
_LIST_FIELDS = (
    "balances", "open_orders", "positions", "fills_trades", "unsettled_claims",
    "public_allowance_facts",
)
_SELECT = "id, schema_version, semantic_key, material_hash, source_system, source_run_id, source_precedence, confidence_label, staleness_status, environment_label, account_label, venue_label, captured_at, effective_at, as_of, retrieved_at, imported_at, artifact_hash, redacted_artifact_ref, balances_json, collateral_json, open_orders_json, positions_json, fills_trades_json, unsettled_claims_json, public_allowance_facts_json, caveats_json, provenance_json, quarantine_reason, idempotency_key, actor_id"


def _decimal_value(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return Decimal(text)
        except InvalidOperation:
            return None
    return None


def _reject_impossible_account_state(value: Any, *, field: str) -> None:
    """Reject impossible/conflicting numeric account-state facts before persistence.

    Account snapshot fact families are conservative caller-supplied evidence. None
    of the v1 fact-family schemas documents signed numeric fields, so negative
    numeric values are quarantined by default. Balance-like objects with both
    ``available`` and ``total`` are also rejected when available exceeds total.
    """

    def fail(message: str, code: str, path: str) -> None:
        raise ToolError(ErrorCode.VALIDATION_ERROR, message, details={"field": field, "path": path, "code": code})

    def walk(node: Any, path: str) -> None:
        numeric = _decimal_value(node)
        if numeric is not None and numeric < 0:
            fail("account snapshot contains negative account-state numeric value", "impossible_payload_quarantined", path)
        if isinstance(node, dict):
            for key, nested in node.items():
                walk(nested, f"{path}.{key}")
            available = _decimal_value(node.get("available"))
            total = _decimal_value(node.get("total"))
            if available is not None and total is not None and available > total:
                fail("account snapshot available exceeds total", "conflicting_payload_quarantined", f"{path}.available")
        elif isinstance(node, list):
            for index, nested in enumerate(node):
                walk(nested, f"{path}[{index}]")

    walk(value, field)


def _json_arg(args: dict[str, Any], field: str, default: Any) -> Any:
    value = args.get(field, default)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            reject_if_contains_secrets(value, field=field)
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
    return hashlib.sha256(f"account_snapshot:{_canonical_json(material)}".encode()).hexdigest()


def _artifact_hash(args: dict[str, Any], material_without_hash: dict[str, Any]) -> str:
    provided = args.get("artifact_hash") or args.get("content_hash")
    if provided:
        text = str(provided)
        reject_if_contains_secrets(text, field="artifact_hash")
        return text
    return hashlib.sha256(f"account_snapshot_artifact:{_canonical_json(material_without_hash)}".encode()).hexdigest()


def _row_to_response(row: Any) -> dict[str, Any]:
    return {
        "id": row[0], "schema_version": row[1], "semantic_key": row[2], "material_hash": row[3],
        "source_system": row[4], "source_run_id": row[5], "source_precedence": row[6],
        "confidence_label": row[7], "staleness_status": row[8], "environment_label": row[9],
        "account_label": row[10], "venue_label": row[11], "captured_at": row[12], "effective_at": row[13],
        "as_of": row[14], "retrieved_at": row[15], "imported_at": row[16], "artifact_hash": row[17],
        "redacted_artifact_ref": row[18], "balances": json.loads(row[19]), "collateral": json.loads(row[20]),
        "open_orders": json.loads(row[21]), "positions": json.loads(row[22]), "fills_trades": json.loads(row[23]),
        "unsettled_claims": json.loads(row[24]), "public_allowance_facts": json.loads(row[25]),
        "caveats": json.loads(row[26]), "provenance": json.loads(row[27]), "quarantine_reason": row[28],
        "idempotency_key": row[29], "actor_id": row[30],
        "record_kind": "sanitized_imported_account_snapshot", "local_evidence_only": True,
        "non_executing": True, "credential_blind": True,
    }


def _response(conn: Any, snapshot_id: str) -> dict[str, Any]:
    row = conn.execute(f"SELECT {_SELECT} FROM account_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "account snapshot not found", details={"id": snapshot_id})
    return _row_to_response(row)


def _account_snapshot_import(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    schema_version = str(args.get("schema_version") or _SCHEMA_VERSION)
    if schema_version != _SCHEMA_VERSION:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unsupported account snapshot schema_version", details={"field": "schema_version", "code": "unsupported_schema_version"})
    confidence = str(args.get("confidence_label") or "unknown")
    staleness = str(args.get("staleness_status") or "unknown")
    if confidence not in _CONFIDENCE:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown account snapshot confidence_label", details={"field": "confidence_label", "code": "impossible_payload_quarantined"})
    if staleness not in _STALENESS:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown account snapshot staleness_status", details={"field": "staleness_status", "code": "impossible_payload_quarantined"})
    captured_at = normalize_timestamp(args, "captured_at", required=True)
    effective_at = normalize_timestamp(args, "effective_at")
    as_of = normalize_timestamp(args, "as_of", required=True)
    retrieved_at = normalize_timestamp(args, "retrieved_at")
    if captured_at is None or as_of is None:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "captured_at and as_of are required", details={"code": "malformed_payload_quarantined"})
    source_precedence = int(args.get("source_precedence", 100))
    if source_precedence < 0:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "source_precedence must be non-negative", details={"field": "source_precedence", "code": "impossible_payload_quarantined"})
    lists = {field: _list_arg(args, field) for field in _LIST_FIELDS}
    collateral = _dict_arg(args, "collateral")
    for field, value in lists.items():
        _reject_impossible_account_state(value, field=field)
    _reject_impossible_account_state(collateral, field="collateral")
    caveats = _list_arg(args, "caveats")
    provenance = json.loads(store_metadata_json(args, "provenance_json"))
    safe_text = {
        field: _safe_text(args, field, required=field in {"semantic_key", "source_system"})
        for field in (
            "semantic_key", "source_system", "source_run_id", "environment_label",
            "account_label", "venue_label", "redacted_artifact_ref", "quarantine_reason",
        )
    }
    if staleness in {"stale", "missing"}:
        caveats.append({"code": f"account_snapshot_{staleness}", "message": "Imported account snapshot staleness was supplied by caller; use as caveated local evidence only."})
    if not any(lists[field] for field in _LIST_FIELDS) and not collateral:
        caveats.append({"code": "account_snapshot_no_fact_families", "message": "Imported snapshot contains no account fact families; reconciliation may be incomplete."})
    material_base = {
        "schema_version": schema_version, "semantic_key": safe_text["semantic_key"],
        "source_system": safe_text["source_system"], "source_run_id": safe_text["source_run_id"],
        "source_precedence": source_precedence, "confidence_label": confidence, "staleness_status": staleness,
        "environment_label": safe_text["environment_label"], "account_label": safe_text["account_label"],
        "venue_label": safe_text["venue_label"], "captured_at": captured_at, "effective_at": effective_at,
        "as_of": as_of, "retrieved_at": retrieved_at, "redacted_artifact_ref": safe_text["redacted_artifact_ref"],
        "balances": lists["balances"], "collateral": collateral, "open_orders": lists["open_orders"],
        "positions": lists["positions"], "fills_trades": lists["fills_trades"],
        "unsettled_claims": lists["unsettled_claims"], "public_allowance_facts": lists["public_allowance_facts"],
        "caveats": caveats, "provenance": provenance, "quarantine_reason": safe_text["quarantine_reason"],
    }
    artifact_hash = _artifact_hash(args, material_base)
    material = {**material_base, "artifact_hash": artifact_hash}
    material_hash = args.get("material_hash") or _hash_material(material)
    if material_hash != _hash_material(material):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "material_hash does not match canonical account snapshot", details={"field": "material_hash", "code": "conflicting_payload_quarantined"})
    idempotency_key = args.get("idempotency_key")
    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(uow, event_type=_EVENT, actor_id=ctx.actor_id, idempotency_key=idempotency_key)
            if replay is not None:
                emit_event(uow, event_type=_EVENT, subject_kind="account_snapshot", subject_id=replay["id"], payload={"id": replay["id"], **material, "material_hash": material_hash, "idempotency_key": idempotency_key}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
                return _response(uow.conn, replay["id"])
            existing = uow.conn.execute("SELECT id, material_hash FROM account_snapshots WHERE semantic_key = ?", (material["semantic_key"],)).fetchone()
            if existing is not None:
                if existing[1] == material_hash:
                    return _response(uow.conn, existing[0])
                raise ToolError(ErrorCode.IDEMPOTENCY_CONFLICT, "semantic_key already has materially different account snapshot", details={"semantic_key": material["semantic_key"], "existing_id": existing[0], "code": "semantic_conflict"})
            snapshot_id = args.get("id") or new_id("acs")
            imported_at = now_iso()
            uow.execute(
                "INSERT INTO account_snapshots(id, schema_version, semantic_key, material_hash, source_system, source_run_id, source_precedence, confidence_label, staleness_status, environment_label, account_label, venue_label, captured_at, effective_at, as_of, retrieved_at, imported_at, artifact_hash, redacted_artifact_ref, balances_json, collateral_json, open_orders_json, positions_json, fills_trades_json, unsettled_claims_json, public_allowance_facts_json, caveats_json, provenance_json, quarantine_reason, idempotency_key, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (snapshot_id, schema_version, material["semantic_key"], material_hash, material["source_system"], material["source_run_id"], source_precedence, confidence, staleness, material["environment_label"], material["account_label"], material["venue_label"], captured_at, effective_at, as_of, retrieved_at, imported_at, artifact_hash, material["redacted_artifact_ref"], _canonical_json(lists["balances"]), _canonical_json(collateral), _canonical_json(lists["open_orders"]), _canonical_json(lists["positions"]), _canonical_json(lists["fills_trades"]), _canonical_json(lists["unsettled_claims"]), _canonical_json(lists["public_allowance_facts"]), _canonical_json(caveats), _canonical_json(provenance), material["quarantine_reason"], idempotency_key, ctx.actor_id),
            )
            emit_event(uow, event_type=_EVENT, subject_kind="account_snapshot", subject_id=snapshot_id, payload={"id": snapshot_id, **material, "material_hash": material_hash, "idempotency_key": idempotency_key}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
            return _response(uow.conn, snapshot_id)


def _account_snapshot_get(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    with db_for_args(args) as db:
        return _response(db.connection, require(args, "id"))


def _account_snapshot_list(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    limit = min(int(args.get("limit", 50)), 200)
    where: list[str] = []
    params: list[Any] = []
    for field in ("source_system", "environment_label", "account_label", "venue_label", "staleness_status"):
        if args.get(field):
            where.append(f"{field} = ?")
            params.append(args[field])
    with db_for_args(args) as db:
        sql = f"SELECT {_SELECT} FROM account_snapshots"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY source_precedence ASC, as_of DESC, imported_at DESC, id DESC LIMIT ?"
        rows = db.connection.execute(sql, (*params, limit)).fetchall()
        return {"records": [_row_to_response(row) for row in rows], "count": len(rows), "record_kind": "sanitized_imported_account_snapshot"}


def _account_snapshot_report(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    limit = min(int(args.get("limit", 100)), 500)
    states = _list_arg(args, "staleness_statuses") if args.get("staleness_statuses") else ["stale", "missing", "unknown"]
    invalid = [state for state in states if state not in _STALENESS]
    if invalid:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "staleness_statuses contains unknown value", details={"field": "staleness_statuses", "invalid": invalid})
    placeholders = ",".join("?" for _ in states)
    with db_for_args(args) as db:
        rows = db.connection.execute(
            f"SELECT {_SELECT} FROM account_snapshots WHERE staleness_status IN ({placeholders}) ORDER BY source_precedence ASC, as_of DESC, imported_at DESC, id DESC LIMIT ?",
            (*states, limit),
        ).fetchall()
        records = [_row_to_response(row) for row in rows]
        return {
            "records": records, "count": len(records), "included_staleness_statuses": states,
            "caveat_codes": sorted(str(c.get("code")) for r in records for c in r["caveats"] if isinstance(c, dict) and c.get("code")),
            "report_kind": "stale_missing_imported_account_snapshots", "local_evidence_only": True,
            "non_executing": True,
        }


def register_account_snapshot_tools(registry: ToolRegistry) -> None:
    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    schema_props = {
        "schema_version": {"type": "string"}, "semantic_key": {"type": "string"},
        "source_system": {"type": "string"}, "source_run_id": {"type": "string"},
        "source_precedence": {"type": "integer"}, "confidence_label": {"type": "string", "enum": sorted(_CONFIDENCE)},
        "staleness_status": {"type": "string", "enum": sorted(_STALENESS)},
        "environment_label": {"type": "string"}, "account_label": {"type": "string"}, "venue_label": {"type": "string"},
        "captured_at": {"type": "string"}, "effective_at": {"type": "string"}, "as_of": {"type": "string"}, "retrieved_at": {"type": "string"},
        "artifact_hash": {"type": "string"}, "content_hash": {"type": "string"}, "redacted_artifact_ref": {"type": "string"},
        "balances": {"type": "array"}, "collateral": {"type": "object"}, "open_orders": {"type": "array"},
        "positions": {"type": "array"}, "fills_trades": {"type": "array"}, "unsettled_claims": {"type": "array"},
        "public_allowance_facts": {"type": "array"}, "caveats": {"type": "array"}, "provenance_json": {"type": "object"},
        "quarantine_reason": {"type": "string"}, "material_hash": {"type": "string"}, "idempotency_key": {"type": "string"}, "home": {"type": "string"},
    }
    registry.register(
        "account_snapshot.import", _account_snapshot_import, is_write=True,
        **_examples_for("account_snapshot.import"),
        description="Import one sanitized caller-supplied account snapshot as local reconciliation evidence only; no private-auth fetch, signing, placement, cancellation, custody movement, or remediation is performed.",
        json_schema={"type": "object", "properties": schema_props, "required": ["semantic_key", "source_system", "captured_at", "as_of"]},
    )
    registry.register(
        "account_snapshot.get", _account_snapshot_get,
        description="Read one sanitized imported account snapshot from local evidence.",
        json_schema={"type": "object", "properties": {"id": {"type": "string"}, "home": {"type": "string"}}, "required": ["id"]},
    )
    registry.register(
        "account_snapshot.list", _account_snapshot_list,
        description="List sanitized imported account snapshots from local evidence; ordered by caller-supplied source precedence.",
        json_schema={"type": "object", "properties": {"source_system": {"type": "string"}, "environment_label": {"type": "string"}, "account_label": {"type": "string"}, "venue_label": {"type": "string"}, "staleness_status": {"type": "string"}, "limit": {"type": "integer"}, "home": {"type": "string"}}},
    )
    registry.register(
        "account_snapshot.report", _account_snapshot_report,
        description="Report stale/missing/unknown imported account snapshots from local evidence; report caveats only and do not remediate.",
        json_schema={"type": "object", "properties": {"staleness_statuses": {"type": "array", "items": {"type": "string", "enum": sorted(_STALENESS)}}, "limit": {"type": "integer"}, "home": {"type": "string"}}},
    )


__all__ = ["register_account_snapshot_tools"]
