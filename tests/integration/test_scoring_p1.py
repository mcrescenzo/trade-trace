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


def test_categorical_brier_multiclass_scores_on_outcome(home):
    inst, thesis = _setup(home)
    f = _call(home, "forecast.add", {"thesis_id": thesis, "kind": "categorical", "outcomes": [
        {"outcome_label": "red", "probability": 0.2},
        {"outcome_label": "blue", "probability": 0.7},
        {"outcome_label": "green", "probability": 0.1},
    ]})
    assert f["ok"] is True
    out = _call(home, "outcome.add", {"instrument_id": inst, "resolved_at": "2026-05-19T00:00:00Z", "outcome_label": "blue", "status": "resolved_final"})
    assert out["ok"] is True
    metric, score, _ = _score_row(home, f["data"]["id"])
    assert metric == "brier_multiclass"
    assert score == pytest.approx((0.2 - 0) ** 2 + (0.7 - 1) ** 2 + (0.1 - 0) ** 2)


def test_scalar_squared_error_scores_on_numeric_outcome_value(home):
    inst, thesis = _setup(home)
    f = _call(home, "forecast.add", {"thesis_id": thesis, "kind": "scalar", "outcomes": [{"outcome_label": "value", "probability": 0.65}]})
    assert f["ok"] is True
    out = _call(home, "outcome.add", {"instrument_id": inst, "resolved_at": "2026-05-19T00:00:00Z", "outcome_label": "ignored", "outcome_value": 0.5, "status": "resolved_final"})
    assert out["ok"] is True
    metric, score, _ = _score_row(home, f["data"]["id"])
    assert metric == "squared_error_scalar"
    assert score == pytest.approx((0.65 - 0.5) ** 2)


def test_invalid_categorical_and_scalar_shapes_rejected(home):
    _, thesis = _setup(home)
    bad_cat = _call(home, "forecast.add", {"thesis_id": thesis, "kind": "categorical", "outcomes": [
        {"outcome_label": "a", "probability": 0.6}, {"outcome_label": "b", "probability": 0.6}
    ]})
    assert bad_cat["ok"] is False
    assert bad_cat["error"]["code"] == "INVARIANT_VIOLATION"
    bad_scalar = _call(home, "forecast.add", {"thesis_id": thesis, "kind": "scalar", "outcomes": [
        {"outcome_label": "a", "probability": 0.4}, {"outcome_label": "b", "probability": 0.6}
    ]})
    assert bad_scalar["ok"] is False
    assert bad_scalar["error"]["code"] == "INVARIANT_VIOLATION"


def test_rescan_preview_confirm_idempotent_noop_for_already_scored(home):
    inst, thesis = _setup(home)
    f = _call(home, "forecast.add", {"thesis_id": thesis, "kind": "categorical", "outcomes": [
        {"outcome_label": "a", "probability": 0.25}, {"outcome_label": "b", "probability": 0.75}
    ]})["data"]["id"]
    _call(home, "outcome.add", {"instrument_id": inst, "resolved_at": "2026-05-19T00:00:00Z", "outcome_label": "b", "status": "resolved_final"})

    preview = _call(home, "journal.rescan_scoring", {"mode": "preview"})
    assert preview["ok"] is True
    assert preview["data"]["affected_rows"] == 1
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
    _call(home, "outcome.add", {"instrument_id": inst, "resolved_at": "2026-05-19T00:00:00Z", "outcome_label": "NO", "status": "resolved_final"})
    metric, score, _ = _score_row(home, f)
    assert metric == "brier_binary"
    assert score == pytest.approx(0.49)
