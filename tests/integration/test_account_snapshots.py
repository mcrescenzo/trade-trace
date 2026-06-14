from __future__ import annotations

import sqlite3

import pytest

from trade_trace.core import dispatch
from trade_trace.storage.paths import db_path


def _call(tool: str, args: dict, *, actor_id: str = "agent:account-import"):
    return dispatch(tool, args, actor_id=actor_id)


def _init(home) -> None:
    init = _call("journal.init", {"home": str(home)}, actor_id="agent:init")
    assert init.ok, init


def _snapshot_args(home, *, semantic_key: str = "account-snapshot-1", staleness: str = "fresh") -> dict:
    return {
        "home": str(home),
        "semantic_key": semantic_key,
        "schema_version": "account_snapshot.v1",
        "source_system": "sanitized-account-export",
        "source_run_id": "run-1",
        "source_precedence": 10,
        "confidence_label": "high",
        "staleness_status": staleness,
        "environment_label": "paper",
        "account_label": "acct-redacted",
        "venue_label": "venue-redacted",
        "captured_at": "2026-05-28T00:02:00.000Z",
        "effective_at": "2026-05-28T00:02:00.000Z",
        "retrieved_at": "2026-05-28T00:03:00.000Z",
        "as_of": "2026-05-28T00:02:00.000Z",
        "redacted_artifact_ref": "sha256://redacted/account-snapshot-1",
        "balances": [{"asset": "USD", "total": "100", "available": "75"}],
        "collateral": {"available": "75", "committed": "25", "currency": "USD"},
        "open_orders": [{"ref": "order-redacted-1", "quantity": "10"}],
        "positions": [{"instrument_ref": "instrument-redacted-1", "quantity": "15"}],
        "fills_trades": [{"ref": "fill-redacted-1", "quantity": "5"}],
        "unsettled_claims": [{"ref": "claim-redacted-1", "amount": "2"}],
        "public_allowance_facts": [{"asset": "USDC", "allowance": "0"}],
        "caveats": [{"code": "caller_supplied_sanitized_snapshot"}],
        "provenance_json": {"importer": "unit-test", "private_payload_ingested": False},
        "idempotency_key": semantic_key,
    }


def test_account_snapshot_import_idempotent_list_get_and_report(tmp_path):
    home = tmp_path / "home"
    _init(home)
    first = _call("account_snapshot.import", _snapshot_args(home))
    assert first.ok, first
    assert first.data["record_kind"] == "sanitized_imported_account_snapshot"
    assert first.data["local_evidence_only"] is True
    assert first.data["non_executing"] is True
    assert first.data["credential_blind"] is True
    assert first.data["artifact_hash"]
    assert first.data["balances"][0]["available"] == "75"
    assert first.data["collateral"]["committed"] == "25"
    assert first.data["open_orders"] and first.data["positions"] and first.data["fills_trades"]
    assert first.data["unsettled_claims"] and first.data["public_allowance_facts"]

    replay = _call("account_snapshot.import", _snapshot_args(home))
    assert replay.ok, replay
    assert replay.data["id"] == first.data["id"]
    assert replay.meta.idempotent_replay is True

    got = _call("account_snapshot.get", {"home": str(home), "id": first.data["id"]})
    assert got.ok, got
    assert got.data["id"] == first.data["id"]

    listed = _call("account_snapshot.list", {"home": str(home), "account_label": "acct-redacted"})
    assert listed.ok, listed
    assert listed.data["count"] == 1

    stale = _call("account_snapshot.import", _snapshot_args(home, semantic_key="stale-snapshot", staleness="stale"))
    assert stale.ok, stale
    report = _call("account_snapshot.report", {"home": str(home)})
    assert report.ok, report
    assert report.data["count"] == 1
    assert "account_snapshot_stale" in report.data["caveat_codes"]


