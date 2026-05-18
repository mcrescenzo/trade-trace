"""`report.mistakes` + `report.strengths` per trade-trace-nxn."""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


def _envelope(home: Path, tool: str, args: dict):
    payload = {"home": str(home), **args}
    return mcp_call(tool, payload, actor_id="agent:default").model_dump(
        mode="json", exclude_none=True
    )


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


def _seed_tagged_decision_with_scored_forecast(
    home: Path, *, tag: str, p_yes: float
) -> None:
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": f"X-{tag}-{p_yes}",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": p_yes},
            {"outcome_label": "no", "probability": 1.0 - p_yes},
        ],
    })
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"],
        "thesis_id": thesis["data"]["id"],
        "forecast_id": f["data"]["id"],
        "type": "paper_enter", "side": "yes", "quantity": 100, "price": p_yes,
        "tags": [tag],
    })
    _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
    })


# -- registration ------------------------------------------------------


def test_mistakes_registered():
    assert "report.mistakes" in default_registry().names()


def test_strengths_registered():
    assert "report.strengths" in default_registry().names()


# -- ordering ---------------------------------------------------------


def test_mistakes_orders_by_mean_brier_descending(home):
    # "bad-pattern" → p=0.1 (very wrong on y=1, Brier=0.81)
    # "good-pattern" → p=0.9 (very right on y=1, Brier=0.01)
    _seed_tagged_decision_with_scored_forecast(home, tag="bad-pattern", p_yes=0.1)
    _seed_tagged_decision_with_scored_forecast(home, tag="good-pattern", p_yes=0.9)
    env = _envelope(home, "report.mistakes", {})
    keys = [g["key"] for g in env["data"]["groups"]]
    assert keys == ["bad-pattern", "good-pattern"]


def test_strengths_orders_by_mean_brier_ascending(home):
    _seed_tagged_decision_with_scored_forecast(home, tag="bad-pattern", p_yes=0.1)
    _seed_tagged_decision_with_scored_forecast(home, tag="good-pattern", p_yes=0.9)
    env = _envelope(home, "report.strengths", {})
    keys = [g["key"] for g in env["data"]["groups"]]
    assert keys == ["good-pattern", "bad-pattern"]


# -- drill-down record_ids -------------------------------------------


def test_groups_carry_record_ids(home):
    _seed_tagged_decision_with_scored_forecast(home, tag="pat-1", p_yes=0.5)
    env = _envelope(home, "report.mistakes", {})
    g = env["data"]["groups"][0]
    assert len(g["record_ids"]["decisions"]) == 1
    assert len(g["record_ids"]["forecasts"]) == 1


# -- empty DB -------------------------------------------------------


def test_empty_db_returns_no_groups(home):
    env = _envelope(home, "report.mistakes", {})
    assert env["data"]["groups"] == []
    assert env["data"]["summary"]["metrics"]["tag_count"] == 0
