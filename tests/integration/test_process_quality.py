"""report.process_quality — bet-sizing vs declared-edge Kelly-consistency,
outcome-independent (trade-trace-4kec.11).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _instrument(home: Path, idx: int) -> str:
    venue = _envelope(home, "venue.add", {"name": f"PM{idx}", "kind": "prediction_market"})["data"]["id"]
    return _envelope(home, "instrument.add", {"venue_id": venue, "asset_class": "prediction_market", "title": f"M{idx}"})["data"]["id"]


def _sized_entry(home: Path, idx: int, *, probability: float, price: float, quantity: float, side: str = "yes") -> None:
    inst = _instrument(home, idx)
    thesis = _envelope(home, "thesis.add", {"instrument_id": inst, "side": side, "body": "t"})["data"]["id"]
    forecast = _envelope(
        home, "forecast.add",
        {"thesis_id": thesis, "kind": "binary", "yes_label": "yes",
         "outcomes": [{"outcome_label": "yes", "probability": probability}, {"outcome_label": "no", "probability": 1.0 - probability}]},
    )["data"]["id"]
    _envelope(
        home, "decision.add",
        {"instrument_id": inst, "thesis_id": thesis, "forecast_id": forecast, "type": "paper_enter",
         "side": side, "quantity": quantity, "price": price, "reason": "r"},
    )


def _pq(home: Path, **extra):
    return mcp_call("report.process_quality", {"home": str(home), **extra}, actor_id="agent:default").model_dump(mode="json", exclude_none=True)


def test_process_quality_registered_public():
    assert "report.process_quality" in set(default_registry().public_names())


def test_perfectly_edge_proportional_sizing_scores_one(home: Path):
    # A: edge 0.4 -> kelly 0.8, sized 80; B: edge 0.1 -> kelly 0.2, sized 20.
    _sized_entry(home, 0, probability=0.9, price=0.5, quantity=80)
    _sized_entry(home, 1, probability=0.6, price=0.5, quantity=20)
    env = _pq(home, min_sample=1)
    assert env["ok"], env
    summary = env["data"]["summary"]
    assert summary["sample_size"] == 2
    assert summary["kelly_alignment"] == pytest.approx(1.0)
    assert summary["direction_consistency_rate"] == pytest.approx(1.0)


def test_inverted_sizing_scores_low(home: Path):
    # Size inversely to edge: A big edge small size, B small edge big size.
    _sized_entry(home, 0, probability=0.9, price=0.5, quantity=20)
    _sized_entry(home, 1, probability=0.6, price=0.5, quantity=80)
    env = _pq(home, min_sample=1)
    assert env["data"]["summary"]["kelly_alignment"] == pytest.approx(0.4)


def test_negative_edge_flagged_direction_inconsistent(home: Path):
    # p < price on yes side => negative stated edge.
    _sized_entry(home, 0, probability=0.4, price=0.5, quantity=10)
    env = _pq(home, min_sample=1)
    summary = env["data"]["summary"]
    assert summary["direction_consistency_rate"] == pytest.approx(0.0)
    group = env["data"]["groups"][0]
    assert group["metrics"]["direction_consistent"] is False
    assert group["metrics"]["kelly_fraction"] == 0.0


def test_no_outcome_consulted_still_scores(home: Path):
    # No outcome.add is ever called; the score is purely process-side.
    _sized_entry(home, 0, probability=0.8, price=0.4, quantity=50)
    env = _pq(home, min_sample=1)
    assert env["ok"]
    assert env["data"]["summary"]["sample_size"] == 1
    assert "process quality only" in env["data"]["summary"]["caveats"][0].lower()


def test_low_sample_warns(home: Path):
    _sized_entry(home, 0, probability=0.8, price=0.4, quantity=50)
    env = _pq(home, min_sample=5)
    assert "unreliable below 5" in env["data"]["summary"]["sample_warning"]


def test_empty_is_clean(home: Path):
    env = _pq(home)
    summary = env["data"]["summary"]
    assert summary["sample_size"] == 0
    assert summary["kelly_alignment"] is None
    assert "no sized decisions" in summary["sample_warning"]


def test_no_trade_advice_language(home: Path):
    import re

    from trade_trace.reports.coach import FORBIDDEN_PHRASES

    _sized_entry(home, 0, probability=0.9, price=0.5, quantity=80)
    env = _pq(home, min_sample=1)
    summary = env["data"]["summary"]
    forbidden_re = re.compile(r"\b(" + "|".join(re.escape(p) for p in FORBIDDEN_PHRASES) + r")\b")
    scanned = {k: v for k, v in summary.items() if k != "caveats"}
    assert not forbidden_re.findall(str(scanned).lower())