def test_account_snapshot_table_is_append_only(tmp_path):
    home = tmp_path / "home"
    _init(home)
    imported = _call("account_snapshot.import", _snapshot_args(home, semantic_key="append-only-snapshot"))
    assert imported.ok, imported

    conn = sqlite3.connect(db_path(home))
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only invariant: UPDATE"):
            conn.execute("UPDATE account_snapshots SET confidence_label = 'low' WHERE id = ?", (imported.data["id"],))
        conn.rollback()
        with pytest.raises(sqlite3.DatabaseError, match="append-only invariant: DELETE"):
            conn.execute("DELETE FROM account_snapshots WHERE id = ?", (imported.data["id"],))
        conn.rollback()
        row = conn.execute("SELECT confidence_label FROM account_snapshots WHERE id = ?", (imported.data["id"],)).fetchone()
    finally:
        conn.close()
    assert row == ("high",)


def test_account_snapshot_rejects_secrets_before_persistence(tmp_path):
    home = tmp_path / "home"
    _init(home)
    bad = _snapshot_args(home, semantic_key="bad-secret")
    bad["balances"] = [{"private_key": "not persisted"}]
    env = _call("account_snapshot.import", bad)
    assert not env.ok
    assert env.error is not None
    assert env.error.code == "VALIDATION_ERROR"

    conn = sqlite3.connect(db_path(home))
    try:
        rows = conn.execute("SELECT COUNT(*) FROM account_snapshots WHERE semantic_key = 'bad-secret'").fetchone()[0]
    finally:
        conn.close()
    assert rows == 0


@pytest.mark.parametrize(
    "field",
    [
        "semantic_key", "source_system", "source_run_id", "environment_label",
        "account_label", "venue_label", "redacted_artifact_ref", "quarantine_reason",
    ],
)
def test_account_snapshot_rejects_secret_shaped_persisted_text_fields(tmp_path, field):
    home = tmp_path / "home"
    _init(home)
    secret = "s" + "k" + "-" + "a" * 24
    semantic_key = f"secret-text-{field}"
    bad = _snapshot_args(home, semantic_key=semantic_key)
    bad[field] = f"prefix-{secret}"
    if field == "semantic_key":
        semantic_key = bad[field]
    env = _call("account_snapshot.import", bad)
    assert not env.ok
    assert env.error is not None
    assert env.error.code == "VALIDATION_ERROR"
    assert env.error.details["field"] == field

    conn = sqlite3.connect(db_path(home))
    try:
        rows = conn.execute("SELECT COUNT(*) FROM account_snapshots WHERE semantic_key = ?", (semantic_key,)).fetchone()[0]
    finally:
        conn.close()
    assert rows == 0


def test_account_snapshot_semantic_conflict_and_malformed_quarantine(tmp_path):
    home = tmp_path / "home"
    _init(home)
    ok = _call("account_snapshot.import", _snapshot_args(home, semantic_key="conflict-snapshot"))
    assert ok.ok, ok
    changed = _snapshot_args(home, semantic_key="conflict-snapshot")
    changed["balances"] = [{"asset": "USD", "total": "101"}]
    conflict = _call("account_snapshot.import", changed)
    assert not conflict.ok
    assert conflict.error is not None
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"

    malformed = _snapshot_args(home, semantic_key="malformed-snapshot")
    malformed["positions"] = "not-json"
    env = _call("account_snapshot.import", malformed)
    assert not env.ok
    assert env.error is not None
    assert env.error.details["code"] == "malformed_json_quarantined"

    impossible = _call("account_snapshot.import", _snapshot_args(home, semantic_key="bad-staleness", staleness="timewarp"))
    assert not impossible.ok
    assert impossible.error is not None
    assert impossible.error.details["code"] == "impossible_payload_quarantined"


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_code"),
    [
        ("balances", [{"asset": "USD", "total": "-100", "available": "200"}], "impossible_payload_quarantined"),
        ("balances", [{"asset": "USD", "total": "100", "available": "200"}], "conflicting_payload_quarantined"),
        ("collateral", {"available": "-1", "committed": "2", "currency": "USD"}, "impossible_payload_quarantined"),
        ("collateral", {"available": "1", "committed": "-2", "currency": "USD"}, "impossible_payload_quarantined"),
        ("open_orders", [{"ref": "order-redacted-1", "quantity": "-10"}], "impossible_payload_quarantined"),
        ("positions", [{"instrument_ref": "instrument-redacted-1", "quantity": "-15"}], "impossible_payload_quarantined"),
        ("fills_trades", [{"ref": "fill-redacted-1", "quantity": "-5"}], "impossible_payload_quarantined"),
        ("unsettled_claims", [{"ref": "claim-redacted-1", "amount": "-2"}], "impossible_payload_quarantined"),
        ("public_allowance_facts", [{"asset": "USDC", "allowance": "-1"}], "impossible_payload_quarantined"),
    ],
)
def test_account_snapshot_rejects_impossible_account_state_before_persistence(tmp_path, field, bad_value, expected_code):
    home = tmp_path / "home"
    _init(home)
    semantic_key = f"bad-state-{field}-{expected_code}"
    bad = _snapshot_args(home, semantic_key=semantic_key)
    bad[field] = bad_value

    env = _call("account_snapshot.import", bad)

    assert not env.ok
    assert env.error is not None
    assert env.error.code == "VALIDATION_ERROR"
    assert env.error.details["code"] == expected_code

    conn = sqlite3.connect(db_path(home))
    try:
        rows = conn.execute("SELECT COUNT(*) FROM account_snapshots WHERE semantic_key = ?", (semantic_key,)).fetchone()[0]
    finally:
        conn.close()
    assert rows == 0


