from __future__ import annotations

import sqlite3

import pytest

from trade_trace.core import dispatch
from trade_trace.storage.paths import db_path


def _call(tool: str, args: dict, *, actor_id: str = "agent:reconciliation"):
    return dispatch(tool, args, actor_id=actor_id)


def _seed(home):
    assert _call("journal.init", {"home": str(home)}, actor_id="agent:init").ok
    conn = sqlite3.connect(db_path(home))
    try:
        conn.execute("INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) VALUES ('v_1', 'Venue', 'prediction_market', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.execute("INSERT INTO instruments(id, venue_id, external_id, symbol, title, asset_class, metadata_json, created_at, actor_id) VALUES ('i_1', 'v_1', 'ext-i', 'SYM', 'Instrument', 'prediction_market', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.execute("INSERT INTO markets(id, source, external_id, title, question, state, mechanism, bound_via, venue_metadata_json, metadata_json, created_at, actor_id) VALUES ('m_1', 'manual', 'ext-m', 'Market', 'Market?', 'open', 'clob', 'manual', '{}', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.execute("INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, avg_entry_price, updated_at) VALUES ('pos_1', 'i_1', 'actual', 'yes', 'open', '2026-05-28T00:00:00.000Z', 0.42, '2026-05-28T00:00:00.000Z')")
        conn.commit()
    finally:
        conn.close()
    intent = _call("pretrade_intent.record", {"home": str(home), "semantic_key": "intent-recon", "market_id": "m_1", "instrument_id": "i_1", "proposed_shape": {"side": "yes", "limit_price": "0.42", "quantity": "10"}, "risk_budget": {"max_loss": "4.20"}, "approval_state": "approved_elsewhere", "as_of": "2026-05-28T00:00:00.000Z", "idempotency_key": "intent-recon"})
    assert intent.ok, intent
    return intent.data["id"]


def _counts(home):
    conn = sqlite3.connect(db_path(home))
    try:
        return {
            "records": conn.execute("SELECT COUNT(*) FROM reconciliation_records").fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM events WHERE event_type = 'reconciliation.recorded'").fetchone()[0],
        }
    finally:
        conn.close()


def test_reconciliation_record_and_report_mismatch_codes(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed(home)
    snap = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-recon", "source_system": "external-reconciler", "source_precedence": 1, "staleness_status": "stale", "captured_at": "2026-05-28T00:01:00.000Z", "as_of": "2026-05-28T00:01:00.000Z", "positions": [], "balances": [{"asset": "USD", "total": "100"}], "idempotency_key": "snapshot-recon"})
    assert snap.ok, snap
    orphan = _call("external_receipt.import", {"home": str(home), "semantic_key": "orphan-fill-recon", "lifecycle_state": "filled", "external_event_type": "fill", "source_system": "external-reconciler", "as_of": "2026-05-28T00:02:00.000Z", "external_fill_ref": "fill-dup", "sanitized_facts": {"filled_quantity": "1"}, "idempotency_key": "orphan-fill-recon"})
    assert orphan.ok, orphan
    dup = _call("external_receipt.import", {"home": str(home), "semantic_key": "dup-fill-recon", "lifecycle_state": "partial_fill", "external_event_type": "fill", "source_system": "external-reconciler", "as_of": "2026-05-28T00:02:00.000Z", "pretrade_intent_id": intent_id, "external_fill_ref": "fill-dup", "sanitized_facts": {"requested_quantity": "10", "filled_quantity": "3", "remaining_quantity": "9"}, "idempotency_key": "dup-fill-recon"})
    assert dup.ok, dup
    rejected = _call("external_receipt.import", {"home": str(home), "semantic_key": "rejected-approved-recon", "lifecycle_state": "rejected", "external_event_type": "order", "source_system": "external-reconciler", "as_of": "2026-05-28T00:02:00.000Z", "pretrade_intent_id": intent_id, "sanitized_facts": {}, "idempotency_key": "rejected-approved-recon"})
    assert rejected.ok, rejected

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-1", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-1"})
    assert rec.ok, rec
    codes = set(rec.data["mismatch_codes"])
    assert {"STALE_SNAPSHOT", "POSITION_MISMATCH", "ORPHAN_EXTERNAL_FILL", "DUPLICATE_FILL", "REJECTED_APPROVED_INTENT", "PARTIAL_FILL_REMAINING_MISMATCH", "PRICE_MISMATCH", "FEE_MISMATCH", "EVENT_EXPOSURE_UNAVAILABLE"} <= codes
    assert rec.data["source_precedence"][0] == "imported_account_snapshots"
    assert rec.data["expected_state"]["open_position_count"] == 1
    assert rec.data["observed_imported_state"]["account_snapshot"]["id"] == snap.data["id"]
    assert rec.data["contributing_ids"]["external_receipts"]
    assert rec.data["resolution_status"] == "unresolved"
    assert rec.data["non_executing"] is True

    report = _call("report.reconciliation_mismatches", {"home": str(home)})
    assert report.ok, report
    assert report.data["summary"]["count"] == 1
    assert "DUPLICATE_FILL" in report.data["summary"]["mismatch_codes"]
    assert report.data["non_executing"] is True


def test_reconciliation_rejects_unknown_codes_and_append_only(tmp_path):
    home = tmp_path / "home"
    _seed(home)
    bad = _call("reconciliation.record", {"home": str(home), "semantic_key": "bad-recon", "as_of": "2026-05-28T00:03:00.000Z", "mismatch_codes": ["VAGUE_MISMATCH"], "idempotency_key": "bad-recon"})
    assert not bad.ok
    assert bad.error is not None
    assert bad.error.code == "VALIDATION_ERROR"

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "append-recon", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "append-recon"})
    assert rec.ok, rec
    conn = sqlite3.connect(db_path(home))
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only invariant: UPDATE"):
            conn.execute("UPDATE reconciliation_records SET resolution_status = 'explained' WHERE id = ?", (rec.data["id"],))
        conn.rollback()
        with pytest.raises(sqlite3.DatabaseError, match="append-only invariant: DELETE"):
            conn.execute("DELETE FROM reconciliation_records WHERE id = ?", (rec.data["id"],))
    finally:
        conn.close()


