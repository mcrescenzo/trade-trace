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


def test_external_receipt_rejects_credential_shaped_metadata(tmp_path):
    # Credential-shaped keys inside a persisted JSON object (sanitized_facts /
    # provenance) must be rejected at the boundary so no credential lands.
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    bad = _receipt_args(home, intent_id, semantic_key="cred-meta-receipt")
    bad["sanitized_facts"] = {"client_secret": "shhh"}
    env = _call("external_receipt.import", bad)
    assert not env.ok
    assert env.error is not None
    assert env.error.code == "VALIDATION_ERROR"
    assert env.error.details.get("credential_key") == "client_secret"

    conn = sqlite3.connect(db_path(home))
    try:
        rows = conn.execute("SELECT COUNT(*) FROM external_execution_receipts WHERE semantic_key = 'cred-meta-receipt'").fetchone()[0]
    finally:
        conn.close()
    assert rows == 0


def test_external_receipt_quarantines_impossible_payloads(tmp_path):
    # "Impossible" payloads — an unsupported schema_version, an unknown
    # lifecycle_state, and a material_hash that does not match the canonical
    # receipt — are refused before persistence, so no incoherent row lands.
    home = tmp_path / "home"
    intent_id = _seed_refs(home)

    bad_schema = _receipt_args(home, intent_id, semantic_key="bad-schema")
    bad_schema["schema_version"] = "external_execution_receipt.v999"
    env = _call("external_receipt.import", bad_schema)
    assert not env.ok
    assert env.error is not None
    assert env.error.details["code"] == "unsupported_schema_version"

    bad_state = _receipt_args(home, intent_id, semantic_key="bad-state")
    bad_state["lifecycle_state"] = "teleported"
    env = _call("external_receipt.import", bad_state)
    assert not env.ok
    assert env.error is not None
    assert env.error.details["field"] == "lifecycle_state"

    bad_hash = _receipt_args(home, intent_id, semantic_key="bad-hash")
    bad_hash["material_hash"] = "deadbeef" * 8
    env = _call("external_receipt.import", bad_hash)
    assert not env.ok
    assert env.error is not None
    assert env.error.details["field"] == "material_hash"

    conn = sqlite3.connect(db_path(home))
    try:
        rows = conn.execute(
            "SELECT COUNT(*) FROM external_execution_receipts WHERE semantic_key IN ('bad-schema', 'bad-state', 'bad-hash')"
        ).fetchone()[0]
    finally:
        conn.close()
    assert rows == 0


def test_external_receipt_imported_correction_labeled_as_imported_evidence(tmp_path):
    # §9 IMPORTED CORRECTION: a `corrected`/`correction` receipt is ingested as
    # append-only imported evidence with provenance, labelled non-executing /
    # credential-blind, and never as a fact Trade Trace fetched.
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    correction = _receipt_args(home, intent_id, semantic_key="correction-receipt", state="corrected")
    correction["external_event_type"] = "correction"
    correction["provenance_json"] = {"importer": "external-reconciler", "corrects_event_ref": "event-redacted-1", "private_payload_ingested": False}
    env = _call("external_receipt.import", correction)
    assert env.ok, env
    assert env.data["lifecycle_state"] == "corrected"
    assert env.data["external_event_type"] == "correction"
    assert env.data["record_kind"] == "sanitized_imported_external_execution_receipt"
    assert env.data["non_executing"] is True
    assert env.data["credential_blind"] is True
    assert env.data["provenance"]["corrects_event_ref"] == "event-redacted-1"


def test_external_receipt_cluster_is_not_frozen(tmp_path):
    """Freeze-state regression (bead trade-trace-g776).

    external_receipt.import/get/list/report were unfrozen into the public
    Phase-2 catalog. Pin that non-experimental state so a future accidental
    re-freeze (re-adding any of these names to EXPERIMENTAL_RECONCILIATION) is
    caught here, mirroring test_reconciliation_cluster_is_not_frozen.
    """

    del tmp_path  # registry-shape assertion; no DB needed
    from trade_trace.core import (
        EXPERIMENTAL_FROZEN_TOOLS,
        EXPERIMENTAL_RECONCILIATION,
        build_registry,
    )

    reg = build_registry()
    public = set(reg.public_names())
    for name in ("external_receipt.import", "external_receipt.get", "external_receipt.list", "external_receipt.report"):
        entry = reg.get(name)
        assert entry is not None, f"{name} should be registered"
        assert entry.metadata()["catalog_visibility"] == "public", (
            f"{name} regressed off the public catalog; the external execution-receipt "
            "import cluster was unfrozen in trade-trace-g776"
        )
        assert name in public, f"{name} must appear in the default public catalog"
        assert name not in EXPERIMENTAL_RECONCILIATION, (
            f"{name} was re-added to EXPERIMENTAL_RECONCILIATION"
        )
        assert name not in EXPERIMENTAL_FROZEN_TOOLS, (
            f"{name} re-entered the frozen-tools union"
        )
