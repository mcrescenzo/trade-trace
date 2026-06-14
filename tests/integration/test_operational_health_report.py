from __future__ import annotations

import sqlite3

from trade_trace.core import dispatch
from trade_trace.storage.paths import db_path


def _call(tool: str, args: dict, *, actor_id: str = "agent:operational-health"):
    return dispatch(tool, args, actor_id=actor_id)


def _init(home):
    res = _call("journal.init", {"home": str(home)}, actor_id="agent:init")
    assert res.ok, res
    return sqlite3.connect(db_path(home))


def test_operational_health_empty_dataset_reports_missing_family_codes(tmp_path):
    home = tmp_path / "home"
    conn = _init(home)
    conn.close()

    report = _call("report.operational_health", {"home": str(home), "as_of": "2026-05-28T02:00:00Z"})
    assert report.ok, report
    data = report.data
    assert data["kind"] == "report.operational_health"
    assert data["local_evidence_only"] is True
    assert data["non_executing"] is True
    assert data["credential_blind"] is True
    assert data["advice_free"] is True
    assert "MISSING_SNAPSHOT_INPUTS" in data["families"]["snapshots"]["health_codes"]
    assert "MISSING_RECEIPT_INPUTS" in data["families"]["receipts"]["health_codes"]
    assert "MISSING_RISK_CHECK_INPUTS" in data["families"]["risk_checks"]["health_codes"]
    assert "MISSING_WORK_QUEUE_INPUTS" in data["families"]["work_queue_obligations"]["health_codes"]


