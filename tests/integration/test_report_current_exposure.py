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
    env = mcp_call("report.current_exposure", {"home": str(home), **(args or {})})
    return dump_envelope(env)


def _instrument(home: Path) -> str:
    venue = dump_envelope(mcp_call("venue.add", {"home": str(home), "name": "Test", "kind": "prediction_market"}))
    assert venue["ok"] is True, venue
    inst = dump_envelope(mcp_call(
        "instrument.add",
        {"home": str(home), "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "Will X happen?"},
    ))
    assert inst["ok"] is True, inst
    return inst["data"]["id"]


def _strategy(home: Path, slug: str) -> str:
    strategy = dump_envelope(mcp_call(
        "strategy.create",
        {"home": str(home), "name": slug, "slug": slug, "idempotency_key": f"test-{slug}"},
    ))
    assert strategy["ok"] is True, strategy
    return strategy["data"]["id"]


def _insert_decision(
    home: Path,
    *,
    decision_id: str,
    instrument_id: str,
    type_: str,
    created_at: str,
    reason: str = "recent note",
    strategy_id: str | None = None,
) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            """
            INSERT INTO decisions(
                id, instrument_id, type, side, quantity, price, reason,
                run_id, metadata_json, created_at, actor_id, strategy_id
            ) VALUES (?, ?, ?, 'yes', 1.0, 0.42, ?, 'run_current', '{}', ?, 'agent:test', ?)
            """,
            (decision_id, instrument_id, type_, reason, created_at, strategy_id),
        )
        db.connection.commit()
    finally:
        db.close()


def _insert_position(home: Path, *, instrument_id: str, position_id: str, decision_id: str) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            """
            INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, closed_at,
                                  resolved_at, realized_pnl, unrealized_pnl, avg_entry_price,
                                  updated_at, initial_risk_amount)
            VALUES (?, ?, 'paper', 'yes', 'open', '2026-05-20T00:00:00Z', NULL,
                    NULL, NULL, NULL, 0.42, '2026-05-20T00:00:00Z', 10.0)
            """,
            (position_id, instrument_id),
        )
        db.connection.execute(
            """
            INSERT INTO position_events(id, position_id, instrument_id, decision_id, event_type,
                                        quantity_delta, price, fees, slippage, metadata_json, created_at, actor_id)
            VALUES ('pe_current_open', ?, ?, ?, 'open', 1.0, 0.42, 0.0, 0.0, '{}', '2026-05-20T00:00:00Z', 'agent:test')
            """,
            (position_id, instrument_id, decision_id),
        )
        db.connection.commit()
    finally:
        db.close()


def test_current_exposure_clean_empty_is_positive(home: Path) -> None:
    body = _call(home)

    assert body["ok"] is True
    data = body["data"]
    assert data["summary"]["bucket"] == "current_exposure"
    assert data["summary"]["buckets"] == ["open_positions", "watchlist", "recent_trade_activity", "projection_anomalies"]
    for bucket in data["summary"]["buckets"]:
        assert bucket in data
    assert "anomalies" not in data
    assert data["lower_level_reports"]["projection_anomalies"] == "report.exposure_anomalies"
    assert data["summary"]["open_position_count"] == 0
    assert data["summary"]["watch_count"] == 0
    assert data["summary"]["recent_trade_decision_count"] == 0
    assert data["summary"]["anomaly_count"] == 0
    assert data["open_positions"] == []
    assert data["watchlist"] == []
    assert data["recent_trade_activity"] == []
    assert data["projection_anomalies"] == []
    assert any("No watch ideas" in hint for hint in data["agent_answer_hints"])


def test_current_exposure_omitted_as_of_surfaces_effective_timestamp_in_summary_and_meta(home: Path) -> None:
    current = _call(home)

    assert current["ok"] is True
    current_as_of = current["data"]["summary"]["filter"]["as_of"]
    assert current_as_of is not None
    assert current_as_of.endswith("Z")
    assert current["meta"]["normalized_filter"]["as_of"] == current_as_of


