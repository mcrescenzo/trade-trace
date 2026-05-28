from __future__ import annotations

import sqlite3

from trade_trace.core import dispatch
from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path


def _args(home, **overrides):
    args = {
        "home": str(home),
        "semantic_key": overrides.pop("semantic_key", "paper:test:1"),
        "account_label": "local-paper",
        "side": "buy",
        "outcome_side": "yes",
        "requested_quantity": 10,
        "limit_price": 0.55,
        "reference_mid_price": 0.50,
        "slippage_cap_bps": 2000,
        "quote_id": "quote-1",
        "book_id": "book-1",
        "snapshot_id": "snap-1",
        "snapshot_as_of": "2026-05-28T00:00:00Z",
        "order_as_of": "2026-05-28T00:00:10Z",
        "book_levels": [{"price": 0.52, "quantity": 10}],
        "idempotency_key": overrides.pop("idempotency_key", None),
    }
    args.update(overrides)
    return args


def _dump(env):
    return env.model_dump(mode="json", exclude_none=True)


def _ok(env):
    dumped = _dump(env)
    assert dumped["ok"] is True, dumped
    return dumped["data"]


def _err(env):
    dumped = _dump(env)
    assert dumped["ok"] is False, dumped
    return dumped["error"]


def _paper_fill_count(home):
    db = open_database(db_path(home))
    try:
        apply_pending_migrations(db.connection)
        return db.connection.execute("SELECT COUNT(*) FROM paper_fill_records").fetchone()[0]
    finally:
        db.close()


def _paper_fill_event_count(home):
    db = open_database(db_path(home))
    try:
        apply_pending_migrations(db.connection)
        return db.connection.execute("SELECT COUNT(*) FROM events WHERE event_type = 'paper_fill.recorded'").fetchone()[0]
    finally:
        db.close()


def test_paper_fill_full_partial_no_fill_and_report_labels(initialized_home):
    full = _ok(dispatch("paper_fill.record", _args(initialized_home, idempotency_key="full"), actor_id="cli:tester"))
    assert full["environment"] == "paper"
    assert full["paper_only"] is True
    assert full["not_imported_account_truth"] is True
    assert full["fill_status"] == "full"
    assert full["filled_quantity"] == 10
    assert full["quote_id"] == "quote-1"
    assert full["book_id"] == "book-1"
    assert full["snapshot_id"] == "snap-1"

    partial = _ok(dispatch("paper_fill.record", _args(initialized_home, semantic_key="paper:test:partial", idempotency_key="partial", book_levels=[{"price": 0.52, "quantity": 4}]), actor_id="cli:tester"))
    assert partial["fill_status"] == "partial"
    assert partial["remaining_quantity"] == 6
    assert "insufficient_depth_partial_fill" in {c["code"] for c in partial["caveats"]}

    no_price = _ok(dispatch("paper_fill.record", _args(initialized_home, semantic_key="paper:test:noprice", idempotency_key="noprice", book_levels=[{"price": 0.60, "quantity": 10}]), actor_id="cli:tester"))
    assert no_price["fill_status"] == "no_fill"
    assert no_price["filled_quantity"] == 0
    assert "limit_price_not_fillable" in {c["code"] for c in no_price["caveats"]}

    report = _ok(dispatch("report.paper_exposure", {"home": str(initialized_home), "account_label": "local-paper"}, actor_id="cli:tester"))
    assert report["environment"] == "paper"
    assert report["mark_source"] == "paper_fill_records"
    assert report["no_live_execution_claims"] is True
    assert "imported/live account truth excluded" in report["source_precedence"]
    assert report["as_of"]
    assert report["confidence_label"] in {"low", "medium"}


