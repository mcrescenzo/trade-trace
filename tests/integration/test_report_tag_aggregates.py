"""`report.mistakes` + `report.strengths` per trade-trace-nxn."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


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
        "confidence": 0.99,
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


# -- AX-048: unscored tags carry no Brier evidence -------------------


def _seed_tagged_decision_unscored(home: Path, *, tag: str, p_yes: float) -> None:
    """A tagged decision whose forecast is NOT yet scored (no outcome)."""
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": f"open-{tag}",
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


def test_unscored_tag_excluded_from_both_reports(home):
    # One scored tag (real Brier) + one tag whose forecast is still open. The
    # open tag has no Brier to attribute, so it is neither a recurring mistake
    # nor a recurring strength and must not appear in either ranked report —
    # matching report.mistake_tripwire / report.coach, which both gate on
    # scored evidence. Before the AX-048 fix the open tag surfaced (mean_brier
    # null) in BOTH reports, contradictorily labeled mistake AND strength.
    _seed_tagged_decision_with_scored_forecast(home, tag="scored-pat", p_yes=0.5)
    _seed_tagged_decision_unscored(home, tag="open-pat", p_yes=0.5)

    for report in ("report.mistakes", "report.strengths"):
        env = _envelope(home, report, {})
        keys = [g["key"] for g in env["data"]["groups"]]
        assert keys == ["scored-pat"], (report, keys)
        assert env["data"]["summary"]["metrics"]["tag_count"] == 1
        for g in env["data"]["groups"]:
            assert g["metrics"]["mean_brier"] is not None
            assert g["metrics"]["scored_forecast_count"] >= 1
