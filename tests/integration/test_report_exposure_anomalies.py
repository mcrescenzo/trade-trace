from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.contracts.envelope import dump_envelope
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    init = mcp_call("journal.init", {"home": str(h)})
    assert init.ok, init
    return h


def _call(home: Path, args: dict | None = None) -> dict:
    env = mcp_call("report.exposure_anomalies", {"home": str(home), **(args or {})})
    return dump_envelope(env)


def _assert_boundary(data: dict) -> None:
    for field in (
        "local_evidence_only",
        "non_executing",
        "credential_blind",
        "advice_free",
        "no_live_execution_claims",
        "no_settlement_or_redemption_claims",
        "not_broker_truth",
    ):
        assert data[field] is True
    caveat = data["boundary_caveat"].lower()
    for phrase in ("local journal/projection", "not broker/imported account truth", "live execution", "settlement", "redemption", "advice"):
        assert phrase in caveat


def _instrument(home: Path, title: str = "Will X happen?") -> str:
    venue = dump_envelope(mcp_call("venue.add", {"home": str(home), "name": "Test", "kind": "prediction_market"}))
    assert venue["ok"] is True, venue
    inst = dump_envelope(mcp_call(
        "instrument.add",
        {"home": str(home), "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": title},
    ))
    assert inst["ok"] is True, inst
    return inst["data"]["id"]


def _insert_decision(home: Path, *, decision_id: str, instrument_id: str, type_: str, created_at: str, run_id: str = "run", reason: str = "", metadata_json: str = "{}") -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            """
            INSERT INTO decisions(
                id, instrument_id, type, side, quantity, price, reason, run_id,
                metadata_json, created_at, actor_id
            ) VALUES (?, ?, ?, 'yes', 1.0, 0.42, ?, ?, ?, ?, 'agent:test')
            """,
            (decision_id, instrument_id, type_, reason, run_id, metadata_json, created_at),
        )
        db.connection.commit()
    finally:
        db.close()


def _insert_position(home: Path, *, instrument_id: str, position_id: str, unrealized_pnl: float | None = None, updated_at: str = "2026-05-20T00:00:00Z") -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            """
            INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, closed_at,
                                  resolved_at, realized_pnl, unrealized_pnl, avg_entry_price, updated_at)
            VALUES (?, ?, 'paper', 'yes', 'open', '2026-05-01T00:00:00Z', NULL,
                    NULL, NULL, ?, 0.42, ?)
            """,
            (position_id, instrument_id, unrealized_pnl, updated_at),
        )
        db.connection.commit()
    finally:
        db.close()


def _insert_event(home: Path, *, event_id: str, instrument_id: str, position_id: str, created_at: str, decision_id: str | None = None) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            """
            INSERT INTO position_events(id, position_id, instrument_id, decision_id, event_type,
                                        quantity_delta, price, fees, slippage, metadata_json, created_at, actor_id)
            VALUES (?, ?, ?, ?, 'open', 1.0, 0.42, 0.0, 0.0, '{}', ?, 'agent:test')
            """,
            (event_id, position_id, instrument_id, decision_id, created_at),
        )
        db.connection.commit()
    finally:
        db.close()


def _insert_snapshot(home: Path, *, instrument_id: str, captured_at: str) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            """
            INSERT INTO snapshots(id, instrument_id, captured_at, source, source_url,
                                  price, bid, ask, mid, implied_probability, created_at, actor_id)
            VALUES ('snap_exposure_anomaly', ?, ?, 'test', NULL, 0.5, NULL, NULL, NULL, NULL, ?, 'agent:test')
            """,
            (instrument_id, captured_at, captured_at),
        )
        db.connection.commit()
    finally:
        db.close()


def _codes(body: dict) -> set[str]:
    return {row["code"] for row in body["data"]["projection_anomalies"]}


def test_exposure_anomalies_clean_empty_journal_returns_positive_zero(home: Path) -> None:
    body = _call(home)

    assert body["ok"] is True
    assert body["data"]["summary"]["bucket"] == "projection_anomalies"
    assert body["data"]["summary"]["count"] == 0
    assert body["data"]["summary"]["anomaly_count"] == 0
    assert body["data"]["summary"]["severity_counts"] == {"data_quality": 0, "market_risk": 0}
    assert body["data"]["projection_anomalies"] == []
    assert body["data"]["agent_answer_hints"]
    _assert_boundary(body["data"])


def test_exposure_anomalies_flags_duplicate_record_only_and_missing_position_event(home: Path) -> None:
    instrument_id = _instrument(home)
    _insert_decision(home, decision_id="dec_actual_1", instrument_id=instrument_id, type_="actual_enter", created_at="2026-05-20T00:00:00Z", reason="record-only dogfood, not externally executed")
    _insert_decision(home, decision_id="dec_actual_2", instrument_id=instrument_id, type_="actual_enter", created_at="2026-05-20T00:01:00Z", reason="record only duplicate")

    body = _call(home)

    codes = _codes(body)
    assert "ENTRY_DECISION_WITHOUT_POSITION_EVENT" in codes
    assert "RECORD_ONLY_ACTUAL" in codes
    assert "DUPLICATE_DECISIONS" in codes
    assert body["data"]["summary"]["severity_counts"]["market_risk"] == 0
    record_only = [row for row in body["data"]["projection_anomalies"] if row["code"] == "RECORD_ONLY_ACTUAL"]
    assert any("record-only" in row["evidence"]["record_only_phrase_matches"] for row in record_only)