def test_paper_fill_missing_stale_depth_slippage_and_idempotency(initialized_home):
    missing = _ok(dispatch("paper_fill.record", _args(initialized_home, semantic_key="paper:test:missing", idempotency_key="missing", book_levels=[]), actor_id="cli:tester"))
    assert missing["fill_status"] == "no_fill"
    assert missing["freshness_status"] == "missing"
    assert "missing_depth_no_fill" in {c["code"] for c in missing["caveats"]}

    stale = _ok(dispatch("paper_fill.record", _args(initialized_home, semantic_key="paper:test:stale", idempotency_key="stale", snapshot_as_of="2026-05-27T23:00:00Z"), actor_id="cli:tester"))
    assert stale["fill_status"] == "no_fill"
    assert stale["freshness_status"] == "stale"
    assert "stale_depth_no_fill" in {c["code"] for c in stale["caveats"]}

    slip = _ok(dispatch("paper_fill.record", _args(initialized_home, semantic_key="paper:test:slip", idempotency_key="slip", book_levels=[{"price": 0.70, "quantity": 10}], limit_price=0.75, slippage_cap_bps=100), actor_id="cli:tester"))
    assert slip["fill_status"] == "no_fill"
    assert "slippage_cap_exceeded_conservative_fill" in {c["code"] for c in slip["caveats"]}

    first = _ok(dispatch("paper_fill.record", _args(initialized_home, semantic_key="paper:test:idem", idempotency_key="idem"), actor_id="cli:tester"))
    second = _ok(dispatch("paper_fill.record", _args(initialized_home, semantic_key="paper:test:idem", idempotency_key="idem"), actor_id="cli:tester"))
    assert second["id"] == first["id"]

    conflict = _dump(dispatch("paper_fill.record", _args(initialized_home, semantic_key="paper:test:idem", idempotency_key="other", limit_price=0.56), actor_id="cli:tester"))
    assert conflict["ok"] is False
    assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_paper_fill_idempotency_key_conflicts_on_different_material(initialized_home):
    first = _ok(dispatch("paper_fill.record", _args(initialized_home, semantic_key="paper:test:samekey", idempotency_key="same"), actor_id="cli:tester"))
    assert first["id"]

    semantic_conflict = _err(dispatch("paper_fill.record", _args(initialized_home, semantic_key="paper:test:samekey:other", idempotency_key="same"), actor_id="cli:tester"))
    assert semantic_conflict["code"] == "IDEMPOTENCY_CONFLICT"
    assert semantic_conflict["details"]["code"] == "idempotency_conflict"
    assert _paper_fill_count(initialized_home) == 1
    assert _paper_fill_event_count(initialized_home) == 1

    material_conflict = _err(dispatch("paper_fill.record", _args(initialized_home, semantic_key="paper:test:samekey", idempotency_key="same", limit_price=0.56), actor_id="cli:tester"))
    assert material_conflict["code"] == "IDEMPOTENCY_CONFLICT"
    assert material_conflict["details"]["code"] == "idempotency_conflict"
    assert _paper_fill_count(initialized_home) == 1
    assert _paper_fill_event_count(initialized_home) == 1


def test_paper_fill_rejects_impossible_and_malformed_numeric_inputs(initialized_home):
    cases = [
        ({"requested_quantity": "NaN"}, "requested_quantity", "impossible_payload_quarantined"),
        ({"requested_quantity": 0}, "requested_quantity", "impossible_payload_quarantined"),
        ({"requested_quantity": -1}, "requested_quantity", "impossible_payload_quarantined"),
        ({"limit_price": "Infinity"}, "limit_price", "impossible_payload_quarantined"),
        ({"limit_price": -1}, "limit_price", "impossible_payload_quarantined"),
        ({"fee_amount": -1}, "fee_amount", "impossible_payload_quarantined"),
        ({"slippage_cap_bps": -1}, "slippage_cap_bps", "impossible_payload_quarantined"),
        ({"source_precedence": "abc"}, "source_precedence", "malformed_payload_quarantined"),
        ({"max_snapshot_age_seconds": "abc"}, "max_snapshot_age_seconds", "malformed_payload_quarantined"),
    ]
    for index, (overrides, field, detail_code) in enumerate(cases):
        error = _err(dispatch("paper_fill.record", _args(initialized_home, semantic_key=f"paper:test:numeric:{index}", idempotency_key=f"numeric-{index}", **overrides), actor_id="cli:tester"))
        assert error["code"] == "VALIDATION_ERROR"
        assert error["details"]["field"] == field
        assert error["details"]["code"] == detail_code
        assert _paper_fill_count(initialized_home) == 0
        assert _paper_fill_event_count(initialized_home) == 0


def test_paper_fill_append_only_triggers(initialized_home):
    data = _ok(dispatch("paper_fill.record", _args(initialized_home, idempotency_key="trigger"), actor_id="cli:tester"))
    db = open_database(db_path(initialized_home))
    try:
        apply_pending_migrations(db.connection)
        try:
            db.connection.execute("UPDATE paper_fill_records SET account_label = 'x' WHERE id = ?", (data["id"],))
            raise AssertionError("UPDATE should have failed")
        except sqlite3.DatabaseError as exc:
            assert "append-only invariant" in str(exc)
        try:
            db.connection.execute("DELETE FROM paper_fill_records WHERE id = ?", (data["id"],))
            raise AssertionError("DELETE should have failed")
        except sqlite3.DatabaseError as exc:
            assert "append-only invariant" in str(exc)
    finally:
        db.close()
