from __future__ import annotations

import sqlite3
from decimal import Decimal

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


def _seed_no_positions(home):
    """Seed venue/instrument/market but no open positions (clean-match base)."""
    assert _call("journal.init", {"home": str(home)}, actor_id="agent:init").ok
    conn = sqlite3.connect(db_path(home))
    try:
        conn.execute("INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) VALUES ('v_1', 'Venue', 'prediction_market', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.execute("INSERT INTO instruments(id, venue_id, external_id, symbol, title, asset_class, metadata_json, created_at, actor_id) VALUES ('i_1', 'v_1', 'ext-i', 'SYM', 'Instrument', 'prediction_market', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.execute("INSERT INTO markets(id, source, external_id, title, question, state, mechanism, bound_via, venue_metadata_json, metadata_json, created_at, actor_id) VALUES ('m_1', 'manual', 'ext-m', 'Market', 'Market?', 'open', 'clob', 'manual', '{}', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.commit()
    finally:
        conn.close()


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


def test_reconciliation_manual_codes_routed_to_manually_flagged_not_derived(tmp_path):
    # Determinism guard (bead trade-trace-opoc): caller-supplied mismatch_codes
    # are recorded on the distinct `manually_flagged` channel and are NEVER
    # unioned into the deterministically derived `mismatch_codes` set, so the
    # derived set stays reproducible from append-only rows alone.
    home = tmp_path / "home"
    _seed(home)
    manual_codes = ["MISSING_APPROVAL", "NEGATIVE_RISK_CAVEAT", "EXPOSURE_MISMATCH", "AMBIGUOUS_RESOLUTION", "POLICY_WAIVER_BREACH"]

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "manual-codes", "as_of": "2026-05-28T00:03:00.000Z", "mismatch_codes": manual_codes, "idempotency_key": "manual-codes"})

    assert rec.ok, rec
    # Caller codes land ONLY on the manually_flagged channel...
    assert set(manual_codes) <= set(rec.data["manually_flagged"])
    # ...and do NOT contaminate the derived set.
    assert set(manual_codes).isdisjoint(set(rec.data["mismatch_codes"]))
    # Sorted, deduplicated, stable.
    assert rec.data["manually_flagged"] == sorted(manual_codes)
    # The report surfaces the manual channel separately from derived codes.
    report = _call("report.reconciliation_mismatches", {"home": str(home)})
    assert report.ok, report
    assert set(manual_codes) <= set(report.data["summary"]["manually_flagged_codes"])
    assert set(manual_codes).isdisjoint(set(report.data["summary"]["mismatch_codes"]))


def test_reconciliation_caller_codes_cannot_change_derived_set_or_severity(tmp_path):
    # The same derived inputs must produce a byte-identical derived set and
    # severity regardless of what manual codes the caller supplies. A caller
    # passing critical-tier manual codes (DUPLICATE_FILL) must not be able to
    # escalate diff_severity, which is derived from the derived set alone.
    home = tmp_path / "home"
    _seed(home)
    plain = _call("reconciliation.record", {"home": str(home), "semantic_key": "derive-plain", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "derive-plain"})
    assert plain.ok, plain
    flagged = _call("reconciliation.record", {"home": str(home), "semantic_key": "derive-flagged", "as_of": "2026-05-28T00:03:00.000Z", "mismatch_codes": ["DUPLICATE_FILL"], "idempotency_key": "derive-flagged"})
    assert flagged.ok, flagged

    assert plain.data["mismatch_codes"] == flagged.data["mismatch_codes"]
    assert plain.data["diff_severity"] == flagged.data["diff_severity"]
    assert "DUPLICATE_FILL" not in plain.data["mismatch_codes"]
    assert "DUPLICATE_FILL" not in flagged.data["mismatch_codes"]
    assert flagged.data["manually_flagged"] == ["DUPLICATE_FILL"]


def test_reconciliation_cluster_is_not_frozen(tmp_path):
    """Freeze-state regression (bead trade-trace-opoc).

    reconciliation.record/get + report.reconciliation_mismatches were unfrozen
    into the public Phase-2 catalog. Pin that non-experimental state so a future
    accidental re-freeze (re-adding any of these names to
    EXPERIMENTAL_RECONCILIATION) is caught here.
    """

    del tmp_path  # registry-shape assertion; no DB needed
    from trade_trace.core import (
        EXPERIMENTAL_FROZEN_TOOLS,
        EXPERIMENTAL_RECONCILIATION,
        build_registry,
    )

    reg = build_registry()
    public = set(reg.public_names())
    for name in ("reconciliation.record", "reconciliation.get", "report.reconciliation_mismatches"):
        entry = reg.get(name)
        assert entry is not None, f"{name} should be registered"
        assert entry.metadata()["catalog_visibility"] == "public", (
            f"{name} regressed off the public catalog; the reconciliation result "
            "cluster was unfrozen in trade-trace-opoc"
        )
        assert name in public, f"{name} must appear in the default public catalog"
        assert name not in EXPERIMENTAL_RECONCILIATION, (
            f"{name} was re-added to EXPERIMENTAL_RECONCILIATION"
        )
        assert name not in EXPERIMENTAL_FROZEN_TOOLS, (
            f"{name} re-entered the frozen-tools union"
        )


def test_partial_fill_float_serialized_remainder_no_false_mismatch(tmp_path):
    # Regression for trade-trace-awbi (hardened by trade-trace-pgtt): the receipt
    # is internally consistent (remaining == requested - filled in real arithmetic),
    # but the operands carry float-serialization noise that the reconciliation read
    # path (_dec -> Decimal(str(value))) preserves.
    #
    # requested=139.8, filled=86.45. The genuinely-correct remaining is the float
    # subtraction 139.8 - 86.45, which CPython evaluates to 53.35000000000001 and
    # str()s as "53.35000000000001" (it does NOT round-trip to a clean "53.35").
    # Meanwhile Decimal("139.8") - Decimal("86.45") == Decimal("53.35") exactly.
    # So the *expected remainder string* preserves trailing precision noise that the
    # *operand subtraction* does not -- i.e. Decimal(str(req)) - Decimal(str(fil))
    # != Decimal(str(remaining)). The OLD exact "requested - filled != remaining"
    # comparison therefore fired a FALSE PARTIAL_FILL_REMAINING_MISMATCH on this
    # consistent receipt; the shipped 1e-6 tolerance comparison must not.
    #
    # (The earlier 10.1/3.3/6.8 triple did NOT discriminate: str(6.8) == "6.8" and
    # Decimal("10.1") - Decimal("3.3") == Decimal("6.8"), so the test passed against
    # both the old and new code and was not a true regression guard.)
    requested = 139.8
    filled = 86.45
    remaining = requested - filled  # 53.35000000000001 -- the consistent, noisy remainder

    # Guard the construction itself: the operands must reproduce the false-positive
    # condition (clean operand-subtraction != noisy expected-remainder string), else
    # this test silently stops discriminating old-vs-new behavior.
    assert str(remaining) != "53.35", "expected remainder must carry float noise"
    assert Decimal(str(requested)) - Decimal(str(filled)) != Decimal(str(remaining)), (
        "operands must reproduce the exact-comparison false positive"
    )
    assert abs((Decimal(str(requested)) - Decimal(str(filled))) - Decimal(str(remaining))) <= Decimal("0.000001"), (
        "mismatch must be float noise within tolerance, not a genuine discrepancy"
    )

    home = tmp_path / "home"
    intent_id = _seed(home)
    receipt = _call("external_receipt.import", {
        "home": str(home), "semantic_key": "partial-float-recon", "lifecycle_state": "partial_fill",
        "external_event_type": "fill", "source_system": "external-reconciler",
        "as_of": "2026-05-28T00:02:00.000Z", "pretrade_intent_id": intent_id,
        "external_fill_ref": "fill-float", "external_order_ref": "order-float",
        "sanitized_facts": {
            "requested_quantity": requested, "filled_quantity": filled, "remaining_quantity": remaining,
            "average_fill_price": 0.42, "fee_amount": 0.01,
        },
        "idempotency_key": "partial-float-recon",
    })
    assert receipt.ok, receipt

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-float", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-float"})
    assert rec.ok, rec
    assert "PARTIAL_FILL_REMAINING_MISMATCH" not in set(rec.data["mismatch_codes"])


