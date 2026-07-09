"""Append-only local approval/waiver/autonomy audit ledger tools."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
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
    validate_fk_refs,
)
from trade_trace.tools.errors import ToolError

_EVENT = "approval_waiver.recorded"
_RECORD_TYPES = {
    "approval", "denial", "modification", "expiry", "revocation", "warning_waiver",
    "missing_data_waiver", "hard_block_override_attempt", "autonomy_permission",
}
_DECISIONS = {"approved", "denied", "modified", "expired", "revoked", "waived", "attempted", "permitted", "rejected"}
_WAIVER_CLASS_BY_TYPE = {
    "warning_waiver": "warning",
    "missing_data_waiver": "missing_data",
    "hard_block_override_attempt": "hard_block_override_attempt",
}
_REF_TABLES = {
    "pretrade_intent_id": "pretrade_intents",
    "risk_check_receipt_id": "risk_check_receipts",
    "strategy_id": "strategies",
    "instrument_id": "instruments",
    "market_id": "markets",
    "policy_version_id": "risk_policy_versions",
}
_SELECT = "id, semantic_key, material_hash, record_type, decision, pretrade_intent_id, risk_check_receipt_id, strategy_id, instrument_id, market_id, actor_mode, decision_actor_id, decision_at, reason, modifications_json, scope_json, limits_json, expires_at, revoked_at, revocation_reason, waiver_class, hard_block_policy_permitted, violation_visible, policy_version_id, policy_version, policy_evidence_json, environment_label, account_label, external_receipt_refs_json, caveats_json, run_id, idempotency_key, provenance_json, created_at, actor_id"


def _json_arg(args: dict[str, Any], field: str, default: Any) -> Any:
    value = args.get(field, default)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be valid JSON", details={"field": field}) from exc
    return value


def _dict_arg(args: dict[str, Any], field: str) -> dict[str, Any]:
    value = _json_arg(args, field, {})
    if not isinstance(value, dict):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an object", details={"field": field})
    reject_credential_metadata(value, field=field)
    return value


def _list_arg(args: dict[str, Any], field: str) -> list[Any]:
    value = _json_arg(args, field, [])
    if not isinstance(value, list):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an array", details={"field": field})
    reject_credential_metadata(value, field=field)
    return value


def _text_arg(args: dict[str, Any], field: str) -> str | None:
    value = args.get(field)
    if value is None:
        return None
    value = str(value)
    reject_if_contains_secrets(value, field=field)
    return value


def _hash_material(material: dict[str, Any]) -> str:
    return hashlib.sha256(f"approval_waiver:{_canonical_json(material)}".encode()).hexdigest()


def _row_to_response(row: Any) -> dict[str, Any]:
    return {
        "id": row[0], "semantic_key": row[1], "material_hash": row[2], "record_type": row[3], "decision": row[4],
        "pretrade_intent_id": row[5], "risk_check_receipt_id": row[6], "strategy_id": row[7], "instrument_id": row[8], "market_id": row[9],
        "actor_mode": row[10], "decision_actor_id": row[11], "decision_at": row[12], "reason": row[13],
        "modifications": json.loads(row[14]), "scope": json.loads(row[15]), "limits": json.loads(row[16]),
        "expires_at": row[17], "revoked_at": row[18], "revocation_reason": row[19], "waiver_class": row[20],
        "hard_block_policy_permitted": bool(row[21]), "violation_visible": bool(row[22]), "policy_version_id": row[23], "policy_version": row[24],
        "policy_evidence": json.loads(row[25]), "environment_label": row[26], "account_label": row[27],
        "external_receipt_refs": json.loads(row[28]), "caveats": json.loads(row[29]), "run_id": row[30],
        "idempotency_key": row[31], "provenance": json.loads(row[32]), "created_at": row[33], "actor_id": row[34],
        "record_kind": "local_approval_waiver_autonomy_audit", "non_executing": True,
    }


def _response(conn: Any, record_id: str) -> dict[str, Any]:
    row = conn.execute(f"SELECT {_SELECT} FROM approval_waiver_records WHERE id = ?", (record_id,)).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "approval/waiver record not found", details={"id": record_id})
    return _row_to_response(row)


def _validate_refs(conn: Any, args: dict[str, Any]) -> list[dict[str, str]]:
    return validate_fk_refs(conn, args, _REF_TABLES)


def _approval_record(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    record_type = str(require(args, "record_type"))
    decision = str(require(args, "decision"))
    if record_type not in _RECORD_TYPES:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown record_type", details={"field": "record_type"})
    if decision not in _DECISIONS:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown decision", details={"field": "decision"})
    decision_at = normalize_timestamp(args, "decision_at", required=True)
    expires_at = normalize_timestamp(args, "expires_at")
    revoked_at = normalize_timestamp(args, "revoked_at")
    if decision_at is None:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "decision_at is required", details={"field": "decision_at"})
    waiver_class = args.get("waiver_class") or _WAIVER_CLASS_BY_TYPE.get(record_type)
    policy_evidence = _dict_arg(args, "policy_evidence")
    hard_block_permitted = bool(args.get("hard_block_policy_permitted", False))
    violation_visible = bool(record_type == "hard_block_override_attempt")
    if record_type == "hard_block_override_attempt" and hard_block_permitted:
        policy_evidence.setdefault("caller_asserted_policy_permits_hard_block_override", True)
    caveats = _list_arg(args, "caveats")
    if record_type == "hard_block_override_attempt" and hard_block_permitted:
        caveats.append({"code": "hard_block_policy_assertion_unverified", "message": "Caller asserted policy permits the hard-block override attempt; this is audit evidence only and was not locally verified, so violation visibility remains fail-closed."})
    if args.get("external_receipt_refs"):
        caveats.append({"code": "external_receipts_caller_supplied_unverified", "message": "External receipt references are opaque caller/importer labels; Trade Trace does not fetch or remediate execution."})
    if record_type == "hard_block_override_attempt" and violation_visible:
        caveats.append({"code": "hard_block_override_attempt_violation", "message": "Hard-block override attempt remains visible as a violation; no live permission was granted."})
    for field in ("reason", "revocation_reason", "environment_label", "account_label", "policy_version", "actor_mode", "decision_actor_id"):
        _text_arg(args, field)
    provenance = json.loads(store_metadata_json(args, "provenance_json"))
    material = {
        "semantic_key": require(args, "semantic_key"), "record_type": record_type, "decision": decision,
        "pretrade_intent_id": args.get("pretrade_intent_id"), "risk_check_receipt_id": args.get("risk_check_receipt_id"),
        "strategy_id": args.get("strategy_id"), "instrument_id": args.get("instrument_id"), "market_id": args.get("market_id"),
        "actor_mode": require(args, "actor_mode"), "decision_actor_id": require(args, "decision_actor_id"), "decision_at": decision_at,
        "reason": args.get("reason"), "modifications": _dict_arg(args, "modifications"), "scope": _dict_arg(args, "scope"),
        "limits": _dict_arg(args, "limits"), "expires_at": expires_at, "revoked_at": revoked_at,
        "revocation_reason": args.get("revocation_reason"), "waiver_class": waiver_class,
        "hard_block_policy_permitted": hard_block_permitted, "violation_visible": violation_visible,
        "policy_version_id": args.get("policy_version_id"), "policy_version": args.get("policy_version"), "policy_evidence": policy_evidence,
        "environment_label": args.get("environment_label"), "account_label": args.get("account_label"),
        "external_receipt_refs": _list_arg(args, "external_receipt_refs"), "caveats": caveats,
        "run_id": args.get("run_id"), "provenance": provenance,
    }
    computed_hash = _hash_material(material)
    material_hash = args.get("material_hash") or computed_hash
    if material_hash != computed_hash:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "material_hash does not match canonical approval/waiver record", details={"field": "material_hash"})
    idempotency_key = args.get("idempotency_key")
    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            missing = _validate_refs(uow.conn, args)
            if missing:
                raise ToolError(ErrorCode.VALIDATION_ERROR, "approval/waiver references missing rows", details={"missing_refs": missing})
            replay = check_idempotency_replay(uow, event_type=_EVENT, actor_id=ctx.actor_id, idempotency_key=idempotency_key)
            if replay is not None:
                emit_event(uow, event_type=_EVENT, subject_kind="approval_waiver", subject_id=replay["id"], payload={"id": replay["id"], **material, "material_hash": material_hash, "idempotency_key": idempotency_key}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
                return _response(uow.conn, replay["id"])
            existing = uow.conn.execute("SELECT id, material_hash FROM approval_waiver_records WHERE semantic_key = ?", (material["semantic_key"],)).fetchone()
            if existing is not None:
                if existing[1] == material_hash:
                    return _response(uow.conn, existing[0])
                raise ToolError(ErrorCode.IDEMPOTENCY_CONFLICT, "semantic_key already has materially different approval/waiver record", details={"semantic_key": material["semantic_key"], "existing_id": existing[0]})
            record_id = args.get("id") or new_id("awr")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO approval_waiver_records(id, semantic_key, material_hash, record_type, decision, pretrade_intent_id, risk_check_receipt_id, strategy_id, instrument_id, market_id, actor_mode, decision_actor_id, decision_at, reason, modifications_json, scope_json, limits_json, expires_at, revoked_at, revocation_reason, waiver_class, hard_block_policy_permitted, violation_visible, policy_version_id, policy_version, policy_evidence_json, environment_label, account_label, external_receipt_refs_json, caveats_json, run_id, idempotency_key, provenance_json, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record_id, material["semantic_key"], material_hash, record_type, decision, material["pretrade_intent_id"], material["risk_check_receipt_id"], material["strategy_id"], material["instrument_id"], material["market_id"], material["actor_mode"], material["decision_actor_id"], decision_at, material["reason"], _canonical_json(material["modifications"]), _canonical_json(material["scope"]), _canonical_json(material["limits"]), expires_at, revoked_at, material["revocation_reason"], waiver_class, int(hard_block_permitted), int(violation_visible), material["policy_version_id"], material["policy_version"], _canonical_json(policy_evidence), material["environment_label"], material["account_label"], _canonical_json(material["external_receipt_refs"]), _canonical_json(caveats), material["run_id"], idempotency_key, _canonical_json(provenance), created_at, ctx.actor_id),
            )
            emit_event(uow, event_type=_EVENT, subject_kind="approval_waiver", subject_id=record_id, payload={"id": record_id, **material, "material_hash": material_hash, "idempotency_key": idempotency_key}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
            return _response(uow.conn, record_id)


def _approval_get(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    with db_for_args(args) as db:
        return _response(db.connection, require(args, "id"))


def _approval_list(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    limit = min(int(args.get("limit", 50)), 200)
    where: list[str] = []
    params: list[Any] = []
    for field in ("pretrade_intent_id", "risk_check_receipt_id", "strategy_id", "instrument_id", "market_id", "record_type", "decision"):
        if args.get(field):
            where.append(f"{field} = ?")
            params.append(args[field])
    with db_for_args(args) as db:
        sql = f"SELECT {_SELECT} FROM approval_waiver_records"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        rows = db.connection.execute(sql, (*params, limit)).fetchall()
        return {"records": [_row_to_response(row) for row in rows], "count": len(rows), "record_kind": "local_approval_waiver_autonomy_audit", "non_executing": True}


def _approval_report(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    listed = _approval_list(args, ctx)
    by_intent: dict[str, dict[str, Any]] = {}
    with db_for_args(args) as db:
        for record in listed["records"]:
            intent_id = record.get("pretrade_intent_id") or "unlinked"
            entry = by_intent.setdefault(intent_id, {"pretrade_intent_id": None if intent_id == "unlinked" else intent_id, "proposed": None, "approval_waiver_records": [], "caveats": []})
            entry["approval_waiver_records"].append(record)
        for intent_id, entry in by_intent.items():
            if intent_id == "unlinked":
                entry["caveats"].append("No pretrade_intent_id link supplied for one or more records.")
                continue
            row = db.connection.execute("SELECT proposed_shape_json, risk_budget_json, approval_state, approval_ref_id FROM pretrade_intents WHERE id = ?", (intent_id,)).fetchone()
            if row is None:
                entry["caveats"].append("Linked pre-trade intent row is unavailable.")
            else:
                entry["proposed"] = {"proposed_shape": json.loads(row[0]), "risk_budget": json.loads(row[1]), "intent_approval_state": row[2], "intent_approval_ref_id": row[3]}
            if any(r["external_receipt_refs"] for r in entry["approval_waiver_records"]):
                entry["caveats"].append("External execution receipt refs are caller-supplied labels only; no execution import table is compared in this bead.")
            else:
                entry["caveats"].append("Externally imported execution activity unavailable/not imported; no remediation inferred.")
        return {"kind": "approval_ledger_report", "record_kind": "local_approval_waiver_autonomy_audit_report", "non_executing": True, "count": listed["count"], "groups": list(by_intent.values())}


def register_approval_tools(registry: ToolRegistry) -> None:
    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    schema_props = {
        "semantic_key": {"type": "string"}, "record_type": {"type": "string", "enum": sorted(_RECORD_TYPES)}, "decision": {"type": "string", "enum": sorted(_DECISIONS)},
        "pretrade_intent_id": {"type": "string"}, "risk_check_receipt_id": {"type": "string"}, "strategy_id": {"type": "string"}, "instrument_id": {"type": "string"}, "market_id": {"type": "string"},
        "actor_mode": {"type": "string"}, "decision_actor_id": {"type": "string"}, "decision_at": {"type": "string"}, "reason": {"type": "string"},
        "modifications": {"type": "object"}, "scope": {"type": "object"}, "limits": {"type": "object"}, "expires_at": {"type": "string"}, "revoked_at": {"type": "string"}, "revocation_reason": {"type": "string"},
        "waiver_class": {"type": "string", "enum": ["warning", "missing_data", "hard_block_override_attempt"]}, "hard_block_policy_permitted": {"type": "boolean"},
        "policy_version_id": {"type": "string"}, "policy_version": {"type": "string"}, "policy_evidence": {"type": "object"}, "environment_label": {"type": "string"}, "account_label": {"type": "string"},
        "external_receipt_refs": {"type": "array"}, "caveats": {"type": "array"}, "run_id": {"type": "string"}, "idempotency_key": {"type": "string"}, "material_hash": {"type": "string"}, "provenance_json": {"type": "object"}, "home": {"type": "string"},
    }
    registry.register("approval.record", _approval_record, is_write=True, **_examples_for("approval.record"), description="Append a local approval/waiver/autonomy-permission audit evidence record. This is not a live permission gate and Trade Trace does not submit, sign, approve external allowances, place, cancel, settle, redeem, deposit, withdraw, or remediate activity.", json_schema={"type": "object", "properties": schema_props, "required": ["semantic_key", "record_type", "decision", "actor_mode", "decision_actor_id", "decision_at"]})
    registry.register("approval.get", _approval_get, description="Read one local approval/waiver/autonomy audit record; non-executing evidence only.", json_schema={"type": "object", "properties": {"id": {"type": "string"}, "home": {"type": "string"}}, "required": ["id"]})
    registry.register("approval.list", _approval_list, description="List local approval/waiver/autonomy audit records and hard-block override attempts; non-executing evidence only.", json_schema={"type": "object", "properties": {"pretrade_intent_id": {"type": "string"}, "risk_check_receipt_id": {"type": "string"}, "strategy_id": {"type": "string"}, "instrument_id": {"type": "string"}, "market_id": {"type": "string"}, "record_type": {"type": "string"}, "decision": {"type": "string"}, "limit": {"type": "integer"}, "home": {"type": "string"}}})
    registry.register("approval.report", _approval_report, description="Read-only comparison of proposed pre-trade packets versus local approval/waiver records and caller-supplied external receipt refs; reports unavailable imports as caveats and performs no execution/remediation.", json_schema={"type": "object", "properties": {"pretrade_intent_id": {"type": "string"}, "risk_check_receipt_id": {"type": "string"}, "strategy_id": {"type": "string"}, "instrument_id": {"type": "string"}, "market_id": {"type": "string"}, "limit": {"type": "integer"}, "home": {"type": "string"}}})


__all__ = ["register_approval_tools"]