def test_operational_health_flags_stale_blocked_failed_unreviewed_and_unresolved_inputs(tmp_path):
    home = tmp_path / "home"
    conn = _init(home)
    try:
        conn.execute("INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) VALUES ('v1','Venue','prediction_market','{}','2026-05-28T00:00:00Z','agent:test')")
        conn.execute("INSERT INTO instruments(id, venue_id, external_id, symbol, title, asset_class, metadata_json, created_at, actor_id) VALUES ('inst1','v1','ext','SYM','Instrument','prediction_market','{}','2026-05-28T00:00:00Z','agent:test')")
        conn.execute("INSERT INTO markets(id, source, external_id, title, question, state, mechanism, bound_via, venue_metadata_json, metadata_json, created_at, actor_id) VALUES ('m1','manual','m-ext','Market','Q','open','clob','manual','{}','{}','2026-05-28T00:00:00Z','agent:test')")
        conn.execute("INSERT INTO snapshots(id, instrument_id, captured_at, source, price, bid, ask, mid, spread, liquidity_depth_json, metadata_json, created_at, actor_id) VALUES ('snap-market','inst1','2026-05-28T00:00:00Z','manual',0.5,0.49,0.51,0.5,0.02,'{}','{}','2026-05-28T00:00:00Z','agent:test')")
        conn.execute("INSERT INTO risk_policy_versions(id, policy_key, version, policy_hash, limits_json, rules_json, source, provenance_json, effective_from, effective_to, created_at, actor_id) VALUES ('rpv1','p','1','h','{}','[]','manual','{}','2026-05-28T00:00:00Z',NULL,'2026-05-28T00:00:00Z','agent:test')")
        conn.execute("INSERT INTO account_snapshots(id, schema_version, semantic_key, material_hash, source_system, source_run_id, source_precedence, confidence_label, staleness_status, environment_label, account_label, venue_label, captured_at, effective_at, as_of, retrieved_at, imported_at, artifact_hash, redacted_artifact_ref, balances_json, collateral_json, open_orders_json, positions_json, fills_trades_json, unsettled_claims_json, public_allowance_facts_json, caveats_json, provenance_json, quarantine_reason, idempotency_key, actor_id) VALUES ('acct1','account_snapshot.v1','acct-key','mh','importer','run-a',1,'unknown','stale',NULL,NULL,NULL,'2026-05-28T00:00:00Z',NULL,'2026-05-28T00:00:00Z',NULL,'2026-05-28T00:01:00Z','ah',NULL,'[]','{}','[]','[]','[]','[]','[]','[]','{}',NULL,NULL,'agent:test')")
        conn.execute("INSERT INTO risk_check_receipts(id, receipt_hash, policy_version_id, status, outcome, intended_action, proposed_intent_hash, decision_id, market_id, instrument_id, strategy_id, snapshot_id, exposure_input_ids_json, evidence_input_ids_json, input_provenance_json, as_of, created_at, waived_by, waiver_reason, actor_id) VALUES ('risk1','rh','rpv1','fail','hard_block','trade','ph',NULL,'m1','inst1',NULL,'snap-market','[]','[]','{}','2026-05-28T00:05:00Z','2026-05-28T00:05:00Z',NULL,NULL,'agent:test')")
        conn.execute("INSERT INTO pretrade_intents(id, semantic_key, material_hash, market_id, instrument_id, snapshot_id, proposed_shape_json, risk_budget_json, risk_check_receipt_id, approval_state, approval_ref_id, as_of, created_at, idempotency_key, actor_id) VALUES ('intent1','intent-key','mh','m1','inst1','snap-market','{}','{}','risk1','pending_external_review',NULL,'2026-05-28T00:06:00Z','2026-05-28T00:06:00Z',NULL,'agent:test')")
        conn.execute("INSERT INTO external_execution_receipts(id, schema_version, semantic_key, material_hash, lifecycle_state, external_event_type, pretrade_intent_id, approval_ref_id, market_id, instrument_id, external_order_ref, external_fill_ref, external_event_ref, source_system, source_run_id, retrieved_at, as_of, imported_at, artifact_hash, redacted_artifact_ref, sanitized_facts_json, caveats_json, provenance_json, quarantine_reason, idempotency_key, actor_id) VALUES ('rec1','external_execution_receipt.v1','rec-key','mh','accepted','order','intent1',NULL,'m1','inst1','ord1',NULL,'ev1','importer','run-a','2026-05-28T00:10:00Z','2026-05-28T00:10:00Z','2026-05-28T00:11:00Z','ah',NULL,'{}','[]','{}',NULL,NULL,'agent:test')")
        conn.execute("INSERT INTO reconciliation_records(id, schema_version, semantic_key, material_hash, as_of, source, source_precedence_json, expected_state_json, observed_imported_state_json, diff_json, diff_severity, mismatch_codes_json, resolution_status, contributing_ids_json, caveats_json, provenance_json, imported_at, recorded_at, idempotency_key, actor_id) VALUES ('recon1','reconciliation_result.v1','recon-key','mh','2026-05-28T00:20:00Z','manual','[]','{}','{}','{}','warning','[\"POSITION_MISMATCH\"]','unresolved','{\"external_receipts\":[\"rec1\"]}','[]','{}','2026-05-28T00:21:00Z','2026-05-28T00:21:00Z',NULL,'agent:test')")
        conn.execute("INSERT INTO autonomous_run_records(id, schema_version, semantic_key, material_hash, mode, run_status, run_id, session_id, actor_id_recorded, model_id, provider_id, environment_label, policy_version, started_at, ended_at, as_of, config_json, provenance_json, caveats_json, recorded_at, idempotency_key, recorder_actor_id) VALUES ('runrec1','autonomous_run.v1','run-key','mh','dry_run','failed','run-a',NULL,NULL,NULL,NULL,NULL,NULL,'2026-05-28T00:00:00Z','2026-05-28T00:30:00Z','2026-05-28T00:30:00Z','{}','{}','[]','2026-05-28T00:31:00Z',NULL,'agent:test')")
        conn.execute("INSERT INTO autonomous_incident_records(id, schema_version, semantic_key, material_hash, incident_type, severity, resolution_status, run_record_id, run_id, session_id, occurred_at, as_of, summary, imported_fact_only, evidence_state, link_ids_json, evidence_refs_json, caveats_json, provenance_json, recorded_at, idempotency_key, recorder_actor_id) VALUES ('inc1','autonomous_incident.v1','inc-key','mh','missing_evidence','warning','unresolved','runrec1','run-a',NULL,'2026-05-28T00:35:00Z','2026-05-28T00:35:00Z','missing evidence',1,'missing','{}','[]','[]','{}','2026-05-28T00:36:00Z',NULL,'agent:test')")
        conn.commit()
    finally:
        conn.close()

    report = _call("report.operational_health", {"home": str(home), "as_of": "2026-05-28T03:00:00Z", "stale_snapshot_minutes": 30, "stale_receipt_minutes": 60, "stale_reconciliation_minutes": 60})
    assert report.ok, report
    data = report.data
    assert "STALE_SNAPSHOT_INPUT" in data["families"]["snapshots"]["health_codes"]
    assert "STALE_OPEN_RECEIPT_INPUT" in data["families"]["receipts"]["health_codes"]
    assert "PENDING_OR_MISSING_APPROVAL" in data["families"]["approvals"]["health_codes"]
    assert "BLOCKED_RISK_CHECK_INPUT" in data["families"]["risk_checks"]["health_codes"]
    assert "FAILED_RUN_INPUT" in data["families"]["runs_incidents"]["health_codes"]
    assert "UNREVIEWED_INCIDENT_INPUT" in data["families"]["runs_incidents"]["health_codes"]
    assert "UNRESOLVED_RECONCILIATION_MISMATCH" in data["families"]["reconciliations"]["health_codes"]
    assert data["families"]["receipts"]["contributing_record_ids"]["external_execution_receipts"] == ["rec1"]
    assert data["families"]["risk_checks"]["contributing_record_ids"]["risk_check_receipts"] == ["risk1"]


