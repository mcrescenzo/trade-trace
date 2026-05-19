from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


def _envelope(home: Path, tool: str, args: dict):
    return mcp_call(tool, {"home": str(home), **args}, actor_id="agent:default").model_dump(mode="json", exclude_none=True)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).model_dump(mode="json")["ok"] is True
    return h


def test_rescan_scoring_registered():
    assert "journal.rescan_scoring" in default_registry().names()


def test_rescan_scoring_preview_empty_db(home):
    env = _envelope(home, "journal.rescan_scoring", {})
    assert env["ok"] is True
    assert env["data"]["mode"] == "preview"
    assert env["data"]["affected_rows"] == 0
    assert env["data"]["would_score_rows"] == 0


def test_rescan_scoring_preview_counts_pending_categorical_scalar(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {"venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "X"})
    thesis = _envelope(home, "thesis.add", {"instrument_id": inst["data"]["id"], "side": "yes", "body": "..."})
    _envelope(home, "forecast.add", {"thesis_id": thesis["data"]["id"], "kind": "categorical", "outcomes": [
        {"outcome_label": "a", "probability": 0.5}, {"outcome_label": "b", "probability": 0.5}
    ]})
    _envelope(home, "forecast.add", {"thesis_id": thesis["data"]["id"], "kind": "scalar", "outcomes": [
        {"outcome_label": "value", "probability": 0.4}
    ]})
    _envelope(home, "forecast.add", {"thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes", "outcomes": [
        {"outcome_label": "yes", "probability": 0.6}, {"outcome_label": "no", "probability": 0.4}
    ]})
    env = _envelope(home, "journal.rescan_scoring", {})
    assert env["ok"] is True
    assert env["data"]["affected_rows"] == 2


def test_rescan_scoring_invalid_mode(home):
    env = _envelope(home, "journal.rescan_scoring", {"mode": "apply"})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_rescan_scoring_schema_introspectable():
    reg = default_registry().get("journal.rescan_scoring")
    assert "Re-score" in reg.description or "re-score" in reg.description.lower()