def test_reconciliation_idempotency_replay_identical_material_no_extra_row_or_event(tmp_path):
    home = tmp_path / "home"
    _seed(home)
    args = {"home": str(home), "semantic_key": "replay-recon", "as_of": "2026-05-28T00:03:00.000Z", "mismatch_codes": ["AMBIGUOUS_RESOLUTION"], "idempotency_key": "replay-key"}

    first = _call("reconciliation.record", args)
    assert first.ok, first
    before = _counts(home)
    second = _call("reconciliation.record", args)

    assert second.ok, second
    assert second.data["id"] == first.data["id"]
    assert _counts(home) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"semantic_key": "replay-recon-other"},
        {"as_of": "2026-05-28T00:04:00.000Z", "mismatch_codes": ["EXPOSURE_MISMATCH"]},
    ],
)
def test_reconciliation_idempotency_replay_conflicting_material_no_extra_row_or_event(tmp_path, changes):
    home = tmp_path / "home"
    _seed(home)
    args = {"home": str(home), "semantic_key": "replay-conflict", "as_of": "2026-05-28T00:03:00.000Z", "mismatch_codes": ["AMBIGUOUS_RESOLUTION"], "idempotency_key": "replay-conflict-key"}
    first = _call("reconciliation.record", args)
    assert first.ok, first
    before = _counts(home)

    conflict = _call("reconciliation.record", {**args, **changes})

    assert not conflict.ok
    assert conflict.error is not None
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"
    assert conflict.error.details["code"] == "idempotency_conflict"
    assert conflict.error.details["idempotency_key"] == "replay-conflict-key"
    assert conflict.error.details["existing_id"] == first.data["id"]
    assert _counts(home) == before


def test_reconciliation_semantic_conflict_with_different_idempotency_key_no_extra_row_or_event(tmp_path):
    home = tmp_path / "home"
    _seed(home)
    args = {"home": str(home), "semantic_key": "semantic-conflict", "as_of": "2026-05-28T00:03:00.000Z", "mismatch_codes": ["AMBIGUOUS_RESOLUTION"], "idempotency_key": "semantic-conflict-1"}
    first = _call("reconciliation.record", args)
    assert first.ok, first
    before = _counts(home)

    conflict = _call("reconciliation.record", {**args, "as_of": "2026-05-28T00:04:00.000Z", "idempotency_key": "semantic-conflict-2"})

    assert not conflict.ok
    assert conflict.error is not None
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"
    assert conflict.error.details["code"] == "semantic_conflict"
    assert conflict.error.details["existing_id"] == first.data["id"]
    assert _counts(home) == before


def test_reconciliation_manual_stable_mismatch_codes_are_recorded(tmp_path):
    home = tmp_path / "home"
    _seed(home)
    required_codes = ["MISSING_APPROVAL", "NEGATIVE_RISK_CAVEAT", "EXPOSURE_MISMATCH", "AMBIGUOUS_RESOLUTION", "POLICY_WAIVER_BREACH"]

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "manual-codes", "as_of": "2026-05-28T00:03:00.000Z", "mismatch_codes": required_codes, "idempotency_key": "manual-codes"})

    assert rec.ok, rec
    assert set(required_codes) <= set(rec.data["mismatch_codes"])
