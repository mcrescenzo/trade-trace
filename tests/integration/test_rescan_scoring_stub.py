from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage.paths import db_path


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


def test_rescan_scoring_ignores_legacy_categorical_scalar_without_writing_scores(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {"venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "X"})
    thesis = _envelope(home, "thesis.add", {"instrument_id": inst["data"]["id"], "side": "yes", "body": "..."})
    # forecast.add is intentionally binary-only in v0.0.2. Legacy
    # categorical/scalar rows may exist in older journals, but rescan must not
    # turn them into failed unsupported_kind score rows.
    with sqlite3.connect(db_path(home)) as conn:
        conn.executemany(
            """
            INSERT INTO forecasts (id, thesis_id, kind, scoring_support, scoring_state, created_at, actor_id)
            VALUES (?, ?, ?, 'supported', 'pending', '2026-05-18T14:00:00.000Z', 'test')
            """,
            [
                ("fc_legacy_categorical", thesis["data"]["id"], "categorical"),
                ("fc_legacy_scalar", thesis["data"]["id"], "scalar"),
            ],
        )
    _envelope(home, "forecast.add", {"thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes", "outcomes": [
        {"outcome_label": "yes", "probability": 0.6}, {"outcome_label": "no", "probability": 0.4}
    ]})
    preview = _envelope(home, "journal.rescan_scoring", {})
    assert preview["ok"] is True
    assert preview["data"]["affected_rows"] == 0
    assert preview["data"]["would_score_rows"] == 0
    assert preview["data"]["ignored_unsupported_rows"] == 2
    confirm = _envelope(home, "journal.rescan_scoring", {"mode": "confirm"})
    assert confirm["ok"] is True
    assert confirm["data"]["scored_rows"] == 0
    with sqlite3.connect(db_path(home)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM forecast_scores").fetchone()[0] == 0


def test_rescan_scoring_invalid_mode(home):
    env = _envelope(home, "journal.rescan_scoring", {"mode": "apply"})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_rescan_scoring_schema_introspectable():
    reg = default_registry().get("journal.rescan_scoring")
    assert "binary-only" in reg.description