def test_exposure_anomalies_flags_missing_and_stale_mark(home: Path) -> None:
    instr_missing = _instrument(home, "Missing mark instrument")
    instr_stale = _instrument(home, "Stale mark instrument")
    _insert_position(home, instrument_id=instr_missing, position_id="pos_missing_mark", unrealized_pnl=None)
    _insert_position(home, instrument_id=instr_stale, position_id="pos_stale_mark", unrealized_pnl=1.5)
    _insert_snapshot(home, instrument_id=instr_stale, captured_at="2026-05-01T00:00:00Z")

    body = _call(home, {"as_of": "2026-05-21T00:00:00Z", "stale_mark_threshold_days": 14})

    assert "MISSING_MARK" in _codes(body)
    assert "STALE_MARK" in _codes(body)


@pytest.mark.parametrize(
    ("args", "message", "details"),
    [
        (
            {"stale_mark_threshold_days": -1},
            "stale_mark_threshold_days must be a non-negative integer",
            {"field": "stale_mark_threshold_days", "value": -1},
        ),
        (
            {"stale_mark_threshold_days": "14"},
            "stale_mark_threshold_days must be a non-negative integer",
            {"field": "stale_mark_threshold_days", "value": "14"},
        ),
        (
            {"as_of": 123},
            "as_of must be an ISO timestamp string",
            {"field": "as_of", "value": 123},
        ),
    ],
)
def test_exposure_anomalies_temporal_validation_errors_are_stable(
    home: Path,
    args: dict,
    message: str,
    details: dict,
) -> None:
    body = _call(home, args)

    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == message
    assert body["error"]["details"] == details


def test_exposure_anomalies_flags_fragmented_same_side_exposure(home: Path) -> None:
    # trade-trace-scx8: paper_enter ALWAYS opens an independent position, so an
    # autonomous feeder re-entering the same market across runs accumulates
    # several open same-side rows. These differ in quantity/price/run_id and so
    # never trip the exact-replay DUPLICATE_DECISIONS query — the detector must
    # flag the fragmentation from the PROJECTION (positions table) instead.
    instrument_id = _instrument(home)
    # Two open positions on the SAME instrument+side (_insert_position fixes
    # side='yes' and status='open') — the fragmentation signature.
    _insert_position(home, instrument_id=instrument_id, position_id="pos_frag_a", unrealized_pnl=1.0)
    _insert_position(home, instrument_id=instrument_id, position_id="pos_frag_b", unrealized_pnl=2.0)

    body = _call(home)

    codes = _codes(body)
    assert "FRAGMENTED_SAME_SIDE_EXPOSURE" in codes
    frag = [r for r in body["data"]["projection_anomalies"] if r["code"] == "FRAGMENTED_SAME_SIDE_EXPOSURE"]
    assert len(frag) == 1, frag
    row = frag[0]
    assert row["evidence"]["instrument_id"] == instrument_id
    assert row["evidence"]["side"] == "yes"
    assert row["evidence"]["open_position_count"] == 2
    assert set(row["affected_ids"]["positions"]) == {"pos_frag_a", "pos_frag_b"}
    assert row["affected_ids"]["instruments"] == [instrument_id]
    assert body["data"]["summary"]["severity_counts"]["market_risk"] == 0


def test_exposure_anomalies_single_open_position_is_not_fragmented(home: Path) -> None:
    # One open position on an instrument+side is normal exposure, not
    # fragmentation — the anomaly must require MORE THAN ONE open same-side row.
    instrument_id = _instrument(home)
    _insert_position(home, instrument_id=instrument_id, position_id="pos_solo", unrealized_pnl=1.0)

    body = _call(home)

    assert "FRAGMENTED_SAME_SIDE_EXPOSURE" not in _codes(body)


def test_exposure_anomalies_flags_projection_missing_and_stale(home: Path) -> None:
    instrument_id = _instrument(home)
    _insert_position(home, instrument_id=instrument_id, position_id="pos_stale_projection", updated_at="2026-05-01T00:00:00Z")
    _insert_event(home, event_id="pe_later", instrument_id=instrument_id, position_id="pos_stale_projection", created_at="2026-05-02T00:00:00Z")
    _insert_event(home, event_id="pe_orphan", instrument_id=instrument_id, position_id="pos_missing_projection", created_at="2026-05-03T00:00:00Z")

    body = _call(home)

    assert "PROJECTION_STALE" in _codes(body)
    assert "PROJECTION_MISSING" in _codes(body)


def test_exposure_anomalies_schema_mentions_projection_anomalies_and_stable_codes() -> None:
    reg = __import__("trade_trace.core", fromlist=["default_registry"]).default_registry()
    registration = reg.get("report.exposure_anomalies")

    assert registration.json_schema is not None
    text = (registration.description + " " + registration.json_schema.get("description", "")).lower()
    assert "projection_anomalies" in text
    assert "entry_decision_without_position_event" in text
    assert "record_only_actual" in text
    assert "fragmented_same_side_exposure" in text
    assert "not market risk" in text
    for phrase in ("broker truth", "live execution", "settlement/redemption", "advice"):
        assert phrase in text
