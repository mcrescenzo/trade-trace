"""report.mistake_tripwire — decision-time recurring-mistake trip-wire
(trade-trace-4kec.10).

Given the tag fingerprint of a decision the agent is about to make, fire the
candidate tags that match the agent's own poorly-calibrated patterns, without
an explicit recall query.
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


def _seed_bad_forecast(home: Path, idx: int, tag: str, *, probability: float, resolves_yes: bool) -> None:
    """A confidently-wrong forecast tagged `tag`: high p but resolves NO (or vice
    versa) so the Brier is poor."""
    venue = _envelope(home, "venue.add", {"name": f"PM{idx}", "kind": "prediction_market"})["data"]["id"]
    inst = _envelope(home, "instrument.add", {"venue_id": venue, "asset_class": "prediction_market", "title": f"M{idx}"})["data"]["id"]
    _envelope(
        home, "market.bind",
        {"id": inst, "source": "polymarket", "external_id": f"ext-{inst}", "title": f"M{idx}",
         "state": "resolved", "mechanism": "clob", "bound_via": "manual",
         "opened_at": "2027-01-01T00:00:00Z", "close_at": "2027-01-10T00:00:00Z",
         "closed_for_trading_at": "2027-01-10T00:00:00Z", "resolving_at": "2027-01-11T00:00:00Z",
         "resolved_at": "2027-01-12T00:00:00Z"},
    )
    thesis = _envelope(home, "thesis.add", {"instrument_id": inst, "side": "yes", "body": "t"})["data"]["id"]
    forecast = _envelope(
        home, "forecast.add",
        {"thesis_id": thesis, "kind": "binary", "yes_label": "yes",
         "outcomes": [{"outcome_label": "yes", "probability": probability}, {"outcome_label": "no", "probability": 1.0 - probability}]},
    )["data"]["id"]
    _envelope(
        home, "decision.add",
        {"instrument_id": inst, "thesis_id": thesis, "forecast_id": forecast, "type": "watch",
         "side": "yes", "reason": "test", "tags": [tag]},
    )
    _envelope(
        home, "outcome.add",
        {"instrument_id": inst, "resolved_at": "2027-01-12T00:00:00Z",
         "outcome_label": "yes" if resolves_yes else "no", "status": "resolved_final", "confidence": 0.99},
    )


def _tripwire(home: Path, tags, **extra):
    return mcp_call(
        "report.mistake_tripwire",
        {"home": str(home), "tags": tags, **extra},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)


def test_tripwire_registered_public():
    assert "report.mistake_tripwire" in set(default_registry().public_names())


def test_tripwire_fires_on_matching_bad_pattern(home: Path):
    # Three confidently-wrong forecasts (p=0.9 but resolve NO) tagged 'chased'.
    for i in range(3):
        _seed_bad_forecast(home, i, "chased", probability=0.9, resolves_yes=False)

    env = _tripwire(home, ["chased", "fresh_tag"], min_sample=3)
    assert env["ok"], env
    summary = env["data"]["summary"]
    assert summary["triggered"] is True
    assert summary["match_count"] == 1
    group = env["data"]["groups"][0]
    assert group["key"] == "chased"
    assert group["metrics"]["mean_brier"] >= 0.25
    assert group["metrics"]["scored_forecast_count"] == 3


def test_tripwire_silent_when_no_candidate_tag_matches(home: Path):
    for i in range(3):
        _seed_bad_forecast(home, i, "chased", probability=0.9, resolves_yes=False)
    env = _tripwire(home, ["unrelated"], min_sample=3)
    assert env["data"]["summary"]["triggered"] is False
    assert env["data"]["groups"] == []


def test_tripwire_silent_for_well_calibrated_tag(home: Path):
    # Confidently-right forecasts (p=0.9 resolve YES) → low Brier, not a mistake.
    for i in range(3):
        _seed_bad_forecast(home, i, "disciplined", probability=0.9, resolves_yes=True)
    env = _tripwire(home, ["disciplined"], min_sample=3)
    assert env["data"]["summary"]["triggered"] is False


def test_tripwire_respects_min_sample(home: Path):
    _seed_bad_forecast(home, 0, "chased", probability=0.9, resolves_yes=False)
    env = _tripwire(home, ["chased"], min_sample=5)
    assert env["data"]["summary"]["triggered"] is False


def test_tripwire_rejects_non_list_tags(home: Path):
    env = mcp_call(
        "report.mistake_tripwire",
        {"home": str(home), "tags": "chased"},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_tripwire_emits_no_trade_advice(home: Path):
    import re

    from trade_trace.reports.coach import FORBIDDEN_PHRASES

    for i in range(3):
        _seed_bad_forecast(home, i, "chased", probability=0.9, resolves_yes=False)
    env = _tripwire(home, ["chased"], min_sample=3)
    summary = env["data"]["summary"]
    assert any("not trade advice" in c.lower() for c in summary["caveats"])
    forbidden_re = re.compile(r"\b(" + "|".join(re.escape(p) for p in FORBIDDEN_PHRASES) + r")\b")
    scanned = {k: v for k, v in summary.items() if k != "caveats"}
    assert not forbidden_re.findall(str(scanned).lower())