def _seed_market_inst(conn):
    conn.execute("INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) VALUES ('v1','Venue','prediction_market','{}','2026-05-28T00:00:00Z','agent:test')")
    conn.execute("INSERT INTO instruments(id, venue_id, external_id, symbol, title, asset_class, metadata_json, created_at, actor_id) VALUES ('inst1','v1','ext','SYM','Instrument','prediction_market','{}','2026-05-28T00:00:00Z','agent:test')")
    conn.execute("INSERT INTO markets(id, source, external_id, title, question, state, mechanism, bound_via, venue_metadata_json, metadata_json, created_at, actor_id) VALUES ('m1','manual','m-ext','Market','Q','open','clob','manual','{}','{}','2026-05-28T00:00:00Z','agent:test')")


def _insert_intent(conn, intent_id, semantic_key, material_hash, approval_state, approval_ref_id):
    ref_sql = "NULL" if approval_ref_id is None else f"'{approval_ref_id}'"
    conn.execute(
        f"INSERT INTO pretrade_intents(id, semantic_key, material_hash, market_id, instrument_id, proposed_shape_json, risk_budget_json, approval_state, approval_ref_id, as_of, created_at, actor_id) "
        f"VALUES ('{intent_id}','{semantic_key}','{material_hash}','m1','inst1','{{}}','{{}}','{approval_state}',{ref_sql},'2026-05-28T00:06:00Z','2026-05-28T00:06:00Z','agent:test')"
    )


def test_operational_health_not_requested_null_approval_ref_is_clean(tmp_path):
    """Regression (trade-trace-t6db): a normal intent with approval_state='not_requested'
    and NULL approval_ref_id must NOT be flagged, so the approvals section is not
    permanently in 'attention'."""
    home = tmp_path / "home"
    conn = _init(home)
    try:
        _seed_market_inst(conn)
        _insert_intent(conn, "intent-clean", "intent-clean-key", "mh-clean", "not_requested", None)
        conn.commit()
    finally:
        conn.close()

    report = _call("report.operational_health", {"home": str(home), "as_of": "2026-05-28T03:00:00Z"})
    assert report.ok, report
    approvals = report.data["families"]["approvals"]
    # The normal not_requested intent produces no flagged approval rows, so the
    # bug code is absent (the section reports MISSING_APPROVAL_INPUTS only because
    # there are no actionable approval rows — that is a distinct, correct signal).
    assert "PENDING_OR_MISSING_APPROVAL" not in approvals["health_codes"], approvals
    assert approvals["count"] == 0, approvals