def test_partial_fill_genuine_remainder_mismatch_still_fires(tmp_path):
    # Companion to the float-tolerance regression (trade-trace-awbi): a genuine
    # mismatch >= 1e-6 (requested=10, filled=3, remaining=9) must still derive
    # PARTIAL_FILL_REMAINING_MISMATCH after the tolerance change.
    home = tmp_path / "home"
    intent_id = _seed(home)
    receipt = _call("external_receipt.import", {
        "home": str(home), "semantic_key": "partial-genuine-recon", "lifecycle_state": "partial_fill",
        "external_event_type": "fill", "source_system": "external-reconciler",
        "as_of": "2026-05-28T00:02:00.000Z", "pretrade_intent_id": intent_id,
        "external_fill_ref": "fill-genuine", "external_order_ref": "order-genuine",
        "sanitized_facts": {
            "requested_quantity": 10, "filled_quantity": 3, "remaining_quantity": 9,
            "average_fill_price": 0.42, "fee_amount": 0.01,
        },
        "idempotency_key": "partial-genuine-recon",
    })
    assert receipt.ok, receipt

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-genuine", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-genuine"})
    assert rec.ok, rec
    assert "PARTIAL_FILL_REMAINING_MISMATCH" in set(rec.data["mismatch_codes"])


def test_policy_waiver_breach_not_injected_for_permitted_approval_without_violation(tmp_path):
    # Regression for trade-trace-v8td: a plain record_type='approval' that asserts
    # hard_block_policy_permitted=True (but with violation_visible=0, decision='approved')
    # is NOT a policy breach and must not derive POLICY_WAIVER_BREACH.
    home = tmp_path / "home"
    intent_id = _seed(home)
    approval = _call(
        "approval.record",
        {
            "home": str(home), "semantic_key": "approval-permitted", "record_type": "approval", "decision": "approved",
            "pretrade_intent_id": intent_id, "market_id": "m_1", "instrument_id": "i_1",
            "actor_mode": "human", "decision_actor_id": "human:supervisor", "decision_at": "2026-05-28T00:01:00.000Z",
            "hard_block_policy_permitted": True, "idempotency_key": "approval-permitted",
        },
        actor_id="agent:approval",
    )
    assert approval.ok, approval
    assert approval.data["hard_block_policy_permitted"] is True
    assert approval.data["violation_visible"] is False

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-no-breach", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-no-breach"})

    assert rec.ok, rec
    assert "POLICY_WAIVER_BREACH" not in set(rec.data["mismatch_codes"])


