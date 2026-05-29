"""report.calibration_advisory — decision-time recalibration (trade-trace-4kec.7).

The forward-facing surface: given a candidate YES probability, return the
caller's own prior resolved forecasts in that equal-width 0.1 band, their
observed resolution rate, and a calibration-derived suggested_probability.
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


def _seed_resolved_forecast(home: Path, idx: int, *, probability: float, resolves_yes: bool) -> str:
    venue = _envelope(home, "venue.add", {"name": f"PM{idx}", "kind": "prediction_market"})["data"]["id"]
    inst = _envelope(
        home,
        "instrument.add",
        {"venue_id": venue, "asset_class": "prediction_market", "title": f"Market {idx}?"},
    )["data"]["id"]
    _envelope(
        home,
        "market.bind",
        {
            "id": inst,
            "source": "polymarket",
            "external_id": f"ext-{inst}",
            "title": f"Market {idx}?",
            "state": "resolved",
            "mechanism": "clob",
            "bound_via": "manual",
            "opened_at": "2027-01-01T00:00:00Z",
            "close_at": "2027-01-10T00:00:00Z",
            "closed_for_trading_at": "2027-01-10T00:00:00Z",
            "resolving_at": "2027-01-11T00:00:00Z",
            "resolved_at": "2027-01-12T00:00:00Z",
        },
    )
    thesis = _envelope(home, "thesis.add", {"instrument_id": inst, "side": "yes", "body": "t"})["data"]["id"]
    forecast = _envelope(
        home,
        "forecast.add",
        {
            "thesis_id": thesis,
            "kind": "binary",
            "yes_label": "yes",
            "resolution_at": "2027-01-12T00:00:00Z",
            "outcomes": [
                {"outcome_label": "yes", "probability": probability},
                {"outcome_label": "no", "probability": 1.0 - probability},
            ],
        },
    )["data"]["id"]
    _envelope(
        home,
        "outcome.add",
        {
            "instrument_id": inst,
            "resolved_at": "2027-01-12T00:00:00Z",
            "outcome_label": "yes" if resolves_yes else "no",
            "status": "resolved_final",
            "confidence": 0.99,
        },
    )
    return forecast


def _advisory(home: Path, probability: float, **extra):
    return mcp_call(
        "report.calibration_advisory",
        {"home": str(home), "probability": probability, **extra},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)


def test_advisory_registered_and_public():
    names = set(default_registry().public_names())
    assert "report.calibration_advisory" in names


def test_advisory_reports_band_observed_rate_and_adjustment(home: Path):
    # Four forecasts in band 7 (p in [0.7, 0.8)): two resolve YES, two NO.
    for i in range(2):
        _seed_resolved_forecast(home, i, probability=0.75, resolves_yes=True)
    for i in range(2, 4):
        _seed_resolved_forecast(home, i, probability=0.75, resolves_yes=False)

    env = _advisory(home, 0.72, min_sample=1)
    assert env["ok"], env
    summary = env["data"]["summary"]
    assert summary["band"]["bin_index"] == 7
    assert summary["band"]["lower"] == 0.7
    assert summary["band"]["upper"] == 0.8
    assert summary["sample_size"] == 4
    assert summary["observed_frequency"] == pytest.approx(0.5)
    assert summary["mean_probability"] == pytest.approx(0.75)
    # gap = observed - mean = 0.5 - 0.75 = -0.25
    assert summary["calibration_gap"] == pytest.approx(-0.25)
    assert summary["suggested_adjustment"] == pytest.approx(-0.25)
    # suggested = clamp(0.72 + (-0.25)) = 0.47
    assert summary["suggested_probability"] == pytest.approx(0.47)


def test_advisory_only_counts_same_band(home: Path):
    # One forecast in band 2, one in band 7. A band-2 candidate sees only the
    # band-2 forecast.
    _seed_resolved_forecast(home, 0, probability=0.25, resolves_yes=True)
    _seed_resolved_forecast(home, 1, probability=0.75, resolves_yes=False)

    env = _advisory(home, 0.22, min_sample=1)
    summary = env["data"]["summary"]
    assert summary["band"]["bin_index"] == 2
    assert summary["sample_size"] == 1
    assert summary["observed_frequency"] == pytest.approx(1.0)


def test_advisory_empty_band_returns_no_adjustment(home: Path):
    _seed_resolved_forecast(home, 0, probability=0.75, resolves_yes=True)

    env = _advisory(home, 0.15, min_sample=1)
    summary = env["data"]["summary"]
    assert summary["band"]["bin_index"] == 1
    assert summary["sample_size"] == 0
    assert summary["observed_frequency"] is None
    assert summary["suggested_probability"] is None
    assert summary["calibration_gap"] is None
    assert "no prior resolved forecasts" in summary["sample_warning"]


def test_advisory_low_sample_warns(home: Path):
    _seed_resolved_forecast(home, 0, probability=0.55, resolves_yes=True)
    env = _advisory(home, 0.55, min_sample=20)
    summary = env["data"]["summary"]
    assert summary["sample_size"] == 1
    assert "unreliable below 20" in summary["sample_warning"]


def test_advisory_top_band_is_closed_on_right(home: Path):
    _seed_resolved_forecast(home, 0, probability=0.95, resolves_yes=True)
    env = _advisory(home, 1.0, min_sample=1)
    summary = env["data"]["summary"]
    assert summary["band"]["bin_index"] == 9
    assert summary["sample_size"] == 1


@pytest.mark.parametrize("bad", [-0.1, 1.5, "x", None])
def test_advisory_rejects_out_of_range_probability(home: Path, bad):
    env = mcp_call(
        "report.calibration_advisory",
        {"home": str(home), "probability": bad},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_advisory_disclaims_advice_and_avoids_recommender_language(home: Path):
    import re

    from trade_trace.reports.coach import FORBIDDEN_PHRASES

    _seed_resolved_forecast(home, 0, probability=0.65, resolves_yes=True)
    env = _advisory(home, 0.65, min_sample=1)
    summary = env["data"]["summary"]

    # The output carries an explicit not-trade-advice disclaimer.
    assert any("not trade advice" in c.lower() for c in summary["caveats"])

    # No recommender phrasing anywhere outside the disclaiming caveats, judged
    # by the same word-boundary policy report.coach enforces.
    forbidden_re = re.compile(
        r"\b(" + "|".join(re.escape(p) for p in FORBIDDEN_PHRASES) + r")\b"
    )
    scanned = {k: v for k, v in summary.items() if k != "caveats"}
    assert not forbidden_re.findall(str(scanned).lower())