def test_current_exposure_explicit_as_of_preserved_in_summary_and_meta(home: Path) -> None:
    as_of = "2026-05-25T12:34:56Z"
    normalized_as_of = "2026-05-25T12:34:56.000Z"

    current = _call(home, {"as_of": as_of})
    assert current["ok"] is True
    assert current["data"]["summary"]["filter"]["as_of"] == normalized_as_of
    assert current["meta"]["normalized_filter"]["as_of"] == normalized_as_of


def test_current_exposure_combines_open_watch_recent_and_anomalies(home: Path) -> None:
    instrument_id = _instrument(home)
    watch = dump_envelope(mcp_call("decision.add", {
        "home": str(home), "instrument_id": instrument_id, "type": "watch",
        "reason": "watch this idea", "review_by": "2026-05-01T00:00:00Z",
    }))
    assert watch["ok"] is True, watch
    _insert_decision(home, decision_id="dec_open_current", instrument_id=instrument_id, type_="paper_enter", created_at="2026-05-20T00:00:00Z")
    _insert_position(home, instrument_id=instrument_id, position_id="pos_current", decision_id="dec_open_current")
    _insert_decision(home, decision_id="dec_record_only_current", instrument_id=instrument_id, type_="actual_enter", created_at="2026-05-21T00:00:00Z", reason="record-only actual note")

    body = _call(home, {"recent_limit": 5})

    assert body["ok"] is True
    data = body["data"]
    assert data["summary"]["open_position_count"] == 1
    assert data["summary"]["watch_count"] == 1
    assert data["summary"]["recent_trade_decision_count"] == 2
    assert data["summary"]["anomaly_count"] >= 1
    assert data["open_positions"][0]["position_id"] == "pos_current"
    assert data["watchlist"][0]["decision_id"] == watch["data"]["id"]
    assert data["watchlist"][0]["caveat_codes"] == ["WATCH_ONLY_IDEA"]
    recent = {row["decision_id"]: row for row in data["recent_trade_activity"]}
    assert recent["dec_record_only_current"]["instrument_id"] == instrument_id
    assert recent["dec_record_only_current"]["strategy_id"] is None
    assert recent["dec_record_only_current"]["run_id"] == "run_current"
    assert "RECORD_ONLY_ACTUAL" in recent["dec_record_only_current"]["caveat_codes"]
    assert any(row["code"] == "RECORD_ONLY_ACTUAL" for row in data["projection_anomalies"])
    assert any("Recent trade activity" in hint for hint in data["agent_answer_hints"])


def test_current_exposure_recent_without_open_positions_warns_not_exposure(home: Path) -> None:
    instrument_id = _instrument(home)
    _insert_decision(home, decision_id="dec_recent_only", instrument_id=instrument_id, type_="actual_enter", created_at="2026-05-21T00:00:00Z")

    body = _call(home, {"include_watchlist": False, "include_anomalies": False})

    assert body["data"]["summary"]["open_position_count"] == 0
    assert body["data"]["summary"]["recent_trade_decision_count"] == 1
    assert body["data"]["watchlist"] == []
    assert body["data"]["projection_anomalies"] == []
    assert "Canonical open positions: zero; recent journal entries exist but are not open exposure." in body["data"]["agent_answer_hints"]