# --- architecture-spec §9 deterministic acceptance gates -------------------
# autonomous-trader-substrate.md §9: "reconciliation match, mismatch, ambiguous
# resolution, stale source precedence, and local projection vs imported
# account-truth disagreement". Each fixture below pins one named gate.


def test_recon_gate_match_clean_state_no_derived_codes(tmp_path):
    # §9 MATCH: a fresh imported snapshot with zero positions, valid balances,
    # and no execution receipts reconciles cleanly against an empty local
    # projection — the derived set is empty and severity is 'none'.
    home = tmp_path / "home"
    _seed_no_positions(home)
    snap = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-match", "source_system": "external-reconciler", "source_precedence": 1, "staleness_status": "fresh", "captured_at": "2026-05-28T00:01:00.000Z", "as_of": "2026-05-28T00:01:00.000Z", "positions": [], "balances": [{"asset": "USD", "total": "100"}], "idempotency_key": "snapshot-match"})
    assert snap.ok, snap

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-match", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-match"})

    assert rec.ok, rec
    assert rec.data["mismatch_codes"] == []
    assert rec.data["diff_severity"] == "none"
    assert rec.data["observed_imported_state"]["account_snapshot"]["id"] == snap.data["id"]


def test_recon_gate_mismatch_orphan_and_duplicate(tmp_path):
    # §9 MISMATCH: orphan external fill (no intent) + duplicate fill ref derive
    # critical-tier mismatch codes deterministically.
    home = tmp_path / "home"
    _seed_no_positions(home)
    snap = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-mismatch", "source_system": "external-reconciler", "source_precedence": 1, "staleness_status": "fresh", "captured_at": "2026-05-28T00:01:00.000Z", "as_of": "2026-05-28T00:01:00.000Z", "positions": [], "balances": [{"asset": "USD", "total": "100"}], "idempotency_key": "snapshot-mismatch"})
    assert snap.ok, snap
    for n in (1, 2):
        dup = _call("external_receipt.import", {"home": str(home), "semantic_key": f"orphan-dup-{n}", "lifecycle_state": "filled", "external_event_type": "fill", "source_system": "external-reconciler", "as_of": "2026-05-28T00:02:00.000Z", "external_fill_ref": "dup-ref", "sanitized_facts": {"filled_quantity": "1", "average_fill_price": "0.5", "fee_amount": "0.01"}, "idempotency_key": f"orphan-dup-{n}"})
        assert dup.ok, dup

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-mismatch", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-mismatch"})

    assert rec.ok, rec
    codes = set(rec.data["mismatch_codes"])
    assert {"ORPHAN_EXTERNAL_FILL", "DUPLICATE_FILL"} <= codes
    assert rec.data["diff_severity"] == "critical"


