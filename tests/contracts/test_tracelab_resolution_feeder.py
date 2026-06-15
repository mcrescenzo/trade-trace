from __future__ import annotations

from pathlib import Path

import pytest

from tools.tracelab.resolution_feeder import (
    ManualResolution,
    ResolutionFeederError,
    feed_manual_resolutions,
    validate_resolution_payload,
)
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _envelope(home: Path, tool: str, args: dict, actor_id: str = "agent:test"):
    return mcp_call(tool, {"home": str(home), **args}, actor_id=actor_id).model_dump(
        mode="json", exclude_none=True
    )


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


def _setup_market(home: Path):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Will X happen?",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "test thesis",
    })
    return inst["data"]["id"], thesis["data"]["id"]


def _add_scoreable_forecast(home: Path, thesis_id: str):
    return _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })


@pytest.mark.parametrize(
    "confidence,label",
    [
        (None, "yes"),
        (0.89, "yes"),
        (0.99, "maybe"),
    ],
)
def test_payload_precheck_refuses_missing_low_confidence_or_non_binary_label(confidence, label):
    with pytest.raises(ResolutionFeederError):
        validate_resolution_payload(ManualResolution(
            instrument_id="inst_1",
            resolved_at="2026-06-30T00:00:00Z",
            outcome_label=label,
            confidence=confidence,
            confirm_outcome_label=label,
        ))


def test_payload_precheck_accepts_high_confidence_binary_label():
    validate_resolution_payload(ManualResolution(
        instrument_id="inst_1",
        resolved_at="2026-06-30T00:00:00Z",
        outcome_label="yes",
        confidence=0.9,
        confirm_outcome_label="YES",
    ))


def test_dual_check_blocks_unconfirmed_winning_outcome():
    with pytest.raises(ResolutionFeederError):
        validate_resolution_payload(ManualResolution(
            instrument_id="inst_1",
            resolved_at="2026-06-30T00:00:00Z",
            outcome_label="yes",
            confidence=0.99,
        ))


def test_forecast_presence_flags_no_scoreable_forecast_without_silent_zero(home):
    instrument_id, _thesis_id = _setup_market(home)

    result = feed_manual_resolutions(home, [ManualResolution(
        instrument_id=instrument_id,
        resolved_at="2026-06-30T00:00:00Z",
        outcome_label="yes",
        confidence=0.99,
        confirm_outcome_label="yes",
    )])

    assert result.submitted_count == 0
    assert result.resolved_but_no_forecast_count == 1
    assert result.health()["resolved_but_no_forecast"] == 1
    db = open_database(db_path(home))
    try:
        scores = db.connection.execute("SELECT COUNT(*) FROM forecast_scores").fetchone()[0]
        outcomes = db.connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
    finally:
        db.close()
    assert scores == 0
    assert outcomes == 0


def test_feeder_treats_committed_but_unrevealed_forecast_as_no_scoreable_forecast(home):
    instrument_id, thesis_id = _setup_market(home)
    forecast = _add_scoreable_forecast(home, thesis_id)
    assert forecast["ok"] is True
    committed = _envelope(home, "forecast.commit_blind", {"forecast_id": forecast["data"]["id"]})
    assert committed["ok"] is True

    result = feed_manual_resolutions(home, [ManualResolution(
        instrument_id=instrument_id,
        resolved_at="2026-06-30T00:00:00Z",
        outcome_label="yes",
        confidence=0.99,
        confirm_outcome_label="yes",
    )])

    assert result.submitted_count == 0
    assert result.resolved_but_no_forecast_count == 1
    db = open_database(db_path(home))
    try:
        scores = db.connection.execute("SELECT COUNT(*) FROM forecast_scores").fetchone()[0]
        outcomes = db.connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
    finally:
        db.close()
    assert scores == 0
    assert outcomes == 0


def test_integration_feed_writes_forecast_scores_row(home):
    instrument_id, thesis_id = _setup_market(home)
    forecast = _add_scoreable_forecast(home, thesis_id)
    assert forecast["ok"] is True

    result = feed_manual_resolutions(home, [ManualResolution(
        instrument_id=instrument_id,
        resolved_at="2026-06-30T00:00:00Z",
        outcome_label="yes",
        confidence=0.99,
        confirm_outcome_label="yes",
    )])

    assert result.submitted_count == 1
    assert result.submitted[0]["auto_scored_forecasts"][0]["forecast_id"] == forecast["data"]["id"]
    assert result.resolved_but_no_forecast_count == 0
    assert result.health()["resolved_but_unfed"] == 0
    db = open_database(db_path(home))
    try:
        row = db.connection.execute(
            "SELECT forecast_id, score FROM forecast_scores"
        ).fetchone()
    finally:
        db.close()
    assert row[0] == forecast["data"]["id"]
    assert row[1] == pytest.approx(0.16)


def test_feeder_emits_resolved_but_unfed_count(home):
    instrument_id, _thesis_id = _setup_market(home)
    out = _envelope(home, "resolution.add", {
        "instrument_id": instrument_id,
        "resolved_at": "2026-06-29T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.99,
    })
    assert out["ok"] is True

    result = feed_manual_resolutions(home, [])

    assert result.resolved_but_unfed_count == 1
    assert result.health()["resolved_but_unfed"] == 1
    assert result.health()["resolved_but_no_forecast"] == 0
