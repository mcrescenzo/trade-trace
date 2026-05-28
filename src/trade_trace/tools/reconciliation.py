"""Local reconciliation record and mismatch report tools.

Reconciliation compares Trade Trace local projections with caller-imported
external execution/account facts. It is evidence for external operators only:
no venue client, private-auth fetch, signing, order action, cancellation,
settlement, fund movement, scheduler, or remediation path exists here.
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

_EVENT = "reconciliation.recorded"
_SCHEMA_VERSION = "reconciliation_result.v1"
_SEVERITIES = {"none", "info", "warning", "critical"}
_RESOLUTION = {"unresolved", "explained", "accepted_caveat", "superseded", "not_applicable"}
_SOURCE_PRECEDENCE = [
    "imported_account_snapshots",
    "imported_external_execution_receipts",
    "local_position_projection",
    "paper_fill_records",
    "event_exposure_sets",
    "pretrade_intents",
    "approval_waiver_records",
    "risk_check_receipts",
]
_MISMATCH_CODES = {
    "MISSING_EXTERNAL_EVENT",
    "ORPHAN_EXTERNAL_ORDER",
    "ORPHAN_EXTERNAL_FILL",
    "DUPLICATE_FILL",
    "REJECTED_APPROVED_INTENT",
    "PARTIAL_FILL_REMAINING_MISMATCH",
    "POSITION_MISMATCH",
    "PRICE_MISMATCH",
    "FEE_MISMATCH",
    "BALANCE_MISMATCH",
    "EXPOSURE_MISMATCH",
    "STALE_SNAPSHOT",
    "AMBIGUOUS_RESOLUTION",
    "POLICY_WAIVER_BREACH",
    "MISSING_APPROVAL",
    "EVENT_EXPOSURE_UNAVAILABLE",
    "NEGATIVE_RISK_CAVEAT",
}
_SELECT = "id, schema_version, semantic_key, material_hash, as_of, source, source_precedence_json, expected_state_json, observed_imported_state_json, diff_json, diff_severity, mismatch_codes_json, resolution_status, contributing_ids_json, caveats_json, provenance_json, imported_at, recorded_at, idempotency_key, actor_id"


def _canonical_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"), default=str)


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


def _hash_material(material: dict[str, Any]) -> str:
    return hashlib.sha256(f"reconciliation:{_canonical_json(material)}".encode()).hexdigest()


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _num_from_obj(obj: Any, *keys: str) -> Decimal | None:
    if not isinstance(obj, dict):
        return None
    for key in keys:
        val = _dec(obj.get(key))
        if val is not None:
            return val
    return None


def _row(row: Any) -> dict[str, Any]:
    return {
        "id": row[0], "schema_version": row[1], "semantic_key": row[2], "material_hash": row[3],
        "as_of": row[4], "source": row[5], "source_precedence": json.loads(row[6]),
        "expected_state": json.loads(row[7]), "observed_imported_state": json.loads(row[8]),
        "diff": json.loads(row[9]), "diff_severity": row[10], "mismatch_codes": json.loads(row[11]),
        "resolution_status": row[12], "contributing_ids": json.loads(row[13]), "caveats": json.loads(row[14]),
        "provenance": json.loads(row[15]), "imported_at": row[16], "recorded_at": row[17],
        "idempotency_key": row[18], "actor_id": row[19], "record_kind": "local_reconciliation_result",
        "local_evidence_only": True, "non_executing": True, "credential_blind": True,
    }


def _response(conn: Any, record_id: str) -> dict[str, Any]:
    row = conn.execute(f"SELECT {_SELECT} FROM reconciliation_records WHERE id = ?", (record_id,)).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "reconciliation record not found", details={"id": record_id})
    return _row(row)


def _latest_snapshot(conn: Any, as_of: str | None) -> dict[str, Any] | None:
    clause = "WHERE as_of <= ?" if as_of else ""
    params: tuple[Any, ...] = (as_of,) if as_of else ()
    row = conn.execute(
        f"SELECT id, as_of, imported_at, staleness_status, source_system, source_precedence, balances_json, positions_json, open_orders_json, caveats_json FROM account_snapshots {clause} ORDER BY source_precedence ASC, as_of DESC, imported_at DESC, id DESC LIMIT 1",
        params,
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "as_of": row[1], "imported_at": row[2], "staleness_status": row[3], "source_system": row[4], "source_precedence": row[5], "balances": json.loads(row[6]), "positions": json.loads(row[7]), "open_orders": json.loads(row[8]), "caveats": json.loads(row[9])}


def _build_derived(conn: Any, *, as_of: str, stale_snapshot_statuses: set[str]) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[str]], list[str], list[dict[str, Any]], str | None]:
    ids: dict[str, list[str]] = {"positions": [], "external_receipts": [], "account_snapshots": [], "paper_fills": [], "pretrade_intents": [], "approval_waiver_records": [], "risk_check_receipts": []}
    codes: set[str] = set()
    caveats: list[dict[str, Any]] = []
    positions = conn.execute("SELECT id, instrument_id, kind, side, status, avg_entry_price, updated_at FROM positions WHERE status IN ('open','partial') ORDER BY id").fetchall()
    local_positions = []
    for row in positions:
        ids["positions"].append(row[0])
        local_positions.append({"id": row[0], "instrument_id": row[1], "kind": row[2], "side": row[3], "status": row[4], "avg_entry_price": row[5], "updated_at": row[6]})
    expected = {"projection_source": "positions", "open_positions": local_positions, "open_position_count": len(local_positions)}

    snapshot = _latest_snapshot(conn, as_of)
    observed: dict[str, Any] = {"external_receipts": [], "account_snapshot": snapshot}
    imported_at: str | None = None
    if snapshot is None:
        codes.add("BALANCE_MISMATCH")
        codes.add("POSITION_MISMATCH")
        caveats.append({"code": "IMPORTED_ACCOUNT_SNAPSHOT_UNAVAILABLE", "message": "No imported account snapshot at or before as_of; reconciliation is absence-caveated."})
    else:
        ids["account_snapshots"].append(snapshot["id"])
        imported_at = snapshot["imported_at"]
        if snapshot["staleness_status"] in stale_snapshot_statuses:
            codes.add("STALE_SNAPSHOT")
    imported_positions = snapshot.get("positions", []) if snapshot else []
    if snapshot is not None and len(imported_positions) != len(local_positions):
        codes.add("POSITION_MISMATCH")
    if snapshot is not None and any(_num_from_obj(b, "total", "available", "balance") is None for b in snapshot.get("balances", [])):
        codes.add("BALANCE_MISMATCH")

    receipts = conn.execute("SELECT id, lifecycle_state, external_event_type, pretrade_intent_id, approval_ref_id, external_order_ref, external_fill_ref, imported_at, sanitized_facts_json, caveats_json FROM external_execution_receipts WHERE as_of <= ? ORDER BY imported_at, id", (as_of,)).fetchall()
    seen_fills: set[str] = set()
    for row in receipts:
        rid, state, etype, intent_id, approval_id, order_ref, fill_ref, rec_imported_at, facts_json, caveats_json = row
        ids["external_receipts"].append(rid)
        imported_at = max(imported_at or rec_imported_at, rec_imported_at)
        facts = json.loads(facts_json)
        observed["external_receipts"].append({"id": rid, "lifecycle_state": state, "external_event_type": etype, "pretrade_intent_id": intent_id, "approval_ref_id": approval_id, "external_order_ref": order_ref, "external_fill_ref": fill_ref, "sanitized_facts": facts})
        if not intent_id:
            codes.add("ORPHAN_EXTERNAL_FILL" if etype == "fill" else "ORPHAN_EXTERNAL_ORDER")
        else:
            ids["pretrade_intents"].append(intent_id)
            intent = conn.execute("SELECT approval_state, risk_check_receipt_id, approval_ref_id FROM pretrade_intents WHERE id = ?", (intent_id,)).fetchone()
            if intent is None:
                codes.add("MISSING_EXTERNAL_EVENT")
            else:
                if intent[1]:
                    ids["risk_check_receipts"].append(intent[1])
                effective_approval = approval_id or intent[2]
                if effective_approval:
                    ids["approval_waiver_records"].append(effective_approval)
                if intent[0] in {"approved_elsewhere", "waived_elsewhere"} and state == "rejected":
                    codes.add("REJECTED_APPROVED_INTENT")
                if intent[0] == "pending_external_review" and state in {"accepted", "partial_fill", "filled"}:
                    codes.add("MISSING_APPROVAL")
        if etype == "fill" and fill_ref:
            if fill_ref in seen_fills:
                codes.add("DUPLICATE_FILL")
            seen_fills.add(fill_ref)
        if state == "partial_fill":
            requested = _num_from_obj(facts, "requested_quantity", "quantity")
            filled = _num_from_obj(facts, "filled_quantity", "fill_quantity")
            remaining = _num_from_obj(facts, "remaining_quantity")
            if requested is not None and filled is not None and remaining is not None and requested - filled != remaining:
                codes.add("PARTIAL_FILL_REMAINING_MISMATCH")
        if _num_from_obj(facts, "average_fill_price", "price") is None and etype == "fill":
            codes.add("PRICE_MISMATCH")
        if _num_from_obj(facts, "fee_amount", "fee") is None and etype == "fill":
            codes.add("FEE_MISMATCH")
        for caveat in json.loads(caveats_json):
            if isinstance(caveat, dict) and "negative" in str(caveat.get("code", "")).lower():
                codes.add("NEGATIVE_RISK_CAVEAT")

    if not receipts and local_positions:
        codes.add("MISSING_EXTERNAL_EVENT")
    paper = conn.execute("SELECT id, pretrade_intent_id, fill_status, remaining_quantity FROM paper_fill_records ORDER BY order_as_of DESC, id").fetchall()
    for row in paper:
        ids["paper_fills"].append(row[0])
        if row[2] == "partial" and _dec(row[3]) not in (None, Decimal("0")):
            codes.add("PARTIAL_FILL_REMAINING_MISMATCH")
    if local_positions and not _event_metadata_available(conn, [p["instrument_id"] for p in local_positions]):
        codes.add("EVENT_EXPOSURE_UNAVAILABLE")
    if _policy_waiver_breach(conn):
        codes.add("POLICY_WAIVER_BREACH")
    return expected, observed, ids, sorted(codes), caveats, imported_at


def _event_metadata_available(conn: Any, instrument_ids: list[str]) -> bool:
    if not instrument_ids:
        return True
    placeholders = ",".join("?" for _ in instrument_ids)
    rows = conn.execute(f"SELECT metadata_json FROM markets WHERE id IN ({placeholders})", tuple(instrument_ids)).fetchall()
    if not rows:
        return False
    for row in rows:
        try:
            meta = json.loads(row[0] or "{}")
        except json.JSONDecodeError:
            return False
        grouping = meta.get("event_grouping") or {}
        identity = meta.get("polymarket_identity") or {}
        if not (grouping.get("event_id") or grouping.get("event_slug") or identity.get("gamma_event_id") or identity.get("event_slug")):
            return False
    return True


def _policy_waiver_breach(conn: Any) -> bool:
    row = conn.execute("SELECT 1 FROM approval_waiver_records WHERE decision IN ('rejected','denied') OR hard_block_policy_permitted = 1 OR violation_visible = 1 LIMIT 1").fetchone()
    return row is not None


def _severity(codes: list[str]) -> str:
    if not codes:
        return "none"
    if any(code in codes for code in {"POLICY_WAIVER_BREACH", "DUPLICATE_FILL", "REJECTED_APPROVED_INTENT"}):
        return "critical"
    return "warning"


def _reconciliation_record(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    schema_version = str(args.get("schema_version") or _SCHEMA_VERSION)
    if schema_version != _SCHEMA_VERSION:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unsupported reconciliation schema_version", details={"field": "schema_version"})
    as_of = normalize_timestamp(args, "as_of", required=True)
    if as_of is None:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "as_of is required", details={"field": "as_of"})
    semantic_key = str(require(args, "semantic_key"))
    reject_if_contains_secrets(semantic_key, field="semantic_key")
    source = str(args.get("source") or "derived_local_reconciliation")
    reject_if_contains_secrets(source, field="source")
    source_precedence = _list_arg(args, "source_precedence") if args.get("source_precedence") else list(_SOURCE_PRECEDENCE)
    resolution_status = str(args.get("resolution_status") or "unresolved")
    if resolution_status not in _RESOLUTION:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown reconciliation resolution_status", details={"field": "resolution_status"})
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            expected, observed, ids, codes, caveats, imported_at = _build_derived(uow.conn, as_of=as_of, stale_snapshot_statuses={"stale", "missing", "unknown"})
            caller_codes = [str(code) for code in _list_arg(args, "mismatch_codes")]
            invalid = [code for code in caller_codes if code not in _MISMATCH_CODES]
            if invalid:
                raise ToolError(ErrorCode.VALIDATION_ERROR, "mismatch_codes contains unknown code", details={"field": "mismatch_codes", "invalid": invalid})
            codes = sorted(set(codes).union(caller_codes))
            diff = _dict_arg(args, "diff") if args.get("diff") else {"mismatch_code_count": len(codes), "codes": codes}
            diff_severity = str(args.get("diff_severity") or _severity(codes))
            if diff_severity not in _SEVERITIES:
                raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown reconciliation diff_severity", details={"field": "diff_severity"})
            provenance = json.loads(store_metadata_json(args, "provenance_json"))
            caveats.extend(_list_arg(args, "caveats"))
            material = {"schema_version": schema_version, "semantic_key": semantic_key, "as_of": as_of, "source": source, "source_precedence": source_precedence, "expected_state": expected, "observed_imported_state": observed, "diff": diff, "diff_severity": diff_severity, "mismatch_codes": codes, "resolution_status": resolution_status, "contributing_ids": ids, "caveats": caveats, "provenance": provenance, "imported_at": imported_at}
            material_hash = args.get("material_hash") or _hash_material(material)
            if material_hash != _hash_material(material):
                raise ToolError(ErrorCode.VALIDATION_ERROR, "material_hash does not match canonical reconciliation record", details={"field": "material_hash"})
            replay = check_idempotency_replay(uow, event_type=_EVENT, actor_id=ctx.actor_id, idempotency_key=args.get("idempotency_key"))
            if replay is not None:
                if replay.get("material_hash") != material_hash or replay.get("semantic_key") != semantic_key:
                    raise ToolError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "idempotency_key already recorded materially different reconciliation record",
                        details={
                            "code": "idempotency_conflict",
                            "idempotency_key": args.get("idempotency_key"),
                            "existing_id": replay.get("id"),
                        },
                    )
                return _response(uow.conn, replay["id"])
            existing = uow.conn.execute("SELECT id, material_hash FROM reconciliation_records WHERE semantic_key = ?", (semantic_key,)).fetchone()
            if existing is not None:
                if existing[1] == material_hash:
                    return _response(uow.conn, existing[0])
                raise ToolError(ErrorCode.IDEMPOTENCY_CONFLICT, "semantic_key already has materially different reconciliation record", details={"semantic_key": semantic_key, "existing_id": existing[0], "code": "semantic_conflict"})
            record_id = args.get("id") or new_id("rec")
            recorded_at = now_iso()
            uow.execute("INSERT INTO reconciliation_records(id, schema_version, semantic_key, material_hash, as_of, source, source_precedence_json, expected_state_json, observed_imported_state_json, diff_json, diff_severity, mismatch_codes_json, resolution_status, contributing_ids_json, caveats_json, provenance_json, imported_at, recorded_at, idempotency_key, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (record_id, schema_version, semantic_key, material_hash, as_of, source, _canonical_json(source_precedence), _canonical_json(expected), _canonical_json(observed), _canonical_json(diff), diff_severity, _canonical_json(codes), resolution_status, _canonical_json(ids), _canonical_json(caveats), _canonical_json(provenance), imported_at, recorded_at, args.get("idempotency_key"), ctx.actor_id))
            emit_event(uow, event_type=_EVENT, subject_kind="reconciliation_record", subject_id=record_id, payload={"id": record_id, **material, "material_hash": material_hash}, actor_id=ctx.actor_id, idempotency_key=args.get("idempotency_key"), ctx=ctx)
            return _response(uow.conn, record_id)
    finally:
        db.close()


def _reconciliation_get(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    db = open_db_for_args(args)
    try:
        return _response(db.connection, require(args, "id"))
    finally:
        db.close()


def _reconciliation_report(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    limit = min(int(args.get("limit", 100)), 500)
    where: list[str] = []
    params: list[Any] = []
    if args.get("resolution_status"):
        where.append("resolution_status = ?")
        params.append(args["resolution_status"])
    if args.get("diff_severity"):
        where.append("diff_severity = ?")
        params.append(args["diff_severity"])
    sql = f"SELECT {_SELECT} FROM reconciliation_records"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY as_of DESC, recorded_at DESC, id DESC LIMIT ?"
    db = open_db_for_args(args)
    try:
        records = [_row(row) for row in db.connection.execute(sql, (*params, limit)).fetchall()]
    finally:
        db.close()
    codes = sorted({code for record in records for code in record["mismatch_codes"]})
    return {"summary": {"bucket": "reconciliation_mismatches", "count": len(records), "mismatch_codes": codes, "source_precedence": list(_SOURCE_PRECEDENCE), "local_evidence_only": True, "non_executing": True}, "groups": records, "reconciliation_records": records, "report_kind": "local_reconciliation_mismatch_report", "agent_answer_hints": ["Use reconciliation rows as evidence for external operators; Trade Trace does not cancel, halt, remediate, fetch private state, or move funds.", "Current exposure remains caveated as local projected positions versus imported-observed positions when account snapshots are present."], "non_executing": True, "credential_blind": True}


def register_reconciliation_tools(registry: ToolRegistry) -> None:
    ex = WRITE_TOOL_EXAMPLES.get("reconciliation.record", {})
    props = {"schema_version": {"type": "string"}, "semantic_key": {"type": "string"}, "as_of": {"type": "string"}, "source": {"type": "string"}, "source_precedence": {"type": "array", "items": {"type": "string"}}, "diff": {"type": "object"}, "diff_severity": {"type": "string", "enum": sorted(_SEVERITIES)}, "mismatch_codes": {"type": "array", "items": {"type": "string", "enum": sorted(_MISMATCH_CODES)}}, "resolution_status": {"type": "string", "enum": sorted(_RESOLUTION)}, "caveats": {"type": "array"}, "provenance_json": {"type": "object"}, "material_hash": {"type": "string"}, "idempotency_key": {"type": "string"}, "home": {"type": "string"}}
    registry.register("reconciliation.record", _reconciliation_record, is_write=True, example_minimal=ex.get("minimal") or {"semantic_key": "recon:example", "as_of": "2026-01-20T00:00:00Z"}, example_rich=ex.get("rich"), description="Record an append-only local reconciliation snapshot/result comparing local projection to imported external facts; no fetch, signing, execution, cancellation, settlement, fund movement, or remediation.", json_schema={"type": "object", "properties": props, "required": ["semantic_key", "as_of"]})
    registry.register("reconciliation.get", _reconciliation_get, description="Read one local reconciliation result record.", json_schema={"type": "object", "properties": {"id": {"type": "string"}, "home": {"type": "string"}}, "required": ["id"]})
    registry.register("report.reconciliation_mismatches", _reconciliation_report, description="Report local reconciliation mismatch records and stable mismatch codes for external operators; no remediation or execution path.", json_schema={"type": "object", "properties": {"resolution_status": {"type": "string", "enum": sorted(_RESOLUTION)}, "diff_severity": {"type": "string", "enum": sorted(_SEVERITIES)}, "limit": {"type": "integer"}, "home": {"type": "string"}}, "required": []})


__all__ = ["register_reconciliation_tools"]