def test_recon_gate_ambiguous_resolution_manual_channel(tmp_path):
    # §9 AMBIGUOUS RESOLUTION: AMBIGUOUS_RESOLUTION is not a derivation an empty
    # local state produces; it is an operator judgment surfaced on the
    # manually_flagged channel without contaminating the derived set.
    home = tmp_path / "home"
    _seed_no_positions(home)
    snap = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-ambig", "source_system": "external-reconciler", "source_precedence": 1, "staleness_status": "fresh", "captured_at": "2026-05-28T00:01:00.000Z", "as_of": "2026-05-28T00:01:00.000Z", "positions": [], "balances": [{"asset": "USD", "total": "100"}], "idempotency_key": "snapshot-ambig"})
    assert snap.ok, snap

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-ambig", "as_of": "2026-05-28T00:03:00.000Z", "mismatch_codes": ["AMBIGUOUS_RESOLUTION"], "resolution_status": "unresolved", "idempotency_key": "recon-ambig"})

    assert rec.ok, rec
    assert "AMBIGUOUS_RESOLUTION" in set(rec.data["manually_flagged"])
    assert "AMBIGUOUS_RESOLUTION" not in set(rec.data["mismatch_codes"])
    assert rec.data["resolution_status"] == "unresolved"


def test_recon_gate_stale_source_precedence(tmp_path):
    # §9 STALE SOURCE PRECEDENCE: when two snapshots exist, the lowest
    # source_precedence wins, and a stale staleness_status on the winning
    # snapshot derives STALE_SNAPSHOT. source_precedence ordering is reported.
    home = tmp_path / "home"
    _seed_no_positions(home)
    # Higher-precedence-number (less authoritative), fresh.
    low = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-low-prec", "source_system": "secondary", "source_precedence": 5, "staleness_status": "fresh", "captured_at": "2026-05-28T00:01:30.000Z", "as_of": "2026-05-28T00:01:30.000Z", "positions": [], "balances": [{"asset": "USD", "total": "100"}], "idempotency_key": "snapshot-low-prec"})
    assert low.ok, low
    # Most authoritative (precedence 1) but stale — precedence wins over freshness.
    top = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-top-prec", "source_system": "authoritative", "source_precedence": 1, "staleness_status": "stale", "captured_at": "2026-05-28T00:01:00.000Z", "as_of": "2026-05-28T00:01:00.000Z", "positions": [], "balances": [{"asset": "USD", "total": "100"}], "idempotency_key": "snapshot-top-prec"})
    assert top.ok, top

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-stale-prec", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-stale-prec"})

    assert rec.ok, rec
    # Precedence-1 snapshot is selected even though it is the staler/older one.
    assert rec.data["observed_imported_state"]["account_snapshot"]["id"] == top.data["id"]
    assert "STALE_SNAPSHOT" in set(rec.data["mismatch_codes"])
    assert rec.data["source_precedence"][0] == "imported_account_snapshots"


