from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.storage.paths import db_path


def _call(home: Path, tool: str, args: dict):
    return mcp_call(tool, {"home": str(home), **args}, actor_id="agent:test").model_dump(mode="json", exclude_none=True)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert _call(h, "journal.init", {})["ok"] is True
    return h


def _setup(home: Path):
    v = _call(home, "venue.add", {"name": "PM", "kind": "prediction_market"})["data"]["id"]
    i = _call(home, "instrument.add", {"venue_id": v, "asset_class": "prediction_market", "title": "P1 scoring"})["data"]["id"]
    t = _call(home, "thesis.add", {"instrument_id": i, "side": "yes", "body": "body"})["data"]["id"]
    return i, t


def _score_row(home: Path, forecast_id: str):
    conn = sqlite3.connect(db_path(home))
    try:
        return conn.execute("SELECT metric, score, metadata_json FROM forecast_scores WHERE forecast_id = ?", (forecast_id,)).fetchone()
    finally:
        conn.close()


def test_non_binary_forecast_kinds_rejected_for_v0_0_2(home):
    _, thesis = _setup(home)
    for kind, outcomes in (
        ("categorical", [
            {"outcome_label": "red", "probability": 0.2},
            {"outcome_label": "blue", "probability": 0.7},
            {"outcome_label": "green", "probability": 0.1},
        ]),
        ("scalar", [{"outcome_label": "value", "probability": 0.65}]),
    ):
        env = _call(home, "forecast.add", {"thesis_id": thesis, "kind": kind, "outcomes": outcomes})
        assert env["ok"] is False
        assert env["error"]["code"] == "VALIDATION_ERROR"
        assert env["error"]["details"]["supported_kinds"] == ["binary"]


def test_rescan_preview_confirm_idempotent_noop_for_already_scored_binary(home):
    inst, thesis = _setup(home)
    f = _call(home, "forecast.add", {"thesis_id": thesis, "kind": "binary", "yes_label": "yes", "outcomes": [
        {"outcome_label": "yes", "probability": 0.25}, {"outcome_label": "no", "probability": 0.75}
    ]})["data"]["id"]
    _call(home, "resolution.add", {"instrument_id": inst, "resolved_at": "2026-05-19T00:00:00Z", "outcome_label": "no", "status": "resolved_final", "confidence": 0.99})

    preview = _call(home, "journal.rescan_scoring", {"mode": "preview"})
    assert preview["ok"] is True
    assert preview["data"]["affected_rows"] in (0, 1)
    assert preview["data"]["would_score_rows"] == 0
    confirm = _call(home, "journal.rescan_scoring", {"mode": "confirm"})
    assert confirm["ok"] is True
    assert confirm["data"]["scored_rows"] == 0
    replay = _call(home, "journal.rescan_scoring", {"mode": "confirm"})
    assert replay["ok"] is True
    assert replay["data"]["scored_rows"] == 0
    conn = sqlite3.connect(db_path(home))
    try:
        assert conn.execute("SELECT COUNT(*) FROM forecast_scores WHERE forecast_id = ?", (f,)).fetchone()[0] == 1
    finally:
        conn.close()


def test_binary_brier_regression_preserved(home):
    inst, thesis = _setup(home)
    f = _call(home, "forecast.add", {"thesis_id": thesis, "kind": "binary", "yes_label": "YES", "outcomes": [
        {"outcome_label": "YES", "probability": 0.7}, {"outcome_label": "NO", "probability": 0.3}
    ]})["data"]["id"]
    _call(home, "resolution.add", {"instrument_id": inst, "resolved_at": "2026-05-19T00:00:00Z", "outcome_label": "NO", "status": "resolved_final", "confidence": 0.99})
    metric, score, _ = _score_row(home, f)
    assert metric == "brier_binary"
    assert score == pytest.approx(0.49)
