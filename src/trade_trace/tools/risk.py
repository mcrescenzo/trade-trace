"""Audit-only risk policy version and risk-check receipt tools."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    open_db_for_args,
    reject_credential_metadata,
    reject_if_contains_secrets,
    require,
    store_metadata_json,
)
from trade_trace.tools.errors import ToolError

_POLICY_EVENT = "risk_policy_version.created"
_RECEIPT_EVENT = "risk_check_receipt.recorded"
STATUSES = {"pass", "warn", "fail", "missing_data"}
OUTCOMES = {"pass", "warning", "hard_block", "missing_data", "stale_data", "waived_warning"}
SEVERITIES = {"info", "warning", "hard_block", "missing_data"}
RECEIPT_ANCHOR_FIELDS = (
    "intended_action", "proposed_intent_hash", "decision_id", "market_id",
    "instrument_id", "strategy_id", "snapshot_id",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(prefix: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(f"{prefix}:{_canonical_json(payload)}".encode()).hexdigest()


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


def _guard_json(value: Any, *, field: str) -> None:
    reject_credential_metadata(value, field=field)


def _guard_text(value: Any, *, field: str) -> None:
    reject_if_contains_secrets(value, field=field)


def _policy_response(conn: Any, policy_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, policy_key, version, policy_hash, effective_from, effective_to, created_at FROM risk_policy_versions WHERE id = ?",
        (policy_id,),
    ).fetchone()
    return {
        "id": row[0], "policy_key": row[1], "version": row[2], "policy_hash": row[3],
        "effective_from": row[4], "effective_to": row[5], "created_at": row[6],
    }


def _risk_policy_version_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    policy_key = require(args, "policy_key")
    version = require(args, "version")
    limits = _dict_arg(args, "limits_json")
    rules = _list_arg(args, "rules_json")
    source = require(args, "source")
    _guard_json(limits, field="limits_json")
    _guard_json(rules, field="rules_json")
    _guard_text(source, field="source")
    effective_from = normalize_timestamp(args, "effective_from", required=True)
    effective_to = normalize_timestamp(args, "effective_to")
    provenance_json = store_metadata_json(args, "provenance_json")
    idempotency_key = args.get("idempotency_key")
    computed_policy_hash = _hash_payload("risk_policy", {
        "policy_key": policy_key, "version": version, "limits": limits, "rules": rules,
        "source": source, "effective_from": effective_from, "effective_to": effective_to,
        "provenance": json.loads(provenance_json),
    })
    policy_hash = args.get("policy_hash") or computed_policy_hash
    if policy_hash != computed_policy_hash:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "policy_hash does not match canonical policy payload", details={"field": "policy_hash"})

    def payload(pid: str) -> dict[str, Any]:
        return {
            "id": pid, "policy_key": policy_key, "version": version, "policy_hash": policy_hash,
            "limits_json": limits, "rules_json": rules, "source": source,
            "provenance_json": json.loads(provenance_json), "effective_from": effective_from,
            "effective_to": effective_to,
        }

    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(uow, event_type=_POLICY_EVENT, actor_id=ctx.actor_id, idempotency_key=idempotency_key)
            if replay is not None:
                emit_event(uow, event_type=_POLICY_EVENT, subject_kind="risk_policy_version", subject_id=replay["id"], payload=payload(replay["id"]), actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
                return _policy_response(uow.conn, replay["id"])
            policy_id = args.get("id") or new_id("rpv")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO risk_policy_versions(id, policy_key, version, policy_hash, limits_json, rules_json, source, provenance_json, effective_from, effective_to, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (policy_id, policy_key, version, policy_hash, _canonical_json(limits), _canonical_json(rules), source, provenance_json, effective_from, effective_to, created_at, ctx.actor_id),
            )
            emit_event(uow, event_type=_POLICY_EVENT, subject_kind="risk_policy_version", subject_id=policy_id, payload=payload(policy_id), actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
            return _policy_response(uow.conn, policy_id)
    finally:
        db.close()


def _receipt_response(conn: Any, receipt_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, receipt_hash, policy_version_id, status, outcome, intended_action, proposed_intent_hash, decision_id, market_id, instrument_id, strategy_id, snapshot_id, as_of, created_at FROM risk_check_receipts WHERE id = ?",
        (receipt_id,),
    ).fetchone()
    rules = conn.execute(
        "SELECT rule_id, reason_code, severity, observed_value_json, threshold_json, contributing_record_ids_json, waiver_required, caveat, missing_data, stale_data FROM risk_check_rule_results WHERE receipt_id = ? ORDER BY rule_id",
        (receipt_id,),
    ).fetchall()
    return {
        "id": row[0], "receipt_hash": row[1], "policy_version_id": row[2], "status": row[3],
        "outcome": row[4], "intended_action": row[5], "proposed_intent_hash": row[6],
        "decision_id": row[7], "market_id": row[8], "instrument_id": row[9],
        "strategy_id": row[10], "snapshot_id": row[11], "as_of": row[12], "created_at": row[13],
        "rule_results": [{
            "rule_id": r[0], "reason_code": r[1], "severity": r[2],
            "observed_value": json.loads(r[3]) if r[3] else None,
            "threshold": json.loads(r[4]) if r[4] else None,
            "contributing_record_ids": json.loads(r[5]), "waiver_required": bool(r[6]),
            "caveat": r[7], "missing_data": bool(r[8]), "stale_data": bool(r[9]),
        } for r in rules],
    }


def _risk_check_record(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    policy_version_id = require(args, "policy_version_id")
    status = require(args, "status")
    outcome = require(args, "outcome")
    if status not in STATUSES or outcome not in OUTCOMES:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown risk receipt status/outcome", details={"status": status, "outcome": outcome})
    if status == "pass" and outcome != "pass":
        raise ToolError(ErrorCode.VALIDATION_ERROR, "pass status requires pass outcome", details={"field": "outcome"})
    rule_results = _list_arg(args, "rule_results")
    _guard_json(rule_results, field="rule_results")
    if status == "missing_data" and not any(r.get("missing_data") for r in rule_results if isinstance(r, dict)):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "missing_data status requires a missing-data rule caveat", details={"field": "rule_results"})
    as_of = normalize_timestamp(args, "as_of", required=True)
    exposure_ids = _list_arg(args, "exposure_input_ids_json")
    evidence_ids = _list_arg(args, "evidence_input_ids_json")
    provenance = _dict_arg(args, "input_provenance_json")
    _guard_json(exposure_ids, field="exposure_input_ids_json")
    _guard_json(evidence_ids, field="evidence_input_ids_json")
    _guard_json(provenance, field="input_provenance_json")
    for field in (
        "intended_action", "proposed_intent_hash", "decision_id", "market_id",
        "instrument_id", "strategy_id", "snapshot_id", "waived_by", "waiver_reason",
    ):
        _guard_text(args.get(field), field=field)
    if not any(args.get(field) for field in RECEIPT_ANCHOR_FIELDS) and not exposure_ids and not evidence_ids:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "risk receipt must include at least one audit anchor", details={"field": "receipt_anchor"})
    validated_rule_results: list[dict[str, Any]] = []
    for rr in rule_results:
        if not isinstance(rr, dict):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "rule_results entries must be objects", details={"field": "rule_results"})
        for field in ("rule_id", "reason_code", "severity"):
            if not rr.get(field):
                raise ToolError(ErrorCode.VALIDATION_ERROR, f"rule result requires {field}", details={"field": field})
        severity = rr["severity"]
        if severity not in SEVERITIES:
            raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown rule severity", details={"field": "severity"})
        if "waiver_required" not in rr or not isinstance(rr.get("waiver_required"), bool):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "rule result requires explicit boolean waiver_required", details={"field": "waiver_required"})
        if "contributing_record_ids" not in rr or not isinstance(rr.get("contributing_record_ids"), list):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "rule result requires contributing_record_ids array", details={"field": "contributing_record_ids"})
        missing_or_stale = bool(rr.get("missing_data")) or bool(rr.get("stale_data"))
        if missing_or_stale and not rr.get("caveat"):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "missing_data or stale_data rule requires caveat", details={"field": "caveat"})
        if not missing_or_stale and ("observed_value" not in rr or "threshold" not in rr):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "non-missing rule requires observed_value and threshold", details={"field": "observed_value"})
        validated_rule_results.append(rr)
    has_missing_data = any(bool(rr.get("missing_data")) for rr in validated_rule_results)
    has_stale_data = any(bool(rr.get("stale_data")) for rr in validated_rule_results)
    if has_missing_data and status != "missing_data":
        raise ToolError(ErrorCode.VALIDATION_ERROR, "missing_data rule requires aggregate missing_data status", details={"field": "status"})
    if has_stale_data and status == "pass":
        raise ToolError(ErrorCode.VALIDATION_ERROR, "stale_data rule cannot have aggregate pass status", details={"field": "status"})
    receipt_material = {
        "policy_version_id": policy_version_id, "status": status, "outcome": outcome,
        "intended_action": args.get("intended_action"), "proposed_intent_hash": args.get("proposed_intent_hash"),
        "decision_id": args.get("decision_id"), "market_id": args.get("market_id"),
        "instrument_id": args.get("instrument_id"), "strategy_id": args.get("strategy_id"),
        "snapshot_id": args.get("snapshot_id"), "exposure_input_ids_json": exposure_ids,
        "evidence_input_ids_json": evidence_ids, "input_provenance_json": provenance, "as_of": as_of,
        "waived_by": args.get("waived_by"), "waiver_reason": args.get("waiver_reason"),
        "rule_results": validated_rule_results,
    }
    computed_receipt_hash = _hash_payload("risk_receipt", receipt_material)
    receipt_hash = args.get("receipt_hash") or computed_receipt_hash
    if receipt_hash != computed_receipt_hash:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "receipt_hash does not match canonical receipt payload", details={"field": "receipt_hash"})
    idempotency_key = args.get("idempotency_key")

    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(uow, event_type=_RECEIPT_EVENT, actor_id=ctx.actor_id, idempotency_key=idempotency_key)
            if replay is not None:
                emit_event(uow, event_type=_RECEIPT_EVENT, subject_kind="risk_check_receipt", subject_id=replay["id"], payload={"id": replay["id"], **receipt_material, "receipt_hash": receipt_hash}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
                return _receipt_response(uow.conn, replay["id"])
            receipt_id = args.get("id") or new_id("rcr")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO risk_check_receipts(id, receipt_hash, policy_version_id, status, outcome, intended_action, proposed_intent_hash, decision_id, market_id, instrument_id, strategy_id, snapshot_id, exposure_input_ids_json, evidence_input_ids_json, input_provenance_json, as_of, waived_by, waiver_reason, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (receipt_id, receipt_hash, policy_version_id, status, outcome, args.get("intended_action"), args.get("proposed_intent_hash"), args.get("decision_id"), args.get("market_id"), args.get("instrument_id"), args.get("strategy_id"), args.get("snapshot_id"), _canonical_json(exposure_ids), _canonical_json(evidence_ids), _canonical_json(provenance), as_of, args.get("waived_by"), args.get("waiver_reason"), created_at, ctx.actor_id),
            )
            for rr in validated_rule_results:
                severity = rr["severity"]
                uow.execute(
                    "INSERT INTO risk_check_rule_results(id, receipt_id, rule_id, reason_code, severity, observed_value_json, threshold_json, contributing_record_ids_json, waiver_required, caveat, missing_data, stale_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id("rrr"), receipt_id, rr["rule_id"], rr["reason_code"], severity, _canonical_json(rr.get("observed_value")) if "observed_value" in rr else None, _canonical_json(rr.get("threshold")) if "threshold" in rr else None, _canonical_json(rr["contributing_record_ids"]), 1 if rr["waiver_required"] else 0, rr.get("caveat"), 1 if rr.get("missing_data") else 0, 1 if rr.get("stale_data") else 0),
                )
            emit_event(uow, event_type=_RECEIPT_EVENT, subject_kind="risk_check_receipt", subject_id=receipt_id, payload={"id": receipt_id, **receipt_material, "receipt_hash": receipt_hash}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
            return _receipt_response(uow.conn, receipt_id)
    finally:
        db.close()


def register_risk_tools(registry: ToolRegistry) -> None:
    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    registry.register(
        "risk.policy_version_add", _risk_policy_version_add, is_write=True,
        description="Record an immutable audit-only risk policy version; no order blocking or execution is performed.",
        json_schema={"type": "object", "properties": {"policy_key": {"type": "string"}, "version": {"type": "string"}, "limits_json": {"type": "object"}, "rules_json": {"type": "array"}, "source": {"type": "string"}, "provenance_json": {"type": "object"}, "effective_from": {"type": "string"}, "effective_to": {"type": "string"}, "policy_hash": {"type": "string"}, "idempotency_key": {"type": "string"}, "home": {"type": "string"}}, "required": ["policy_key", "version", "limits_json", "rules_json", "source", "effective_from"]},
        **_examples_for("risk.policy_version_add"),
    )
    registry.register(
        "risk.check_record", _risk_check_record, is_write=True,
        description="Record an audit-only pre-trade risk-check receipt from an external/profile risk layer; no order blocking or execution is performed.",
        json_schema={"type": "object", "properties": {"policy_version_id": {"type": "string"}, "status": {"type": "string", "enum": sorted(STATUSES)}, "outcome": {"type": "string", "enum": sorted(OUTCOMES)}, "intended_action": {"type": "string"}, "proposed_intent_hash": {"type": "string"}, "decision_id": {"type": "string"}, "market_id": {"type": "string"}, "instrument_id": {"type": "string"}, "strategy_id": {"type": "string"}, "snapshot_id": {"type": "string"}, "exposure_input_ids_json": {"type": "array"}, "evidence_input_ids_json": {"type": "array"}, "input_provenance_json": {"type": "object"}, "as_of": {"type": "string"}, "rule_results": {"type": "array"}, "waived_by": {"type": "string"}, "waiver_reason": {"type": "string"}, "receipt_hash": {"type": "string"}, "idempotency_key": {"type": "string"}, "home": {"type": "string"}}, "required": ["policy_version_id", "status", "outcome", "as_of", "rule_results"]},
        **_examples_for("risk.check_record"),
    )


__all__ = ["register_risk_tools"]