def test_recon_gate_local_vs_imported_position_disagreement(tmp_path):
    # §9 LOCAL-vs-IMPORTED DISAGREEMENT: a local open position exists, but the
    # imported snapshot reports zero positions — reconciliation must IDENTIFY the
    # disagreement (POSITION_MISMATCH) rather than rewrite local history.
    home = tmp_path / "home"
    _seed(home)  # seeds one open local position pos_1
    snap = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-disagree", "source_system": "external-reconciler", "source_precedence": 1, "staleness_status": "fresh", "captured_at": "2026-05-28T00:01:00.000Z", "as_of": "2026-05-28T00:01:00.000Z", "positions": [], "balances": [{"asset": "USD", "total": "100"}], "idempotency_key": "snapshot-disagree"})
    assert snap.ok, snap

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-disagree", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-disagree"})

    assert rec.ok, rec
    # Local projection is preserved (1 open position) and the disagreement with
    # the imported zero-position snapshot is flagged, not silently reconciled.
    assert rec.data["expected_state"]["open_position_count"] == 1
    assert rec.data["observed_imported_state"]["account_snapshot"]["positions"] == []
    assert "POSITION_MISMATCH" in set(rec.data["mismatch_codes"])


def test_recon_gate_local_vs_imported_balance_disagreement(tmp_path):
    # §9 LOCAL-vs-IMPORTED DISAGREEMENT (balance side, bead trade-trace-qfn8): an
    # imported snapshot whose balance entry carries no parseable numeric basis
    # (no total/available/balance) cannot be reconciled against local exposure, so
    # reconciliation._build_derived flags BALANCE_MISMATCH rather than guessing a
    # number. The companion clean case (test_recon_gate_match_clean_state...) pins
    # that a numeric `total` does NOT fire it, so this gate is the inverse edge.
    home = tmp_path / "home"
    _seed_no_positions(home)
    snap = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-bal-disagree", "source_system": "external-reconciler", "source_precedence": 1, "staleness_status": "fresh", "captured_at": "2026-05-28T00:01:00.000Z", "as_of": "2026-05-28T00:01:00.000Z", "positions": [], "balances": [{"asset": "USD", "note": "unparseable-no-numeric-basis"}], "idempotency_key": "snapshot-bal-disagree"})
    assert snap.ok, snap

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-bal-disagree", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-bal-disagree"})

    assert rec.ok, rec
    # The snapshot is selected as the observed imported truth, and its
    # non-numeric balance entry is flagged rather than silently reconciled.
    assert rec.data["observed_imported_state"]["account_snapshot"]["id"] == snap.data["id"]
    assert "BALANCE_MISMATCH" in set(rec.data["mismatch_codes"])


def test_recon_gate_missing_snapshot_derives_balance_and_position_mismatch(tmp_path):
    # §9 STALE/MISSING SOURCE (absence side, bead trade-trace-qfn8): when NO
    # imported account snapshot exists at or before as_of, reconciliation cannot
    # observe imported account truth at all, so _build_derived emits both
    # BALANCE_MISMATCH and POSITION_MISMATCH plus an absence caveat — the
    # disagreement is surfaced, never silently treated as a match.
    home = tmp_path / "home"
    _seed_no_positions(home)  # market/instrument only; no account_snapshot imported

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-no-snap", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-no-snap"})

    assert rec.ok, rec
    codes = set(rec.data["mismatch_codes"])
    assert {"BALANCE_MISMATCH", "POSITION_MISMATCH"} <= codes
    assert rec.data["observed_imported_state"]["account_snapshot"] is None
    caveat_codes = {c.get("code") for c in rec.data["caveats"] if isinstance(c, dict)}
    assert "IMPORTED_ACCOUNT_SNAPSHOT_UNAVAILABLE" in caveat_codes


# --- §9 external-receipt import gates (bead trade-trace-g776) ----------------
# autonomous-trader-substrate.md §9: "rejected external order, partial fill,
# duplicate fill, orphan external order/fill, ... and imported correction".
# Each fixture imports a sanitized external receipt and pins that
# reconciliation._build_derived consumes it into the correct derived code.


