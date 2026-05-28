from __future__ import annotations

import sqlite3

from trade_trace.core import dispatch
from trade_trace.storage.paths import db_path


def _call(tool: str, args: dict, *, actor_id: str = "agent:execution-quality"):
    return dispatch(tool, args, actor_id=actor_id)


def _seed_refs(home, *, with_snapshot: bool = True, intent_as_of: str = "2026-05-28T00:10:00.000Z") -> str:
    init = _call("journal.init", {"home": str(home)}, actor_id="agent:init")
    assert init.ok, init
    conn = sqlite3.connect(db_path(home))
    try:
        conn.execute("INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) VALUES ('v_1', 'Venue', 'prediction_market', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.execute("INSERT INTO instruments(id, venue_id, external_id, symbol, title, asset_class, metadata_json, created_at, actor_id) VALUES ('i_1', 'v_1', 'ext-i', 'SYM', 'Instrument', 'prediction_market', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.execute("INSERT INTO markets(id, source, external_id, title, question, state, mechanism, bound_via, venue_metadata_json, metadata_json, created_at, actor_id) VALUES ('m_1', 'manual', 'ext-m', 'Market', 'Market?', 'open', 'clob', 'manual', '{}', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        if with_snapshot:
            conn.execute("INSERT INTO snapshots(id, instrument_id, captured_at, source, price, bid, ask, mid, spread, liquidity_depth_json, metadata_json, created_at, actor_id) VALUES ('s_1', 'i_1', '2026-05-28T00:00:00.000Z', 'manual', 0.50, 0.49, 0.51, 0.50, 0.02, '{}', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.commit()
    finally:
        conn.close()
    args = {
        "home": str(home), "semantic_key": "intent-exec-quality", "market_id": "m_1", "instrument_id": "i_1",
        "proposed_shape": {"side": "yes", "limit_price": "0.52", "quantity": "10"},
        "risk_budget": {"max_loss": "5.20"}, "as_of": intent_as_of, "idempotency_key": "intent-exec-quality",
    }
    if with_snapshot:
        args["snapshot_id"] = "s_1"
    intent = _call("pretrade_intent.record", args)
    assert intent.ok, intent
    return intent.data["id"]


def _receipt(
    home,
    intent_id: str | None,
    *,
    key: str,
    state: str,
    event_type: str = "fill",
    facts: dict | None = None,
    as_of: str = "2026-05-28T00:12:00.000Z",
    source_system: str = "external-reconciler",
    source_run_id: str = "run-1",
):
    args = {
        "home": str(home), "semantic_key": key, "schema_version": "external_execution_receipt.v1",
        "lifecycle_state": state, "external_event_type": event_type, "source_system": source_system,
        "source_run_id": source_run_id, "retrieved_at": as_of, "as_of": as_of,
        "market_id": "m_1", "instrument_id": "i_1", "external_order_ref": f"order-{key}", "external_event_ref": f"event-{key}",
        "sanitized_facts": facts or {}, "provenance_json": {"importer": "unit-test", "private_payload_ingested": False}, "idempotency_key": key,
    }
    if intent_id is not None:
        args["pretrade_intent_id"] = intent_id
    imported = _call("external_receipt.import", args)
    assert imported.ok, imported
    return imported.data["id"]


def test_report_execution_quality_missing_snapshot_partial_rejected_and_sparse(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home, with_snapshot=False)
    partial_id = _receipt(home, intent_id, key="partial", state="partial_fill", facts={"filled_quantity": "4", "order_quantity": "10", "fill_price": "0.52"})
    reject_id = _receipt(home, intent_id, key="rejected", state="rejected", event_type="error", facts={"venue_state_label": "rejected"})

    report = _call("report.execution_quality", {"home": str(home), "min_sample": 5})
    assert report.ok, report
    data = report.data
    assert data["local_evidence_only"] is True
    assert data["non_executing"] is True
    assert data["summary"]["receipt_count"] == 2
    assert data["summary"]["partial_fill_count"] == 1
    assert data["summary"]["rejected_count"] == 1
    assert {"MISSING_SNAPSHOT", "SLIPPAGE_UNAVAILABLE", "PARTIAL_FILL", "REJECTED_RECEIPT", "SPARSE_SAMPLE"}.issubset(set(data["summary"]["caveat_codes"]))
    assert data["summary"]["snapshot_staleness_summary"] == {
        "available_count": 0,
        "stale_count": 0,
        "min_minutes": None,
        "max_minutes": None,
        "average_minutes": None,
    }
    assert data["summary"]["receipt_provenance_summary"]["source_systems"] == ["external-reconciler"]
    assert data["summary"]["receipt_provenance_summary"]["source_run_ids"] == ["run-1"]
    assert data["summary"]["receipt_provenance_summary"]["retrieved_at_min"] == "2026-05-28T00:12:00.000Z"
    assert data["summary"]["receipt_provenance_summary"]["retrieved_at_max"] == "2026-05-28T00:12:00.000Z"
    assert data["summary"]["receipt_provenance_summary"]["imported_at_min"] is not None
    assert data["summary"]["receipt_provenance_summary"]["imported_at_max"] is not None
    row_by_id = {row["receipt_id"]: row for row in data["rows"]}
    assert row_by_id[partial_id]["contributing_ids"]["intent_ids"] == [intent_id]
    assert row_by_id[partial_id]["contributing_ids"]["snapshot_ids"] == []
    assert row_by_id[reject_id]["receipt_provenance"]["source_system"] == "external-reconciler"


def test_report_execution_quality_empty_receipts_has_stable_caveat(tmp_path):
    home = tmp_path / "home"
    init = _call("journal.init", {"home": str(home)}, actor_id="agent:init")
    assert init.ok, init

    report = _call("report.execution_quality", {"home": str(home), "min_sample": 5})
    assert report.ok, report
    data = report.data

    assert data["local_evidence_only"] is True
    assert data["non_executing"] is True
    assert data["summary"]["receipt_count"] == 0
    assert data["summary"]["sparse_sample"] is True
    assert data["rows"] == []
    assert data["summary"]["caveat_codes"] == ["MISSING_RECEIPT_INPUTS"]


def test_report_execution_quality_stale_snapshot_cancel_stale_open_and_fill_direction(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home, with_snapshot=True, intent_as_of="2026-05-28T00:30:00.000Z")
    adverse_id = _receipt(home, intent_id, key="adverse", state="filled", facts={"filled_quantity": "10", "order_quantity": "10", "fill_price": "0.53"})
    improved_id = _receipt(
        home,
        intent_id,
        key="improved",
        state="filled",
        facts={"filled_quantity": "10", "order_quantity": "10", "fill_price": "0.48"},
        as_of="2026-05-28T00:13:00.000Z",
        source_system="secondary-reconciler",
        source_run_id="run-2",
    )
    cancel_id = _receipt(home, intent_id, key="cancel-failed", state="failed", event_type="cancel", facts={"cancel_status": "failed"})
    open_id = _receipt(home, intent_id, key="stale-open", state="accepted", event_type="order", facts={"filled_quantity": "0", "order_quantity": "10"}, as_of="2026-05-28T00:05:00.000Z")

    report = _call("report.execution_quality", {"home": str(home), "min_sample": 1, "as_of": "2026-05-28T02:00:00.000Z", "stale_snapshot_minutes": 15, "stale_open_minutes": 30})
    assert report.ok, report
    data = report.data
    rows = {row["receipt_id"]: row for row in data["rows"]}
    assert rows[adverse_id]["snapshot_id"] == "s_1"
    assert "STALE_PRETRADE_SNAPSHOT" in rows[adverse_id]["caveat_codes"]
    assert "ADVERSE_FILL_VS_SNAPSHOT" in rows[adverse_id]["caveat_codes"]
    assert "SPREAD_CROSSED" in rows[adverse_id]["caveat_codes"]
    assert "IMPROVED_FILL_VS_SNAPSHOT" in rows[improved_id]["caveat_codes"]
    assert "CANCEL_FAILURE_IMPORTED_EVIDENCE" in rows[cancel_id]["caveat_codes"]
    assert "STALE_OPEN_RECEIPT_IMPORTED_EVIDENCE" in rows[open_id]["caveat_codes"]
    assert data["summary"]["contributing_ids"]["snapshot_ids"] == ["s_1"]
    assert data["summary"]["snapshot_staleness_summary"] == {
        "available_count": 4,
        "stale_count": 4,
        "min_minutes": 30.0,
        "max_minutes": 30.0,
        "average_minutes": 30.0,
    }
    provenance_summary = data["summary"]["receipt_provenance_summary"]
    assert provenance_summary["source_systems"] == ["external-reconciler", "secondary-reconciler"]
    assert provenance_summary["source_run_ids"] == ["run-1", "run-2"]
    assert provenance_summary["retrieved_at_min"] == "2026-05-28T00:05:00.000Z"
    assert provenance_summary["retrieved_at_max"] == "2026-05-28T00:13:00.000Z"