def test_account_snapshot_is_imported_evidence_with_provenance_never_tt_fetched(tmp_path):
    # Substrate spec §2.2 / §5.2: imported account truth (balances, positions,
    # open orders) is labelled as sanitized imported EVIDENCE with provenance and
    # source-precedence/confidence/staleness semantics — never a fact Trade Trace
    # fetched. Pin the labelling contract so an importer that started to look like
    # a TT-native fetch (or dropped the provenance) is caught.
    home = tmp_path / "home"
    _init(home)
    env = _call("account_snapshot.import", _snapshot_args(home, semantic_key="provenance-snapshot"))
    assert env.ok, env
    data = env.data
    assert data["record_kind"] == "sanitized_imported_account_snapshot"
    assert data["local_evidence_only"] is True
    assert data["non_executing"] is True
    assert data["credential_blind"] is True
    # Provenance + precedence/confidence/staleness travel with the imported truth.
    assert data["provenance"]["importer"] == "unit-test"
    assert data["source_precedence"] == 10
    assert data["confidence_label"] == "high"
    assert data["staleness_status"] == "fresh"
    # The balances/positions/open-orders families round-trip as imported claims.
    assert data["balances"] == [{"asset": "USD", "total": "100", "available": "75"}]
    assert data["positions"] == [{"instrument_ref": "instrument-redacted-1", "quantity": "15"}]
    assert data["open_orders"] == [{"ref": "order-redacted-1", "quantity": "10"}]


def test_account_snapshot_cluster_is_not_frozen(tmp_path):
    """Freeze-state regression (bead trade-trace-qfn8).

    account_snapshot.import/get/list/report were unfrozen into the public Phase-2
    catalog. Pin that non-experimental state so a future accidental re-freeze
    (re-adding any of these names to EXPERIMENTAL_RECONCILIATION) is caught here,
    mirroring test_external_receipt_cluster_is_not_frozen.
    """

    del tmp_path  # registry-shape assertion; no DB needed
    from trade_trace.core import (
        EXPERIMENTAL_FROZEN_TOOLS,
        EXPERIMENTAL_RECONCILIATION,
        build_registry,
    )

    reg = build_registry()
    public = set(reg.public_names())
    for name in ("account_snapshot.import", "account_snapshot.get", "account_snapshot.list", "account_snapshot.report"):
        entry = reg.get(name)
        assert entry is not None, f"{name} should be registered"
        assert entry.metadata()["catalog_visibility"] == "public", (
            f"{name} regressed off the public catalog; the account-snapshot import "
            "cluster was unfrozen in trade-trace-qfn8"
        )
        assert name in public, f"{name} must appear in the default public catalog"
        assert name not in EXPERIMENTAL_RECONCILIATION, (
            f"{name} was re-added to EXPERIMENTAL_RECONCILIATION"
        )
        assert name not in EXPERIMENTAL_FROZEN_TOOLS, (
            f"{name} re-entered the frozen-tools union"
        )