def test_recon_gate_rejected_external_order_for_approved_intent(tmp_path):
    # §9 REJECTED EXTERNAL ORDER: a `rejected` order receipt linked to an intent
    # whose approval_state is approved/waived elsewhere derives
    # REJECTED_APPROVED_INTENT — the executor rejected something the local audit
    # trail believed was cleared to go.
    home = tmp_path / "home"
    intent_id = _seed(home)  # intent-recon is approval_state='approved_elsewhere'
    snap = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-rej", "source_system": "external-reconciler", "source_precedence": 1, "staleness_status": "fresh", "captured_at": "2026-05-28T00:01:00.000Z", "as_of": "2026-05-28T00:01:00.000Z", "positions": [], "balances": [{"asset": "USD", "total": "100"}], "idempotency_key": "snapshot-rej"})
    assert snap.ok, snap
    rejected = _call("external_receipt.import", {"home": str(home), "semantic_key": "rej-order", "lifecycle_state": "rejected", "external_event_type": "order", "source_system": "external-reconciler", "as_of": "2026-05-28T00:02:00.000Z", "pretrade_intent_id": intent_id, "external_order_ref": "order-rej", "sanitized_facts": {}, "idempotency_key": "rej-order"})
    assert rejected.ok, rejected

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-rej", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-rej"})

    assert rec.ok, rec
    assert "REJECTED_APPROVED_INTENT" in set(rec.data["mismatch_codes"])
    assert intent_id in rec.data["contributing_ids"]["pretrade_intents"]


def test_recon_gate_orphan_external_order_no_intent(tmp_path):
    # §9 ORPHAN EXTERNAL ORDER: an `order` receipt with no pretrade_intent_id
    # derives ORPHAN_EXTERNAL_ORDER (the fill-typed counterpart derives
    # ORPHAN_EXTERNAL_FILL — see test_recon_gate_mismatch_orphan_and_duplicate).
    home = tmp_path / "home"
    _seed_no_positions(home)
    snap = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-orph-order", "source_system": "external-reconciler", "source_precedence": 1, "staleness_status": "fresh", "captured_at": "2026-05-28T00:01:00.000Z", "as_of": "2026-05-28T00:01:00.000Z", "positions": [], "balances": [{"asset": "USD", "total": "100"}], "idempotency_key": "snapshot-orph-order"})
    assert snap.ok, snap
    orphan = _call("external_receipt.import", {"home": str(home), "semantic_key": "orph-order", "lifecycle_state": "accepted", "external_event_type": "order", "source_system": "external-reconciler", "as_of": "2026-05-28T00:02:00.000Z", "external_order_ref": "order-orphan", "sanitized_facts": {}, "idempotency_key": "orph-order"})
    assert orphan.ok, orphan

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-orph-order", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-orph-order"})

    assert rec.ok, rec
    codes = set(rec.data["mismatch_codes"])
    assert "ORPHAN_EXTERNAL_ORDER" in codes
    assert "ORPHAN_EXTERNAL_FILL" not in codes


def test_recon_gate_unlinked_non_order_receipt_is_missing_event_not_orphan_order(tmp_path):
    # trade-trace-1k5d: an UNLINKED (no pretrade_intent_id) receipt whose
    # external_event_type is NOT order/fill (here `cancel`) must derive the
    # generic MISSING_EXTERNAL_EVENT code, not ORPHAN_EXTERNAL_ORDER — only an
    # order-typed orphan is an orphaned order.
    home = tmp_path / "home"
    _seed_no_positions(home)
    snap = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-orph-cancel", "source_system": "external-reconciler", "source_precedence": 1, "staleness_status": "fresh", "captured_at": "2026-05-28T00:01:00.000Z", "as_of": "2026-05-28T00:01:00.000Z", "positions": [], "balances": [{"asset": "USD", "total": "100"}], "idempotency_key": "snapshot-orph-cancel"})
    assert snap.ok, snap
    cancel = _call("external_receipt.import", {"home": str(home), "semantic_key": "orph-cancel", "lifecycle_state": "canceled", "external_event_type": "cancel", "source_system": "external-reconciler", "as_of": "2026-05-28T00:02:00.000Z", "external_order_ref": "order-cancel", "sanitized_facts": {}, "idempotency_key": "orph-cancel"})
    assert cancel.ok, cancel

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-orph-cancel", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-orph-cancel"})

    assert rec.ok, rec
    codes = set(rec.data["mismatch_codes"])
    assert "MISSING_EXTERNAL_EVENT" in codes
    assert "ORPHAN_EXTERNAL_ORDER" not in codes
    assert "ORPHAN_EXTERNAL_FILL" not in codes


