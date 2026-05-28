from __future__ import annotations

import sqlite3

import pytest

from trade_trace.core import dispatch
from trade_trace.storage.paths import db_path


def _call(tool: str, args: dict, *, actor_id: str = "agent:external-import"):
    return dispatch(tool, args, actor_id=actor_id)


def _seed_refs(home):
    init = _call("journal.init", {"home": str(home)}, actor_id="agent:init")
    assert init.ok, init
    conn = sqlite3.connect(db_path(home))
    try:
        conn.execute("INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) VALUES ('v_1', 'Venue', 'prediction_market', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.execute("INSERT INTO instruments(id, venue_id, external_id, symbol, title, asset_class, metadata_json, created_at, actor_id) VALUES ('i_1', 'v_1', 'ext-i', 'SYM', 'Instrument', 'prediction_market', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.execute("INSERT INTO markets(id, source, external_id, title, question, state, mechanism, bound_via, venue_metadata_json, metadata_json, created_at, actor_id) VALUES ('m_1', 'manual', 'ext-m', 'Market', 'Market?', 'open', 'clob', 'manual', '{}', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.commit()
    finally:
        conn.close()
    intent = _call("pretrade_intent.record", {
        "home": str(home), "semantic_key": "intent-external-receipt", "market_id": "m_1", "instrument_id": "i_1",
        "proposed_shape": {"side": "yes", "limit_price": "0.42", "quantity": "10"},
        "risk_budget": {"max_loss": "4.20"}, "as_of": "2026-05-28T00:00:00.000Z", "idempotency_key": "intent-external-receipt",
    })
    assert intent.ok, intent
    return intent.data["id"]


def _receipt_args(home, intent_id: str | None = None, *, semantic_key: str = "receipt-1", state: str = "accepted") -> dict:
    args = {
        "home": str(home), "semantic_key": semantic_key, "schema_version": "external_execution_receipt.v1",
        "lifecycle_state": state, "external_event_type": "order", "source_system": "external-reconciler",
        "source_run_id": "run-1", "retrieved_at": "2026-05-28T00:03:00.000Z", "as_of": "2026-05-28T00:02:00.000Z",
        "market_id": "m_1", "instrument_id": "i_1", "external_order_ref": "order-redacted-1", "external_event_ref": "event-redacted-1",
        "redacted_artifact_ref": "sha256://redacted/order-redacted-1", "sanitized_facts": {"venue_state_label": state, "filled_quantity": "0"},
        "provenance_json": {"importer": "unit-test", "private_payload_ingested": False}, "idempotency_key": semantic_key,
    }
    if intent_id is not None:
        args["pretrade_intent_id"] = intent_id
    return args


def test_external_receipt_import_idempotent_list_and_report(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    first = _call("external_receipt.import", _receipt_args(home, intent_id))
    assert first.ok, first
    assert first.data["schema_version"] == "external_execution_receipt.v1"
    assert first.data["record_kind"] == "sanitized_imported_external_execution_receipt"
    assert first.data["non_executing"] is True
    assert first.data["credential_blind"] is True
    assert first.data["artifact_hash"]

    replay = _call("external_receipt.import", _receipt_args(home, intent_id))
    assert replay.ok, replay
    assert replay.data["id"] == first.data["id"]
    assert replay.meta.idempotent_replay is True

    listed = _call("external_receipt.list", {"home": str(home), "pretrade_intent_id": intent_id})
    assert listed.ok, listed
    assert listed.data["count"] == 1

    report = _call("external_receipt.report", {"home": str(home)})
    assert report.ok, report
    assert report.data["count"] == 1
    assert report.data["records"][0]["id"] == first.data["id"]


def test_orphan_and_mismatch_receipts_are_reportable_caveats(tmp_path):
    home = tmp_path / "home"
    _seed_refs(home)
    orphan = _call("external_receipt.import", _receipt_args(home, None, semantic_key="orphan-receipt", state="orphan"))
    assert orphan.ok, orphan
    assert any(c["code"] == "orphan_external_receipt_no_matching_intent" for c in orphan.data["caveats"])
    assert any(c["code"] == "imported_external_orphan" for c in orphan.data["caveats"])

    mismatch = _call("external_receipt.import", _receipt_args(home, None, semantic_key="mismatch-receipt", state="mismatch"))
    assert mismatch.ok, mismatch
    report = _call("external_receipt.report", {"home": str(home), "states": ["orphan", "mismatch"]})
    assert report.ok, report
    assert report.data["count"] == 2
    assert "orphan_external_receipt_no_matching_intent" in report.data["caveat_codes"]
    assert "imported_external_mismatch" in report.data["caveat_codes"]


def test_external_receipt_table_is_append_only(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    imported = _call("external_receipt.import", _receipt_args(home, intent_id, semantic_key="append-only-receipt"))
    assert imported.ok, imported

    conn = sqlite3.connect(db_path(home))
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only invariant: UPDATE"):
            conn.execute(
                "UPDATE external_execution_receipts SET lifecycle_state = 'filled' WHERE id = ?",
                (imported.data["id"],),
            )
        conn.rollback()
        with pytest.raises(sqlite3.DatabaseError, match="append-only invariant: DELETE"):
            conn.execute("DELETE FROM external_execution_receipts WHERE id = ?", (imported.data["id"],))
        conn.rollback()
        row = conn.execute(
            "SELECT lifecycle_state FROM external_execution_receipts WHERE id = ?",
            (imported.data["id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row == ("accepted",)


def test_external_receipt_accepts_all_lifecycle_states_and_event_types(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    states = [
        "submitted", "accepted", "rejected", "partial_fill", "filled", "cancel_requested",
        "canceled", "expired", "failed", "corrected", "mismatch", "orphan",
    ]
    event_types = ["order", "fill", "cancel", "error", "correction", "status"]

    seen_event_types = set()
    for index, state in enumerate(states):
        event_type = event_types[index % len(event_types)]
        seen_event_types.add(event_type)
        args = _receipt_args(home, intent_id, semantic_key=f"state-event-{index}", state=state)
        args["external_event_type"] = event_type
        imported = _call("external_receipt.import", args)
        assert imported.ok, imported
        assert imported.data["lifecycle_state"] == state
        assert imported.data["external_event_type"] == event_type

    assert seen_event_types == set(event_types)
    listed = _call("external_receipt.list", {"home": str(home), "limit": 50})
    assert listed.ok, listed
    assert listed.data["count"] == len(states)


def test_external_receipt_rejects_secrets_before_persistence(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    bad = _receipt_args(home, intent_id, semantic_key="bad-secret")
    bad["sanitized_facts"] = {"private_key": "not persisted"}
    env = _call("external_receipt.import", bad)
    assert not env.ok
    assert env.error is not None
    assert env.error.code == "VALIDATION_ERROR"

    conn = sqlite3.connect(db_path(home))
    try:
        rows = conn.execute("SELECT COUNT(*) FROM external_execution_receipts WHERE semantic_key = 'bad-secret'").fetchone()[0]
    finally:
        conn.close()
    assert rows == 0


@pytest.mark.parametrize(
    "field",
    [
        "pretrade_intent_id", "approval_ref_id", "market_id", "instrument_id",
        "semantic_key", "source_system", "source_run_id", "external_order_ref",
        "external_fill_ref", "external_event_ref", "redacted_artifact_ref", "quarantine_reason",
    ],
)
def test_external_receipt_rejects_secret_shaped_persisted_text_fields(tmp_path, field):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    secret = "s" + "k" + "-" + "a" * 24
    semantic_key = f"secret-text-{field}"
    bad = _receipt_args(home, intent_id, semantic_key=semantic_key)
    bad[field] = f"prefix-{secret}"
    if field == "semantic_key":
        semantic_key = bad[field]
    env = _call("external_receipt.import", bad)
    assert not env.ok
    assert env.error is not None
    assert env.error.code == "VALIDATION_ERROR"
    assert env.error.details["field"] == field

    conn = sqlite3.connect(db_path(home))
    try:
        rows = conn.execute("SELECT COUNT(*) FROM external_execution_receipts WHERE semantic_key = ?", (semantic_key,)).fetchone()[0]
    finally:
        conn.close()
    assert rows == 0


def test_external_receipt_semantic_conflict_and_malformed_quarantine(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    ok = _call("external_receipt.import", _receipt_args(home, intent_id, semantic_key="conflict-receipt"))
    assert ok.ok, ok
    changed = _receipt_args(home, intent_id, semantic_key="conflict-receipt")
    changed["sanitized_facts"] = {"venue_state_label": "accepted", "filled_quantity": "1"}
    conflict = _call("external_receipt.import", changed)
    assert not conflict.ok
    assert conflict.error is not None
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"

    malformed = _receipt_args(home, intent_id, semantic_key="malformed-receipt")
    malformed["sanitized_facts"] = "not-json"
    env = _call("external_receipt.import", malformed)
    assert not env.ok
    assert env.error is not None
    assert env.error.details["code"] == "malformed_json_quarantined"
