"""Externally supplied replay/evaluation artifact registry tools.

This is a local append-only evidence registry for strategy review. It records
caller-supplied datasets/results/provenance and never fetches data, runs a
simulation/backtest, optimizes a strategy, produces alpha, or gives advice.
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
    parse_int_arg,
    reject_credential_metadata,
    reject_if_contains_secrets,
    require,
)
from trade_trace.tools.errors import ToolError

_EVENT = "replay_evaluation_artifact.recorded"
_SCHEMA_VERSION = "replay_evaluation_artifact.v1"
_ARTIFACT_TYPES = {"historical_simulation", "paper", "imported_live", "evaluation_report", "dataset", "other"}
_EVIDENCE_MODES = {"historical_simulation", "paper", "imported_live", "other"}
_JSON_FIELDS = ("parameters", "assumptions", "fill_model", "slippage_model", "result_summary", "provenance")
_SELECT = "id, schema_version, semantic_key, material_hash, artifact_type, evidence_mode, dataset_hash, strategy_id, strategy_version, parameters_json, assumptions_json, fill_model_json, slippage_model_json, result_summary_json, sample_size, source_links_json, provenance_json, caveats_json, redaction_profile, redacted_artifact_ref, as_of, evaluated_at, imported_at, idempotency_key, actor_id"


def _canonical_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"), default=str)


def _json_arg(args: dict[str, Any], field: str, default: Any) -> Any:
    value = args.get(field, default)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            reject_if_contains_secrets(value, field=field)
            raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be valid JSON", details={"field": field, "code": "malformed_payload_quarantined"}) from exc
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


def _hash_material(material: dict[str, Any]) -> str:
    return hashlib.sha256(f"replay_evaluation_artifact:{_canonical_json(material)}".encode()).hexdigest()


def _row_to_response(row: Any) -> dict[str, Any]:
    return {
        "id": row[0], "schema_version": row[1], "semantic_key": row[2], "material_hash": row[3],
        "artifact_type": row[4], "evidence_mode": row[5], "dataset_hash": row[6], "strategy_id": row[7],
        "strategy_version": row[8], "parameters": json.loads(row[9]), "assumptions": json.loads(row[10]),
        "fill_model": json.loads(row[11]), "slippage_model": json.loads(row[12]),
        "result_summary": json.loads(row[13]), "sample_size": row[14], "source_links": json.loads(row[15]),
        "provenance": json.loads(row[16]), "caveats": json.loads(row[17]), "redaction_profile": row[18],
        "redacted_artifact_ref": row[19], "as_of": row[20], "evaluated_at": row[21], "imported_at": row[22],
        "idempotency_key": row[23], "actor_id": row[24],
        "record_kind": "externally_supplied_replay_evaluation_artifact", "local_evidence_only": True,
        "candidate_visible": False, "evaluator_only": True, "non_executing": True,
        "hard_constraints": {"no_fetch": True, "no_simulation_execution": True, "no_backtester": True, "no_strategy_optimization": True, "no_trading_advice": True},
    }


def _response(conn: Any, artifact_id: str) -> dict[str, Any]:
    row = conn.execute(f"SELECT {_SELECT} FROM replay_evaluation_artifacts WHERE id = ?", (artifact_id,)).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "replay evaluation artifact not found", details={"id": artifact_id})
    return _row_to_response(row)


def _record(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    schema_version = str(args.get("schema_version") or _SCHEMA_VERSION)
    if schema_version != _SCHEMA_VERSION:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unsupported replay artifact schema_version", details={"field": "schema_version"})
    artifact_type = str(args.get("artifact_type") or args.get("evidence_mode") or "evaluation_report")
    evidence_mode = str(args.get("evidence_mode") or (artifact_type if artifact_type in _EVIDENCE_MODES else "other"))
    if artifact_type not in _ARTIFACT_TYPES or evidence_mode not in _EVIDENCE_MODES:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown artifact_type or evidence_mode", details={"artifact_type": artifact_type, "evidence_mode": evidence_mode})
    as_of = normalize_timestamp(args, "as_of", required=True)
    evaluated_at = normalize_timestamp(args, "evaluated_at")
    if as_of is None:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "as_of is required", details={"field": "as_of"})
    payloads = {field: _dict_arg(args, field) for field in _JSON_FIELDS}
    source_links = _list_arg(args, "source_links")
    caveats = _list_arg(args, "caveats")
    sample_size = int(args.get("sample_size", payloads["result_summary"].get("sample_size", 0) or 0))
    if sample_size < 0:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "sample_size must be non-negative", details={"field": "sample_size"})
    if sample_size < 20:
        caveats.append({"code": "small_sample_size", "message": "Sample size is caller-supplied and small; do not infer strategy performance."})
    caveats.append({"code": f"evidence_mode_{evidence_mode}", "message": "Artifact evidence mode is caller supplied; Trade Trace did not execute a simulation/backtest or live decision."})
    material_base = {
        "schema_version": schema_version,
        "semantic_key": _safe_text(args, "semantic_key", required=True),
        "artifact_type": artifact_type,
        "evidence_mode": evidence_mode,
        "dataset_hash": _safe_text(args, "dataset_hash", required=True),
        "strategy_id": _safe_text(args, "strategy_id"),
        "strategy_version": _safe_text(args, "strategy_version", required=True),
        "parameters": payloads["parameters"],
        "assumptions": payloads["assumptions"],
        "fill_model": payloads["fill_model"],
        "slippage_model": payloads["slippage_model"],
        "result_summary": payloads["result_summary"],
        "sample_size": sample_size,
        "source_links": source_links,
        "provenance": payloads["provenance"],
        "caveats": caveats,
        "redaction_profile": _safe_text(args, "redaction_profile") or "metadata_only",
        "redacted_artifact_ref": _safe_text(args, "redacted_artifact_ref"),
        "as_of": as_of,
        "evaluated_at": evaluated_at,
    }
    material_hash = args.get("material_hash") or _hash_material(material_base)
    if material_hash != _hash_material(material_base):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "material_hash does not match canonical replay evaluation artifact", details={"field": "material_hash"})
    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(uow, event_type=_EVENT, actor_id=ctx.actor_id, idempotency_key=args.get("idempotency_key"))
            if replay is not None:
                emit_event(uow, event_type=_EVENT, subject_kind="replay_evaluation_artifact", subject_id=replay["id"], payload={"id": replay["id"], **material_base, "material_hash": material_hash}, actor_id=ctx.actor_id, idempotency_key=args.get("idempotency_key"), ctx=ctx)
                return _response(uow.conn, replay["id"])
            existing = uow.conn.execute("SELECT id, material_hash FROM replay_evaluation_artifacts WHERE semantic_key = ?", (material_base["semantic_key"],)).fetchone()
            if existing is not None:
                if existing[1] == material_hash:
                    return _response(uow.conn, existing[0])
                raise ToolError(ErrorCode.IDEMPOTENCY_CONFLICT, "semantic_key already has materially different replay evaluation artifact", details={"semantic_key": material_base["semantic_key"], "existing_id": existing[0], "code": "semantic_conflict"})
            material_existing = uow.conn.execute("SELECT id, semantic_key FROM replay_evaluation_artifacts WHERE material_hash = ?", (material_hash,)).fetchone()
            if material_existing is not None:
                if material_existing[1] == material_base["semantic_key"]:
                    return _response(uow.conn, material_existing[0])
                raise ToolError(ErrorCode.IDEMPOTENCY_CONFLICT, "material_hash already belongs to a different replay evaluation artifact semantic_key", details={"material_hash": material_hash, "existing_id": material_existing[0], "existing_semantic_key": material_existing[1], "semantic_key": material_base["semantic_key"], "code": "material_hash_conflict"})
            artifact_id = args.get("id") or new_id("rea")
            imported_at = now_iso()
            uow.execute(
                "INSERT INTO replay_evaluation_artifacts(id, schema_version, semantic_key, material_hash, artifact_type, evidence_mode, dataset_hash, strategy_id, strategy_version, parameters_json, assumptions_json, fill_model_json, slippage_model_json, result_summary_json, sample_size, source_links_json, provenance_json, caveats_json, redaction_profile, redacted_artifact_ref, as_of, evaluated_at, imported_at, idempotency_key, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (artifact_id, schema_version, material_base["semantic_key"], material_hash, artifact_type, evidence_mode, material_base["dataset_hash"], material_base["strategy_id"], material_base["strategy_version"], _canonical_json(payloads["parameters"]), _canonical_json(payloads["assumptions"]), _canonical_json(payloads["fill_model"]), _canonical_json(payloads["slippage_model"]), _canonical_json(payloads["result_summary"]), sample_size, _canonical_json(source_links), _canonical_json(payloads["provenance"]), _canonical_json(caveats), material_base["redaction_profile"], material_base["redacted_artifact_ref"], as_of, evaluated_at, imported_at, args.get("idempotency_key"), ctx.actor_id),
            )
            emit_event(uow, event_type=_EVENT, subject_kind="replay_evaluation_artifact", subject_id=artifact_id, payload={"id": artifact_id, **material_base, "material_hash": material_hash}, actor_id=ctx.actor_id, idempotency_key=args.get("idempotency_key"), ctx=ctx)
            return _response(uow.conn, artifact_id)


def _get(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    with db_for_args(args) as db:
        return _response(db.connection, require(args, "id"))


def _list(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    limit = min(parse_int_arg(args, "limit", 50, minimum=1), 200)
    where: list[str] = []
    params: list[Any] = []
    for field in ("artifact_type", "evidence_mode", "dataset_hash", "strategy_id", "strategy_version"):
        if args.get(field):
            where.append(f"{field} = ?")
            params.append(args[field])
    with db_for_args(args) as db:
        sql = f"SELECT {_SELECT} FROM replay_evaluation_artifacts"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY as_of DESC, imported_at DESC, id DESC LIMIT ?"
        rows = db.connection.execute(sql, (*params, limit)).fetchall()
        records = [_row_to_response(row) for row in rows]
        return {"records": records, "count": len(records), "report_caveats": ["Artifacts are externally supplied evidence, not Trade Trace backtest/simulation results.", "Distinguish evidence_mode and sample_size before comparing artifacts; no advice or performance recommendation is produced."], "non_executing": True}


def register_replay_artifact_tools(registry: ToolRegistry) -> None:
    ex = WRITE_TOOL_EXAMPLES.get("replay_artifact.record", {})
    props = {
        "schema_version": {"type": "string"}, "semantic_key": {"type": "string"},
        "artifact_type": {"type": "string", "enum": sorted(_ARTIFACT_TYPES)}, "evidence_mode": {"type": "string", "enum": sorted(_EVIDENCE_MODES)},
        "dataset_hash": {"type": "string"}, "strategy_id": {"type": "string"}, "strategy_version": {"type": "string"},
        "parameters": {"type": "object"}, "assumptions": {"type": "object"}, "fill_model": {"type": "object"}, "slippage_model": {"type": "object"},
        "result_summary": {"type": "object"}, "sample_size": {"type": "integer"}, "source_links": {"type": "array"}, "provenance": {"type": "object"}, "caveats": {"type": "array"},
        "redaction_profile": {"type": "string"}, "redacted_artifact_ref": {"type": "string"}, "as_of": {"type": "string"}, "evaluated_at": {"type": "string"},
        "material_hash": {"type": "string"}, "idempotency_key": {"type": "string"}, "home": {"type": "string"},
    }
    registry.register("replay_artifact.record", _record, is_write=True, example_minimal=ex.get("minimal"), example_rich=ex.get("rich"), description="Record one externally supplied replay/evaluation artifact for strategy review as local append-only evidence. No data fetch, simulation/backtest execution, optimization, advice, or order guidance is performed.", json_schema={"type": "object", "properties": props, "required": ["semantic_key", "dataset_hash", "strategy_version", "as_of"]})
    registry.register("replay_artifact.get", _get, description="Retrieve one externally supplied replay/evaluation artifact record by id; evaluator-only evidence, not candidate-visible context.", json_schema={"type": "object", "properties": {"id": {"type": "string"}, "home": {"type": "string"}}, "required": ["id"]})
    registry.register("replay_artifact.list", _list, description="List externally supplied replay/evaluation artifacts with evidence-mode/sample-size caveats; no advice or performance recommendation.", json_schema={"type": "object", "properties": {"artifact_type": {"type": "string"}, "evidence_mode": {"type": "string"}, "dataset_hash": {"type": "string"}, "strategy_id": {"type": "string"}, "strategy_version": {"type": "string"}, "limit": {"type": "integer"}, "home": {"type": "string"}}})


__all__ = ["register_replay_artifact_tools"]