def test_recon_gate_partial_fill_remaining_mismatch(tmp_path):
    # §9 PARTIAL FILL: a `partial_fill` fill receipt whose requested/filled/
    # remaining quantities are internally inconsistent derives
    # PARTIAL_FILL_REMAINING_MISMATCH (consumed from sanitized_facts).
    home = tmp_path / "home"
    # _seed_no_positions has no intent; create one so the partial fill is not an orphan.
    _seed_no_positions(home)
    intent = _call("pretrade_intent.record", {"home": str(home), "semantic_key": "intent-partial", "market_id": "m_1", "instrument_id": "i_1", "proposed_shape": {"side": "yes", "limit_price": "0.42", "quantity": "10"}, "risk_budget": {"max_loss": "4.20"}, "approval_state": "approved_elsewhere", "as_of": "2026-05-28T00:00:00.000Z", "idempotency_key": "intent-partial"})
    assert intent.ok, intent
    intent_id = intent.data["id"]
    snap = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-partial", "source_system": "external-reconciler", "source_precedence": 1, "staleness_status": "fresh", "captured_at": "2026-05-28T00:01:00.000Z", "as_of": "2026-05-28T00:01:00.000Z", "positions": [], "balances": [{"asset": "USD", "total": "100"}], "idempotency_key": "snapshot-partial"})
    assert snap.ok, snap
    partial = _call("external_receipt.import", {"home": str(home), "semantic_key": "partial-mismatch", "lifecycle_state": "partial_fill", "external_event_type": "fill", "source_system": "external-reconciler", "as_of": "2026-05-28T00:02:00.000Z", "pretrade_intent_id": intent_id, "external_fill_ref": "fill-partial", "external_order_ref": "order-partial", "sanitized_facts": {"requested_quantity": "10", "filled_quantity": "3", "remaining_quantity": "9", "average_fill_price": "0.42", "fee_amount": "0.01"}, "idempotency_key": "partial-mismatch"})
    assert partial.ok, partial

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-partial", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-partial"})

    assert rec.ok, rec
    assert "PARTIAL_FILL_REMAINING_MISMATCH" in set(rec.data["mismatch_codes"])


def test_recon_gate_imported_correction_is_consumed_not_orphaned(tmp_path):
    # §9 IMPORTED CORRECTION: a `corrected`/`correction` receipt linked to an
    # intent is consumed into the reconciliation derivation as a contributing
    # receipt (not an orphan) and the derived set stays reproducible.
    home = tmp_path / "home"
    intent_id = _seed(home)
    snap = _call("account_snapshot.import", {"home": str(home), "semantic_key": "snapshot-corr", "source_system": "external-reconciler", "source_precedence": 1, "staleness_status": "fresh", "captured_at": "2026-05-28T00:01:00.000Z", "as_of": "2026-05-28T00:01:00.000Z", "positions": [], "balances": [{"asset": "USD", "total": "100"}], "idempotency_key": "snapshot-corr"})
    assert snap.ok, snap
    correction = _call("external_receipt.import", {"home": str(home), "semantic_key": "corr-receipt", "lifecycle_state": "corrected", "external_event_type": "correction", "source_system": "external-reconciler", "as_of": "2026-05-28T00:02:00.000Z", "pretrade_intent_id": intent_id, "external_order_ref": "order-corr", "external_event_ref": "event-corr", "sanitized_facts": {"corrects_event_ref": "event-orig"}, "idempotency_key": "corr-receipt"})
    assert correction.ok, correction

    rec = _call("reconciliation.record", {"home": str(home), "semantic_key": "recon-corr", "as_of": "2026-05-28T00:03:00.000Z", "idempotency_key": "recon-corr"})

    assert rec.ok, rec
    # The correction receipt is a contributing input (linked to the intent), so
    # it is neither orphaned nor a rejected-approved breach.
    assert correction.data["id"] in rec.data["contributing_ids"]["external_receipts"]
    codes = set(rec.data["mismatch_codes"])
    assert "ORPHAN_EXTERNAL_ORDER" not in codes
    assert "ORPHAN_EXTERNAL_FILL" not in codes
    assert "REJECTED_APPROVED_INTENT" not in codes
