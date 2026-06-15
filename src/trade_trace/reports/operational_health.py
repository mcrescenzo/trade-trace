"""Read-only operational health report for local trader-intelligence inputs."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import process_filter
from trade_trace.storage.database import read_snapshot
from trade_trace.timestamps import (
    parse_report_timestamp_lenient_utc_naive_as_utc as _dt,
)
from trade_trace.tools._helpers import db_for_args, now_iso

REPORT_NAME = "report.operational_health"
CONTRACT_VERSION = "operational_health.v0"
DEFAULT_STALE_SNAPSHOT_MINUTES = 60.0
DEFAULT_STALE_RECEIPT_MINUTES = 120.0
DEFAULT_STALE_RECONCILIATION_MINUTES = 240.0
DEFAULT_STALE_EVIDENCE_MINUTES = 24.0 * 60.0
DEFAULT_LIMIT = 100

_OPEN_RECEIPT_STATES = {"submitted", "accepted", "cancel_requested", "partial_fill"}
_BLOCKED_RISK_OUTCOMES = {"hard_block", "missing_data", "stale_data"}
_OPEN_APPROVAL_STATES = {"pending_external_review"}
# States that claim an external approval/waiver decision exists: a NULL
# approval_ref_id here is a genuine, actionable gap. By contrast,
# 'not_requested' (the default) with a NULL ref is normal and must NOT be
# flagged — otherwise the approvals section is permanently in 'attention'.
_CLAIMED_EXTERNAL_APPROVAL_STATES = {"approved_elsewhere", "waived_elsewhere"}
_STALE_SNAPSHOT_STATUSES = {"stale", "missing", "unknown"}
_UNRESOLVED_RECONCILIATION = {"unresolved", "accepted_caveat"}




def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _age_minutes(as_of: datetime, value: Any) -> float | None:
    parsed = _dt(value)
    if parsed is None:
        return None
    return round((as_of - parsed).total_seconds() / 60.0, 6)


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _has_table(conn, table):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        return default


def _status(rows: list[dict[str, Any]]) -> str:
    codes = {code for row in rows for code in row["codes"]}
    if any(code.startswith("MISSING_") or code.startswith("FAILED_") or code.startswith("BLOCKED_") or code.startswith("UNREVIEWED_") or code.startswith("UNRESOLVED_") for code in codes):
        return "attention"
    if any(code.startswith("STALE_") or code.startswith("SPARSE_") or code.startswith("PENDING_") for code in codes):
        return "caveated"
    return "healthy"


def _section(family: str, rows: list[dict[str, Any]], *, missing_code: str | None = None) -> dict[str, Any]:
    codes = sorted({code for row in rows for code in row["codes"]})
    if not rows and missing_code:
        codes = [missing_code]
    contributing: dict[str, list[str]] = {}
    for row in rows:
        for kind, ids in row.get("contributing_ids", {}).items():
            contributing.setdefault(kind, [])
            contributing[kind].extend(str(i) for i in ids if i is not None)
    contributing = {k: sorted(set(v)) for k, v in contributing.items()}
    return {
        "family": family,
        "status": "attention" if not rows and missing_code else _status(rows),
        "count": len(rows),
        "health_codes": codes,
        "contributing_record_ids": contributing,
        "items": rows,
    }


def _where(cols: set[str], rf: ReportFilter, alias: str = "") -> tuple[str, list[Any]]:
    prefix = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: list[Any] = []
    for field, values in (("run_id", rf.actors.run_id), ("strategy_id", [rf.strategy.strategy_id] if rf.strategy.strategy_id else []), ("instrument_id", rf.instrument.instrument_id)):
        if values and field in cols:
            clauses.append(f"{prefix}{field} IN ({','.join('?' for _ in values)})")
            params.extend(values)
    if rf.time_window.created_at_gte:
        for col in ("created_at", "recorded_at", "imported_at", "as_of"):
            if col in cols:
                clauses.append(f"{prefix}{col} >= ?")
                params.append(rf.time_window.created_at_gte)
                break
    if rf.time_window.created_at_lt:
        for col in ("created_at", "recorded_at", "imported_at", "as_of"):
            if col in cols:
                clauses.append(f"{prefix}{col} < ?")
                params.append(rf.time_window.created_at_lt)
                break
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _build(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    limit = min(max(int(args.get("limit", DEFAULT_LIMIT)), 1), 500)
    as_of_dt = _dt(args.get("as_of")) or _dt(now_iso()) or datetime.now(UTC)
    as_of = _iso(as_of_dt)
    thresholds = {
        "stale_snapshot_minutes": float(args.get("stale_snapshot_minutes", DEFAULT_STALE_SNAPSHOT_MINUTES)),
        "stale_receipt_minutes": float(args.get("stale_receipt_minutes", DEFAULT_STALE_RECEIPT_MINUTES)),
        "stale_reconciliation_minutes": float(args.get("stale_reconciliation_minutes", DEFAULT_STALE_RECONCILIATION_MINUTES)),
        "stale_evidence_minutes": float(args.get("stale_evidence_minutes", DEFAULT_STALE_EVIDENCE_MINUTES)),
    }
    rf = ReportFilter.model_validate(args.get("filter") or {})
    filter_view = process_filter(rf, report=REPORT_NAME)

    sections: dict[str, Any] = {}
    missing_tables: list[str] = []

    # imported account snapshots
    if not _has_table(conn, "account_snapshots"):
        missing_tables.append("account_snapshots")
        sections["snapshots"] = _section("snapshots", [], missing_code="MISSING_SNAPSHOT_TABLE")
    else:
        rows = []
        where, params = _where(_cols(conn, "account_snapshots"), rf)
        for r in conn.execute(f"SELECT id, as_of, captured_at, staleness_status, source_system, source_run_id, caveats_json FROM account_snapshots{where} ORDER BY as_of DESC, imported_at DESC, id DESC LIMIT ?", (*params, limit)).fetchall():
            age = _age_minutes(as_of_dt, r[1] or r[2])
            codes = []
            if r[3] in _STALE_SNAPSHOT_STATUSES:
                codes.append(f"SNAPSHOT_STATUS_{str(r[3]).upper()}")
            if age is None:
                codes.append("MISSING_SNAPSHOT_TIMESTAMP")
            elif age > thresholds["stale_snapshot_minutes"]:
                codes.append("STALE_SNAPSHOT_INPUT")
            rows.append({"id": r[0], "status": "caveated" if codes else "healthy", "codes": codes, "age_minutes": age, "source_system": r[4], "source_run_id": r[5], "contributing_ids": {"account_snapshots": [r[0]]}})
        sections["snapshots"] = _section("snapshots", rows, missing_code="MISSING_SNAPSHOT_INPUTS")

    # reconciliations
    if not _has_table(conn, "reconciliation_records"):
        missing_tables.append("reconciliation_records")
        sections["reconciliations"] = _section("reconciliations", [], missing_code="MISSING_RECONCILIATION_TABLE")
    else:
        rows = []
        where, params = _where(_cols(conn, "reconciliation_records"), rf)
        for r in conn.execute(f"SELECT id, as_of, diff_severity, mismatch_codes_json, resolution_status, contributing_ids_json, imported_at, recorded_at FROM reconciliation_records{where} ORDER BY as_of DESC, id DESC LIMIT ?", (*params, limit)).fetchall():
            age = _age_minutes(as_of_dt, r[1])
            mismatch = _loads(r[3], [])
            codes = []
            if r[4] in _UNRESOLVED_RECONCILIATION and mismatch:
                codes.append("UNRESOLVED_RECONCILIATION_MISMATCH")
            if age is None or age > thresholds["stale_reconciliation_minutes"]:
                codes.append("STALE_RECONCILIATION_INPUT")
            rows.append({"id": r[0], "status": "attention" if codes else "healthy", "codes": codes, "mismatch_codes": mismatch, "diff_severity": r[2], "resolution_status": r[4], "age_minutes": age, "contributing_ids": {"reconciliation_records": [r[0]], **(_loads(r[5], {}) or {})}})
        sections["reconciliations"] = _section("reconciliations", rows, missing_code="MISSING_RECONCILIATION_INPUTS")

    # receipts
    if not _has_table(conn, "external_execution_receipts"):
        missing_tables.append("external_execution_receipts")
        sections["receipts"] = _section("receipts", [], missing_code="MISSING_RECEIPT_TABLE")
    else:
        rows = []
        where, params = _where(_cols(conn, "external_execution_receipts"), rf)
        for r in conn.execute(f"SELECT id, lifecycle_state, external_event_type, pretrade_intent_id, approval_ref_id, market_id, instrument_id, source_system, source_run_id, as_of, imported_at, caveats_json FROM external_execution_receipts{where} ORDER BY as_of DESC, id DESC LIMIT ?", (*params, limit)).fetchall():
            age = _age_minutes(as_of_dt, r[9])
            codes = []
            if r[1] in _OPEN_RECEIPT_STATES and (age is None or age > thresholds["stale_receipt_minutes"]):
                codes.append("STALE_OPEN_RECEIPT_INPUT")
            if r[1] in {"rejected", "failed", "mismatch", "orphan"}:
                codes.append(f"RECEIPT_STATE_{str(r[1]).upper()}")
            ids = {"external_execution_receipts": [r[0]]}
            if r[3]:
                ids["pretrade_intents"] = [r[3]]
            if r[4]:
                ids["approval_waiver_records"] = [r[4]]
            rows.append({"id": r[0], "status": "attention" if codes else "healthy", "codes": codes, "lifecycle_state": r[1], "external_event_type": r[2], "age_minutes": age, "source_system": r[7], "source_run_id": r[8], "contributing_ids": ids})
        sections["receipts"] = _section("receipts", rows, missing_code="MISSING_RECEIPT_INPUTS")

    # pending approvals from intents and approval ledger
    rows = []
    if _has_table(conn, "pretrade_intents"):
        where, params = _where(_cols(conn, "pretrade_intents"), rf)
        for r in conn.execute(f"SELECT id, approval_state, risk_check_receipt_id, approval_ref_id, market_id, instrument_id, as_of FROM pretrade_intents{where} ORDER BY as_of DESC, id DESC LIMIT ?", (*params, limit)).fetchall():
            codes = []
            if r[1] in _OPEN_APPROVAL_STATES or (r[1] in _CLAIMED_EXTERNAL_APPROVAL_STATES and not r[3]):
                codes.append("PENDING_OR_MISSING_APPROVAL")
            if codes:
                rows.append({"id": r[0], "status": "caveated", "codes": codes, "approval_state": r[1], "contributing_ids": {"pretrade_intents": [r[0]], "risk_check_receipts": [r[2]] if r[2] else []}})
    else:
        missing_tables.append("pretrade_intents")
    sections["approvals"] = _section("approvals", rows, missing_code="MISSING_APPROVAL_INPUTS")

    # risk checks
    if not _has_table(conn, "risk_check_receipts"):
        missing_tables.append("risk_check_receipts")
        sections["risk_checks"] = _section("risk_checks", [], missing_code="MISSING_RISK_CHECK_TABLE")
    else:
        rows = []
        where, params = _where(_cols(conn, "risk_check_receipts"), rf)
        for r in conn.execute(f"SELECT id, status, outcome, market_id, instrument_id, strategy_id, snapshot_id, as_of, created_at FROM risk_check_receipts{where} ORDER BY as_of DESC, id DESC LIMIT ?", (*params, limit)).fetchall():
            codes = []
            if r[2] in _BLOCKED_RISK_OUTCOMES or r[1] in {"fail", "missing_data"}:
                codes.append("BLOCKED_RISK_CHECK_INPUT")
            rows.append({"id": r[0], "status": "attention" if codes else "healthy", "codes": codes, "risk_status": r[1], "outcome": r[2], "contributing_ids": {"risk_check_receipts": [r[0]], "snapshots": [r[6]] if r[6] else []}})
        sections["risk_checks"] = _section("risk_checks", rows, missing_code="MISSING_RISK_CHECK_INPUTS")

    # sources/evidence: local source rows
    evidence_rows = []
    if _has_table(conn, "sources"):
        cols = _cols(conn, "sources")
        time_col = "freshness_at" if "freshness_at" in cols else "created_at"
        for r in conn.execute(f"SELECT id, {time_col} FROM sources ORDER BY {time_col} DESC, id DESC LIMIT ?", (limit,)).fetchall():
            age = _age_minutes(as_of_dt, r[1])
            codes = []
            if age is None or age > thresholds["stale_evidence_minutes"]:
                codes.append("STALE_SOURCE_EVIDENCE")
            evidence_rows.append({"id": r[0], "status": "caveated" if codes else "healthy", "codes": codes, "age_minutes": age, "contributing_ids": {"sources": [r[0]]}})
    else:
        missing_tables.append("sources")
    sections["sources_evidence"] = _section("sources_evidence", evidence_rows, missing_code="MISSING_SOURCE_EVIDENCE_INPUTS")

    # work queue obligations: due review/watch/hold decisions
    queue_rows = []
    if _has_table(conn, "decisions"):
        cols = _cols(conn, "decisions")
        if "review_by" in cols:
            where, params = _where(cols, rf)
            joiner = " AND " if where else " WHERE "
            for r in conn.execute(f"SELECT id, type, review_by, strategy_id, instrument_id FROM decisions{where}{joiner}type IN ('watch','hold','review') AND review_by IS NOT NULL AND review_by <= ? ORDER BY review_by, id LIMIT ?", (*params, as_of, limit)).fetchall():
                queue_rows.append({"id": r[0], "status": "attention", "codes": ["WORK_QUEUE_OBLIGATION_DUE"], "decision_type": r[1], "review_by": r[2], "contributing_ids": {"decisions": [r[0]]}})
    else:
        missing_tables.append("decisions")
    sections["work_queue_obligations"] = _section("work_queue_obligations", queue_rows, missing_code="MISSING_WORK_QUEUE_INPUTS")

    summary_counts = {name: {"status": sec["status"], "count": sec["count"], "health_codes": sec["health_codes"]} for name, sec in sections.items()}
    all_codes = sorted({code for sec in sections.values() for code in sec["health_codes"]})
    groups = [{"key": name, "label": name.replace("_", " "), "metrics": {"status": sec["status"], "count": sec["count"]}, "filter": filter_view, "record_ids": sec["contributing_record_ids"], "sections": {name: sec}, "caveats": sec["health_codes"], "sample_size": sec["count"], "truncated": sec["count"] >= limit} for name, sec in sections.items()]
    return {
        "kind": REPORT_NAME,
        "contract_version": CONTRACT_VERSION,
        "local_evidence_only": True,
        "non_executing": True,
        "credential_blind": True,
        "advice_free": True,
        **standard_report_result(
            summary={"as_of": as_of, "thresholds": thresholds, "filter": filter_view, "family_counts": summary_counts, "health_codes": all_codes, "missing_tables": sorted(set(missing_tables)), "sample_size": sum(sec["count"] for sec in sections.values())},
            groups=groups,
            extra={"families": sections},
        ),
    }


def report_operational_health(args: dict[str, Any]) -> dict[str, Any]:
    """Return a local-only read-only health report over imported intelligence inputs."""
    with db_for_args(args) as db:
        with read_snapshot(db.connection):
            return _build(db.connection, args)
