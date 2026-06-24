"""`report.unscored_forecasts` + `report.decision_velocity` per trade-trace-5ud."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage.paths import db_path


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


def _seed_unscored(home: Path) -> str:
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "resolution_at": "2026-04-01T00:00:00Z",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    return f["data"]["id"]


def _set_decision_created_at(home: Path, decision_id: str, created_at: str) -> None:
    conn = sqlite3.connect(db_path(home))
    try:
        triggers = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'decisions' AND sql LIKE '%UPDATE%'"
        ).fetchall()
        for (name,) in triggers:
            conn.execute(f'DROP TRIGGER "{name}"')
        conn.execute("UPDATE decisions SET created_at = ? WHERE id = ?", (created_at, decision_id))
        conn.commit()
    finally:
        conn.close()


# -- report.unscored_forecasts -----------------------------------------


def test_unscored_forecasts_registered():
    assert "report.unscored_forecasts" in default_registry().names()


def test_unscored_forecasts_empty_db(home):
    env = _envelope(home, "report.unscored_forecasts", {})
    assert env["ok"] is True
    assert env["data"]["summary"]["sample_size"] == 0
    assert env["data"]["groups"][0]["record_ids"]["forecasts"] == []


def test_unscored_forecasts_lists_pending_past_resolution(home):
    fid = _seed_unscored(home)
    env = _envelope(home, "report.unscored_forecasts", {})
    assert env["data"]["summary"]["metrics"]["unscored_count"] == 1
    assert fid in env["data"]["groups"][0]["record_ids"]["forecasts"]


def test_unscored_forecasts_resolved_removes_from_list(home):
    fid = _seed_unscored(home)
    # Find the instrument id by reading the only one.
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(home))
    try:
        inst_id = db.connection.execute("SELECT id FROM instruments").fetchone()[0]
    finally:
        db.close()
    _envelope(home, "resolution.add", {
        "instrument_id": inst_id,
        "resolved_at": "2026-06-01T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
    })
    env = _envelope(home, "report.unscored_forecasts", {})
    assert env["data"]["summary"]["metrics"]["unscored_count"] == 0
    assert fid not in env["data"]["groups"][0]["record_ids"]["forecasts"]


# -- report.decision_velocity ----------------------------------------


def test_decision_velocity_registered():
    assert "report.decision_velocity" in default_registry().names()


def test_decision_velocity_empty_db(home):
    env = _envelope(home, "report.decision_velocity", {})
    assert env["ok"] is True
    assert env["data"]["summary"]["sample_size"] == 0
    assert env["data"]["groups"] == []


def test_decision_velocity_counts_per_day(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "skip", "reason": "a",
        "idempotency_key": "test:decision-velocity-a",
    })
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "skip", "reason": "b",
        "idempotency_key": "test:decision-velocity-b",
    })
    env = _envelope(home, "report.decision_velocity", {"bucket": "day"})
    assert env["data"]["summary"]["sample_size"] == 2
    # Exactly one bucket (same day, two decisions).
    assert env["data"]["summary"]["metrics"]["bucket_count"] == 1
    group = env["data"]["groups"][0]
    assert group["metrics"]["count"] == 2
    assert group["metrics"]["by_type"] == {"skip": 2}


def test_decision_velocity_bucket_group_filter_round_trips_to_bucket(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    first = _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "skip", "reason": "a",
        "idempotency_key": "test:decision-velocity-bucket-a",
    })["data"]["id"]
    second = _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "skip", "reason": "b",
        "idempotency_key": "test:decision-velocity-bucket-b",
    })["data"]["id"]
    _set_decision_created_at(home, first, "2026-01-01T12:00:00Z")
    _set_decision_created_at(home, second, "2026-01-02T12:00:00Z")

    env = _envelope(home, "report.decision_velocity", {"bucket": "day"})
    groups = env["data"]["groups"]
    assert [group["record_ids"]["decisions"] for group in groups] == [[first], [second]]

    first_bucket = _envelope(home, "report.decision_velocity", {
        "bucket": "day",
        "filter": groups[0]["filter"],
    })

    assert first_bucket["data"]["summary"]["sample_size"] == 1
    assert first_bucket["data"]["groups"][0]["record_ids"]["decisions"] == [first]


def test_decision_velocity_bucket_validation(home):
    env = _envelope(home, "report.decision_velocity", {"bucket": "month"})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_decision_velocity_unknown_filter_rejected(home):
    env = _envelope(home, "report.decision_velocity", {
        "filter": {"made_up": {}},
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