def test_operational_health_approved_elsewhere_null_ref_is_flagged(tmp_path):
    """Regression (trade-trace-t6db): an intent claiming approval_state='approved_elsewhere'
    with a NULL approval_ref_id IS a genuine actionable gap and must be flagged — while a
    coexisting normal not_requested/NULL intent must NOT be flagged."""
    home = tmp_path / "home"
    conn = _init(home)
    try:
        _seed_market_inst(conn)
        _insert_intent(conn, "intent-gap", "intent-gap-key", "mh-gap", "approved_elsewhere", None)
        _insert_intent(conn, "intent-normal", "intent-normal-key", "mh-normal", "not_requested", None)
        conn.commit()
    finally:
        conn.close()

    report = _call("report.operational_health", {"home": str(home), "as_of": "2026-05-28T03:00:00Z"})
    assert report.ok, report
    approvals = report.data["families"]["approvals"]
    assert "PENDING_OR_MISSING_APPROVAL" in approvals["health_codes"], approvals
    # Only the approved_elsewhere/NULL gap is flagged; the normal not_requested/NULL
    # intent is absent from the contributing ids.
    assert approvals["contributing_record_ids"]["pretrade_intents"] == ["intent-gap"], approvals
    assert approvals["count"] == 1, approvals


def test_operational_health_approved_elsewhere_with_ref_is_clean(tmp_path):
    """Regression (trade-trace-t6db): approved_elsewhere with a present approval_ref_id is
    a resolved approval and must NOT be flagged."""
    home = tmp_path / "home"
    conn = _init(home)
    try:
        _seed_market_inst(conn)
        _insert_intent(conn, "intent-ok", "intent-ok-key", "mh-ok", "approved_elsewhere", "approval-ref-1")
        conn.commit()
    finally:
        conn.close()

    report = _call("report.operational_health", {"home": str(home), "as_of": "2026-05-28T03:00:00Z"})
    assert report.ok, report
    approvals = report.data["families"]["approvals"]
    assert "PENDING_OR_MISSING_APPROVAL" not in approvals["health_codes"], approvals
    assert approvals["count"] == 0, approvals


def test_operational_health_honors_report_filter_run_id(tmp_path):
    home = tmp_path / "home"
    conn = _init(home)
    try:
        conn.execute("INSERT INTO autonomous_run_records(id, schema_version, semantic_key, material_hash, mode, run_status, run_id, session_id, actor_id_recorded, model_id, provider_id, environment_label, policy_version, started_at, ended_at, as_of, config_json, provenance_json, caveats_json, recorded_at, idempotency_key, recorder_actor_id) VALUES ('runrec-a','autonomous_run.v1','run-a','mh','dry_run','failed','run-a',NULL,NULL,NULL,NULL,NULL,NULL,'2026-05-28T00:00:00Z','2026-05-28T00:30:00Z','2026-05-28T00:30:00Z','{}','{}','[]','2026-05-28T00:31:00Z',NULL,'agent:test')")
        conn.execute("INSERT INTO autonomous_run_records(id, schema_version, semantic_key, material_hash, mode, run_status, run_id, session_id, actor_id_recorded, model_id, provider_id, environment_label, policy_version, started_at, ended_at, as_of, config_json, provenance_json, caveats_json, recorded_at, idempotency_key, recorder_actor_id) VALUES ('runrec-b','autonomous_run.v1','run-b','mh-b','dry_run','failed','run-b',NULL,NULL,NULL,NULL,NULL,NULL,'2026-05-28T00:00:00Z','2026-05-28T00:30:00Z','2026-05-28T00:30:00Z','{}','{}','[]','2026-05-28T00:31:00Z',NULL,'agent:test')")
        conn.commit()
    finally:
        conn.close()

    report = _call("report.operational_health", {"home": str(home), "filter": {"actors": {"run_id": ["run-a"]}}})
    assert report.ok, report
    ids = report.data["families"]["runs_incidents"]["contributing_record_ids"]["autonomous_run_records"]
    assert ids == ["runrec-a"]