def test_current_exposure_filters_scope_child_buckets(home: Path) -> None:
    in_scope = _instrument(home)
    out_scope = _instrument(home)
    keep_strategy = _strategy(home, "strat-keep")
    other_strategy = _strategy(home, "strat-other")
    _insert_decision(
        home,
        decision_id="watch_in_scope",
        instrument_id=in_scope,
        type_="watch",
        created_at="2026-05-19T00:00:00Z",
        reason="watch in scope",
        strategy_id=keep_strategy,
    )
    _insert_decision(
        home,
        decision_id="watch_out_scope",
        instrument_id=out_scope,
        type_="watch",
        created_at="2026-05-19T00:01:00Z",
        reason="watch out of scope",
        strategy_id=other_strategy,
    )
    _insert_decision(
        home,
        decision_id="recent_in_scope",
        instrument_id=in_scope,
        type_="paper_enter",
        created_at="2026-05-20T00:00:00Z",
        strategy_id=keep_strategy,
    )
    _insert_decision(
        home,
        decision_id="recent_out_scope",
        instrument_id=out_scope,
        type_="actual_enter",
        created_at="2026-05-21T00:00:00Z",
        reason="record-only out of scope",
        strategy_id=other_strategy,
    )
    _insert_decision(
        home,
        decision_id="anomaly_in_scope",
        instrument_id=in_scope,
        type_="paper_enter",
        created_at="2026-05-21T00:01:00Z",
        strategy_id=keep_strategy,
    )

    scoped = _call(home, {"instrument_id": in_scope, "strategy_id": keep_strategy, "recent_limit": 10})

    assert scoped["ok"] is True
    scoped_data = scoped["data"]
    assert scoped_data["summary"]["filter"]["instrument_id"] == in_scope
    assert scoped_data["summary"]["filter"]["strategy_id"] == keep_strategy
    assert {row["decision_id"] for row in scoped_data["watchlist"]} == {"watch_in_scope"}
    assert scoped_data["summary"]["watch_count"] == 1
    assert "watch_out_scope" not in {row["decision_id"] for row in scoped_data["watchlist"]}
    assert {row["decision_id"] for row in scoped_data["recent_trade_activity"]} == {
        "anomaly_in_scope",
        "recent_in_scope",
    }
    assert scoped_data["summary"]["recent_trade_decision_count"] == 2
    assert all(
        row["instrument_id"] == in_scope and row["strategy_id"] == keep_strategy
        for row in scoped_data["recent_trade_activity"]
    )
    scoped_anomaly_decisions = {
        decision_id
        for row in scoped_data["projection_anomalies"]
        for decision_id in row["affected_ids"].get("decisions", [])
    }
    assert "anomaly_in_scope" in scoped_anomaly_decisions
    assert "recent_out_scope" not in scoped_anomaly_decisions
    assert all(in_scope in row["affected_ids"].get("instruments", []) for row in scoped_data["projection_anomalies"])
    assert scoped_data["summary"]["anomaly_count"] == len(scoped_data["projection_anomalies"])

    kind_scoped = _call(
        home,
        {"instrument_id": in_scope, "strategy_id": keep_strategy, "kind": "paper", "recent_limit": 10},
    )

    assert kind_scoped["ok"] is True
    kind_data = kind_scoped["data"]
    assert kind_data["summary"]["filter"]["kind"] == "paper"
    assert kind_data["watchlist"] == []
    assert kind_data["summary"]["watch_count"] == 0
    assert {row["decision_id"] for row in kind_data["recent_trade_activity"]} == {
        "anomaly_in_scope",
        "recent_in_scope",
    }
    assert all(row["type"] == "paper_enter" for row in kind_data["recent_trade_activity"])
    kind_anomaly_decisions = {
        decision_id
        for row in kind_data["projection_anomalies"]
        for decision_id in row["affected_ids"].get("decisions", [])
    }
    assert "anomaly_in_scope" in kind_anomaly_decisions
    assert "recent_out_scope" not in kind_anomaly_decisions


def test_current_exposure_schema_mentions_recommended_packet() -> None:
    reg = __import__("trade_trace.core", fromlist=["default_registry"]).default_registry()
    registration = reg.get("report.current_exposure")

    assert registration.json_schema is not None
    text = (registration.description + " " + registration.json_schema.get("description", "")).lower()
    for phrase in ("recommended trader-agent entry point", "open_positions", "watchlist", "recent_trade_activity", "projection_anomalies"):
        assert phrase in text
