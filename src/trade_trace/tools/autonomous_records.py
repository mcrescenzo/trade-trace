"""Append-only autonomous run/session and incident local evidence tools.

The records in this module are durable audit facts for profile-owned cycles.
They intentionally do not supervise runtime, schedule cycles, host agents, fetch
private broker/account state, execute/cancel orders, alert, or remediate.
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
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    open_db_for_args,
    reject_credential_metadata,
    reject_if_contains_secrets,
    require,
)
from trade_trace.tools.errors import ToolError

_RUN_EVENT = "autonomous_run.recorded"
_INCIDENT_EVENT = "autonomous_incident.recorded"
_RUN_SCHEMA = "autonomous_run.v1"
_INCIDENT_SCHEMA = "autonomous_incident.v1"
_RUN_STATUSES = {"started", "running", "completed", "failed", "blocked", "canceled", "timed_out", "unknown"}
_MODES = {"autonomous", "assisted", "manual_replay", "simulation", "dry_run", "unknown"}
_INCIDENT_TYPES = {"blocked_action", "kill_switch", "cancel_only", "missing_evidence", "policy_violation", "reconciliation_mismatch", "approval_gap", "execution_receipt_gap", "recovery_item", "operator_note", "other"}
_SEVERITIES = {"info", "warning", "critical"}
_RESOLUTION = {"unresolved", "monitoring", "explained", "accepted_caveat", "resolved", "superseded", "not_applicable"}
_EVIDENCE_STATES = {"complete", "sparse", "missing", "conflicting", "unknown"}
_RUN_SELECT = "id, schema_version, semantic_key, material_hash, mode, run_status, run_id, session_id, actor_id_recorded, model_id, provider_id, environment_label, policy_version, started_at, ended_at, as_of, config_json, provenance_json, caveats_json, recorded_at, idempotency_key, recorder_actor_id"
_INCIDENT_SELECT = "id, schema_version, semantic_key, material_hash, incident_type, severity, resolution_status, run_record_id, run_id, session_id, occurred_at, as_of, summary, imported_fact_only, evidence_state, link_ids_json, evidence_refs_json, caveats_json, provenance_json, recorded_at, idempotency_key, recorder_actor_id"
_SENSITIVE_LINK_KEYS = {
    "actor",
    "actorid",
    "actorids",
    "actorlabel",
    "actorlabels",
    "accountid",
    "accountids",
    "accountlabel",
    "accountlabels",
    "strategyid",
    "strategyids",
    "strategylabel",
    "strategylabels",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"), default=str)


def _json_arg(args: dict[str, Any], field: str, default: Any) -> Any:
    value = args.get(field, default)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            reject_if_contains_secrets(value, field=field)
            raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be valid JSON", details={"field": field, "code": "malformed_json_quarantined"}) from exc
    reject_credential_metadata(value, field=field)
    return value


def _dict_arg(args: dict[str, Any], field: str) -> dict[str, Any]:
    value = _json_arg(args, field, {})
    if not isinstance(value, dict):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an object", details={"field": field})
    return value


def _list_arg(args: dict[str, Any], field: str) -> list[Any]:
    value = _json_arg(args, field, [])
    if not isinstance(value, list):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an array", details={"field": field})
    return value


def _safe_text(args: dict[str, Any], field: str, *, required: bool = False) -> str | None:
    value = require(args, field) if required else args.get(field)
    if value is None:
        return None
    text = str(value)
    reject_if_contains_secrets(text, field=field)
    return text


def _hash_material(prefix: str, material: dict[str, Any]) -> str:
    return hashlib.sha256(f"{prefix}:{_canonical_json(material)}".encode()).hexdigest()


def _normalize_link_key(key: Any) -> str:
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


def _hash_redacted_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _hash_redacted_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_hash_redacted_value(v) for v in value]
    if value is None:
        return None
    return f"sha256:{hashlib.sha256(str(value).encode()).hexdigest()[:12]}"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (_hash_redacted_value(v) if _normalize_link_key(k) in _SENSITIVE_LINK_KEYS else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _run_row(row: Any) -> dict[str, Any]:
    return {"id": row[0], "schema_version": row[1], "semantic_key": row[2], "material_hash": row[3], "mode": row[4], "run_status": row[5], "run_id": row[6], "session_id": row[7], "actor_id_recorded": row[8], "model_id": row[9], "provider_id": row[10], "environment_label": row[11], "policy_version": row[12], "started_at": row[13], "ended_at": row[14], "as_of": row[15], "config": json.loads(row[16]), "provenance": json.loads(row[17]), "caveats": json.loads(row[18]), "recorded_at": row[19], "idempotency_key": row[20], "recorder_actor_id": row[21], "record_kind": "autonomous_run_record", "local_evidence_only": True, "non_supervising": True, "non_executing": True, "credential_blind": True}


def _incident_row(row: Any, *, public: bool = False) -> dict[str, Any]:
    links = json.loads(row[15])
    out = {"id": row[0], "schema_version": row[1], "semantic_key": row[2], "material_hash": row[3], "incident_type": row[4], "severity": row[5], "resolution_status": row[6], "run_record_id": row[7], "run_id": row[8], "session_id": row[9], "occurred_at": row[10], "as_of": row[11], "summary": row[12], "imported_fact_only": bool(row[13]), "evidence_state": row[14], "link_ids": _redact(links) if public else links, "evidence_refs": json.loads(row[16]), "caveats": json.loads(row[17]), "provenance": json.loads(row[18]), "recorded_at": row[19], "idempotency_key": row[20], "recorder_actor_id": row[21], "record_kind": "autonomous_incident_record", "local_evidence_only": True, "non_supervising": True, "non_executing": True, "credential_blind": True}
    if public:
        for key in ("run_id", "session_id"):
            if out.get(key):
                out[f"{key}_hash"] = hashlib.sha256(str(out[key]).encode()).hexdigest()[:12]
                out[key] = None
    return out


def _run_response(conn: Any, record_id: str) -> dict[str, Any]:
    row = conn.execute(f"SELECT {_RUN_SELECT} FROM autonomous_run_records WHERE id = ?", (record_id,)).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "autonomous run record not found", details={"id": record_id})
    return _run_row(row)


def _incident_response(conn: Any, record_id: str, *, public: bool = False) -> dict[str, Any]:
    row = conn.execute(f"SELECT {_INCIDENT_SELECT} FROM autonomous_incident_records WHERE id = ?", (record_id,)).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "autonomous incident record not found", details={"id": record_id})
    return _incident_row(row, public=public)


def _record_run(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    schema_version = str(args.get("schema_version") or _RUN_SCHEMA)
    if schema_version != _RUN_SCHEMA:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unsupported autonomous run schema_version", details={"field": "schema_version"})
    mode = str(require(args, "mode"))
    status = str(require(args, "run_status"))
    if mode not in _MODES or status not in _RUN_STATUSES:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown autonomous run mode/status", details={"mode": mode, "run_status": status})
    started_at = normalize_timestamp(args, "started_at", required=True)
    ended_at = normalize_timestamp(args, "ended_at")
    as_of = normalize_timestamp(args, "as_of") or ended_at or started_at
    config = _dict_arg(args, "config_json")
    provenance = _dict_arg(args, "provenance_json")
    caveats = _list_arg(args, "caveats")
    if ended_at is None and status in {"completed", "failed", "blocked", "canceled", "timed_out"}:
        caveats.append({"code": "run_terminal_status_without_end_time", "message": "Terminal run status was recorded without ended_at."})
    text = {f: _safe_text(args, f, required=f in {"semantic_key", "run_id"}) for f in ("semantic_key", "run_id", "session_id", "actor_id_recorded", "model_id", "provider_id", "environment_label", "policy_version")}
    material = {"schema_version": schema_version, "mode": mode, "run_status": status, **text, "started_at": started_at, "ended_at": ended_at, "as_of": as_of, "config": config, "provenance": provenance, "caveats": caveats}
    material_hash = args.get("material_hash") or _hash_material("autonomous_run", material)
    if material_hash != _hash_material("autonomous_run", material):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "material_hash does not match canonical autonomous run", details={"field": "material_hash"})
    idempotency_key = args.get("idempotency_key")
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(uow, event_type=_RUN_EVENT, actor_id=ctx.actor_id, idempotency_key=idempotency_key)
            if replay is not None:
                emit_event(uow, event_type=_RUN_EVENT, subject_kind="autonomous_run", subject_id=replay["id"], payload={"id": replay["id"], **material, "material_hash": material_hash, "idempotency_key": idempotency_key}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
                return _run_response(uow.conn, replay["id"])
            existing = uow.conn.execute("SELECT id, material_hash FROM autonomous_run_records WHERE semantic_key = ?", (text["semantic_key"],)).fetchone()
            if existing is not None:
                if existing[1] == material_hash:
                    return _run_response(uow.conn, existing[0])
                raise ToolError(ErrorCode.IDEMPOTENCY_CONFLICT, "semantic_key already has materially different autonomous run", details={"semantic_key": text["semantic_key"], "existing_id": existing[0], "code": "semantic_conflict"})
            rid = args.get("id") or new_id("arun")
            uow.execute("INSERT INTO autonomous_run_records(id, schema_version, semantic_key, material_hash, mode, run_status, run_id, session_id, actor_id_recorded, model_id, provider_id, environment_label, policy_version, started_at, ended_at, as_of, config_json, provenance_json, caveats_json, recorded_at, idempotency_key, recorder_actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (rid, schema_version, text["semantic_key"], material_hash, mode, status, text["run_id"], text["session_id"], text["actor_id_recorded"], text["model_id"], text["provider_id"], text["environment_label"], text["policy_version"], started_at, ended_at, as_of, _canonical_json(config), _canonical_json(provenance), _canonical_json(caveats), now_iso(), idempotency_key, ctx.actor_id))
            emit_event(uow, event_type=_RUN_EVENT, subject_kind="autonomous_run", subject_id=rid, payload={"id": rid, **material, "material_hash": material_hash, "idempotency_key": idempotency_key}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
            return _run_response(uow.conn, rid)
    finally:
        db.close()


def _record_incident(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    schema_version = str(args.get("schema_version") or _INCIDENT_SCHEMA)
    if schema_version != _INCIDENT_SCHEMA:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unsupported autonomous incident schema_version", details={"field": "schema_version"})
    incident_type = str(require(args, "incident_type"))
    severity = str(args.get("severity") or "warning")
    status = str(args.get("resolution_status") or "unresolved")
    evidence_state = str(args.get("evidence_state") or "unknown")
    if incident_type not in _INCIDENT_TYPES or severity not in _SEVERITIES or status not in _RESOLUTION or evidence_state not in _EVIDENCE_STATES:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown autonomous incident classification", details={"incident_type": incident_type, "severity": severity, "resolution_status": status, "evidence_state": evidence_state})
    occurred_at = normalize_timestamp(args, "occurred_at", required=True)
    as_of = normalize_timestamp(args, "as_of") or occurred_at
    summary = _safe_text(args, "summary", required=True)
    links = _dict_arg(args, "link_ids")
    evidence_refs = _list_arg(args, "evidence_refs")
    caveats = _list_arg(args, "caveats")
    provenance = _dict_arg(args, "provenance_json")
    if evidence_state in {"sparse", "missing", "unknown"}:
        caveats.append({"code": f"incident_evidence_{evidence_state}", "message": "Incident is caveated because local supporting evidence is sparse, missing, or unknown."})
    if incident_type in {"blocked_action", "kill_switch", "cancel_only"}:
        caveats.append({"code": "external_control_fact_only", "message": "Recorded as an imported/local fact about an external system; Trade Trace performed no supervision or control action."})
    text = {f: _safe_text(args, f) for f in ("run_record_id", "run_id", "session_id")}
    material = {"schema_version": schema_version, "semantic_key": _safe_text(args, "semantic_key", required=True), "incident_type": incident_type, "severity": severity, "resolution_status": status, **text, "occurred_at": occurred_at, "as_of": as_of, "summary": summary, "imported_fact_only": bool(args.get("imported_fact_only", True)), "evidence_state": evidence_state, "link_ids": links, "evidence_refs": evidence_refs, "caveats": caveats, "provenance": provenance}
    material_hash = args.get("material_hash") or _hash_material("autonomous_incident", material)
    if material_hash != _hash_material("autonomous_incident", material):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "material_hash does not match canonical autonomous incident", details={"field": "material_hash"})
    idempotency_key = args.get("idempotency_key")
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            if text["run_record_id"] and uow.conn.execute("SELECT 1 FROM autonomous_run_records WHERE id = ?", (text["run_record_id"],)).fetchone() is None:
                raise ToolError(ErrorCode.VALIDATION_ERROR, "autonomous incident references missing run record", details={"field": "run_record_id", "id": text["run_record_id"]})
            replay = check_idempotency_replay(uow, event_type=_INCIDENT_EVENT, actor_id=ctx.actor_id, idempotency_key=idempotency_key)
            if replay is not None:
                emit_event(uow, event_type=_INCIDENT_EVENT, subject_kind="autonomous_incident", subject_id=replay["id"], payload={"id": replay["id"], **material, "material_hash": material_hash, "idempotency_key": idempotency_key}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
                return _incident_response(uow.conn, replay["id"])
            existing = uow.conn.execute("SELECT id, material_hash FROM autonomous_incident_records WHERE semantic_key = ?", (material["semantic_key"],)).fetchone()
            if existing is not None:
                if existing[1] == material_hash:
                    return _incident_response(uow.conn, existing[0])
                raise ToolError(ErrorCode.IDEMPOTENCY_CONFLICT, "semantic_key already has materially different autonomous incident", details={"semantic_key": material["semantic_key"], "existing_id": existing[0], "code": "semantic_conflict"})
            iid = args.get("id") or new_id("ainc")
            uow.execute("INSERT INTO autonomous_incident_records(id, schema_version, semantic_key, material_hash, incident_type, severity, resolution_status, run_record_id, run_id, session_id, occurred_at, as_of, summary, imported_fact_only, evidence_state, link_ids_json, evidence_refs_json, caveats_json, provenance_json, recorded_at, idempotency_key, recorder_actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (iid, schema_version, material["semantic_key"], material_hash, incident_type, severity, status, text["run_record_id"], text["run_id"], text["session_id"], occurred_at, as_of, summary, 1 if material["imported_fact_only"] else 0, evidence_state, _canonical_json(links), _canonical_json(evidence_refs), _canonical_json(caveats), _canonical_json(provenance), now_iso(), idempotency_key, ctx.actor_id))
            emit_event(uow, event_type=_INCIDENT_EVENT, subject_kind="autonomous_incident", subject_id=iid, payload={"id": iid, **material, "material_hash": material_hash, "idempotency_key": idempotency_key}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
            return _incident_response(uow.conn, iid)
    finally:
        db.close()


def _run_get(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    db = open_db_for_args(args)
    try:
        return _run_response(db.connection, require(args, "id"))
    finally:
        db.close()


def _incident_report(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    limit = max(1, min(int(args.get("limit", 25)), 200))
    where: list[str] = []
    params: list[Any] = []
    for field in ("incident_type", "severity", "resolution_status", "run_id", "session_id"):
        if args.get(field):
            where.append(f"{field} = ?")
            params.append(args[field])
    sql_where = " WHERE " + " AND ".join(where) if where else ""
    db = open_db_for_args(args)
    try:
        rows = db.connection.execute(f"SELECT {_INCIDENT_SELECT} FROM autonomous_incident_records{sql_where} ORDER BY occurred_at DESC, recorded_at DESC, id DESC LIMIT ?", (*params, limit)).fetchall()
        incidents = [_incident_row(r, public=True) for r in rows]
        blocked = [i for i in incidents if i["incident_type"] in {"blocked_action", "kill_switch", "cancel_only"}]
        unresolved = [i for i in incidents if i["resolution_status"] in {"unresolved", "monitoring"} or i["incident_type"] == "recovery_item"]
        run_record_ids = [str(i["run_record_id"]) for i in incidents if i.get("run_record_id")]
        contributing: dict[str, list[str]] = {"autonomous_incident_records": [i["id"] for i in incidents], "autonomous_run_records": sorted(set(run_record_ids))}
        caveat_codes = sorted(str(c["code"]) for i in incidents for c in i.get("caveats", []) if isinstance(c, dict) and c.get("code"))
        return {"kind": "report.autonomous_incidents", "contract_version": "report.autonomous_incidents.v1", "local_evidence_only": True, "non_supervising": True, "non_executing": True, "count": len(incidents), "recent_incidents": incidents, "blocked_actions": blocked, "unresolved_recovery_items": unresolved, "contributing_record_ids": contributing, "caveat_codes": caveat_codes, "redaction": "run/session ids and sensitive actor/account/strategy link labels are hashed in report output"}
    finally:
        db.close()


def register_autonomous_record_tools(registry: ToolRegistry) -> None:
    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    props = {"home": {"type": "string"}, "semantic_key": {"type": "string"}, "schema_version": {"type": "string"}, "idempotency_key": {"type": "string"}, "material_hash": {"type": "string"}}
    registry.register("autonomous_run.record", _record_run, is_write=True, **_examples_for("autonomous_run.record"), description="Append a local autonomous run/session status audit record; no runtime supervision, scheduling, hosting, fetching, execution, cancellation, alerting, or remediation.", json_schema={"type": "object", "properties": {**props, "mode": {"type": "string"}, "run_status": {"type": "string"}, "run_id": {"type": "string"}, "session_id": {"type": "string"}, "actor_id_recorded": {"type": "string"}, "model_id": {"type": "string"}, "provider_id": {"type": "string"}, "environment_label": {"type": "string"}, "policy_version": {"type": "string"}, "started_at": {"type": "string"}, "ended_at": {"type": "string"}, "as_of": {"type": "string"}, "config_json": {"type": "object"}, "provenance_json": {"type": "object"}, "caveats": {"type": "array"}}, "required": ["semantic_key", "mode", "run_status", "run_id", "started_at"]})
    registry.register("autonomous_run.get", _run_get, description="Read one local autonomous run/session audit record.", json_schema={"type": "object", "properties": {"id": {"type": "string"}, "home": {"type": "string"}}, "required": ["id"]})
    registry.register("autonomous_incident.record", _record_incident, is_write=True, **_examples_for("autonomous_incident.record"), description="Append a local autonomous incident/imported blocked-action fact; Trade Trace records evidence only and performs no supervision, alerts, cancel, kill-switch, or remediation action.", json_schema={"type": "object", "properties": {**props, "incident_type": {"type": "string"}, "severity": {"type": "string"}, "resolution_status": {"type": "string"}, "run_record_id": {"type": "string"}, "run_id": {"type": "string"}, "session_id": {"type": "string"}, "occurred_at": {"type": "string"}, "as_of": {"type": "string"}, "summary": {"type": "string"}, "imported_fact_only": {"type": "boolean"}, "evidence_state": {"type": "string"}, "link_ids": {"type": "object"}, "evidence_refs": {"type": "array"}, "caveats": {"type": "array"}, "provenance_json": {"type": "object"}}, "required": ["semantic_key", "incident_type", "occurred_at", "summary"]})
    registry.register("autonomous_incident.report", _incident_report, description="Read-only local report of recent autonomous incidents, blocked external-action facts, unresolved recovery items, caveats, and contributing record IDs with sensitive IDs redacted.", json_schema={"type": "object", "properties": {"home": {"type": "string"}, "incident_type": {"type": "string"}, "severity": {"type": "string"}, "resolution_status": {"type": "string"}, "run_id": {"type": "string"}, "session_id": {"type": "string"}, "limit": {"type": "integer"}}})


__all__ = ["register_autonomous_record_tools"]
