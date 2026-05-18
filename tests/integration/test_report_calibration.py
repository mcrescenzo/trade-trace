"""`report.calibration` aggregate per trade-trace-0rk.

Covers acceptance:
- ReportResult envelope shape per reports.md §3.
- Late-recorded exclusion default, include opt-in.
- sample_warning when N < min_sample.
- sharpness distinguishes always-50% from skewed forecasts.
- Drill-down: groups[0].record_ids enumerates contributing forecasts/scores.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


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


def _seed_one_scored_forecast(
    home: Path, *, p_yes: float, resolved_label: str = "yes",
    yes_label: str = "yes",
) -> str:
    """Resolve one forecast end-to-end via the public surface. Returns the
    forecast_id."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": yes_label,
        "outcomes": [
            {"outcome_label": yes_label, "probability": p_yes},
            {"outcome_label": "no", "probability": 1.0 - p_yes},
        ],
    })
    _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": resolved_label, "status": "resolved_final",
    })
    return f["data"]["id"]


# -- registration ---------------------------------------------------------


def test_report_calibration_registered():
    assert "report.calibration" in default_registry().names()


# -- empty DB ----------------------------------------------------------


def test_empty_db_returns_zero_sample_with_warning(home):
    env = _envelope(home, "report.calibration", {})
    assert env["ok"] is True
    data = env["data"]
    assert data["summary"]["sample_size"] == 0
    assert data["summary"]["sample_warning"] is not None
    assert "20" in data["summary"]["sample_warning"]


# -- envelope shape ----------------------------------------------------


def test_envelope_shape_matches_reports_md(home):
    _seed_one_scored_forecast(home, p_yes=0.6)
    env = _envelope(home, "report.calibration", {})
    data = env["data"]
    # summary fields per §3
    for key in ("sample_size", "sample_warning", "filter", "metrics"):
        assert key in data["summary"], f"missing summary.{key}"
    # groups[0] shape per §3
    assert len(data["groups"]) == 1
    g = data["groups"][0]
    for key in ("key", "label", "metrics", "filter", "record_ids",
                "examples", "sample_size", "sample_warning", "truncated"):
        assert key in g, f"missing groups[0].{key}"


# -- metrics: single forecast on y=1 ---------------------------------


def test_single_forecast_brier_matches_reference(home):
    # p=0.6, y=1 → brier=0.16
    _seed_one_scored_forecast(home, p_yes=0.6)
    env = _envelope(home, "report.calibration", {})
    data = env["data"]
    assert data["summary"]["metrics"]["brier"] == pytest.approx(0.16)
    assert data["summary"]["sample_size"] == 1


# -- late-recorded default exclusion --------------------------------


def test_late_recorded_excluded_by_default(home):
    """Per dogfood-protocol §2.2: forecasts created against an
    already-resolved outcome are stamped late_recorded=true on the score
    row and excluded from calibration aggregates by default."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    # outcome FIRST → forecast is late
    _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
    })
    _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.7},
            {"outcome_label": "no", "probability": 0.3},
        ],
    })

    # Default: late row excluded.
    env_excluded = _envelope(home, "report.calibration", {})
    assert env_excluded["data"]["summary"]["sample_size"] == 0
    assert env_excluded["data"]["summary"]["late_recorded_excluded"] >= 1
    caveats = env_excluded["data"]["summary"]["caveats"]
    assert any("late-recorded" in c for c in caveats)


def test_late_recorded_included_on_opt_in(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
    })
    _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.7},
            {"outcome_label": "no", "probability": 0.3},
        ],
    })

    env_included = _envelope(home, "report.calibration", {
        "filter": {"outcome": {"include_late_recorded": True}},
    })
    assert env_included["data"]["summary"]["sample_size"] == 1


# -- sharpness distinguishes always-50% from skewed -----------------


def test_sharpness_zero_for_all_50_percent_forecasts(home):
    for _ in range(3):
        _seed_one_scored_forecast(home, p_yes=0.5)
    env = _envelope(home, "report.calibration", {"min_sample": 3})
    sharpness = env["data"]["summary"]["metrics"]["sharpness"]
    assert sharpness == pytest.approx(0.0)


def test_sharpness_positive_for_skewed_forecasts(home):
    for p in (0.2, 0.5, 0.9):
        _seed_one_scored_forecast(home, p_yes=p)
    env = _envelope(home, "report.calibration", {"min_sample": 3})
    sharpness = env["data"]["summary"]["metrics"]["sharpness"]
    assert sharpness > 0


# -- drill-down: record_ids enumerate contributing rows -------------


def test_record_ids_enumerate_contributing_forecasts(home):
    fid = _seed_one_scored_forecast(home, p_yes=0.6)
    env = _envelope(home, "report.calibration", {})
    g = env["data"]["groups"][0]
    assert fid in g["record_ids"]["forecasts"]


# -- min_sample warning threshold ----------------------------------


def test_sample_warning_fires_below_threshold(home):
    _seed_one_scored_forecast(home, p_yes=0.6)
    env = _envelope(home, "report.calibration", {})
    # default min_sample=20, sample_size=1 → warning fires.
    assert env["data"]["summary"]["sample_warning"] is not None


def test_sample_warning_silent_above_threshold(home):
    """When sample_size >= min_sample, sample_warning is null."""

    # Add 5 scored forecasts and lower the threshold to 3.
    for _ in range(5):
        _seed_one_scored_forecast(home, p_yes=0.6)
    env = _envelope(home, "report.calibration", {"min_sample": 3})
    assert env["data"]["summary"]["sample_warning"] is None


# -- input validation ----------------------------------------------


def test_unknown_filter_field_rejected(home):
    env = _envelope(home, "report.calibration", {
        "filter": {"made_up_group": {}},
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


# -- reliability bins ---------------------------------------------


def test_reliability_bins_emitted(home):
    _seed_one_scored_forecast(home, p_yes=0.6)
    env = _envelope(home, "report.calibration", {})
    bins = env["data"]["summary"]["metrics"]["reliability_bins"]
    # 10 equal-width bins, canonical field names per scoring.md §7.2
    assert len(bins) == 10
    # p_yes=0.6 lands in bin idx=6 (0.6..0.7)
    bin_with_data = next(b for b in bins if b["count"] > 0)
    assert bin_with_data["bin_index"] == 6
    assert bin_with_data["lower"] == pytest.approx(0.6)
    assert bin_with_data["upper"] == pytest.approx(0.7)
    assert bin_with_data["bin_midpoint"] == pytest.approx(0.65)
    # empty bins surface count=0 with null means
    empty_bin = next(b for b in bins if b["count"] == 0)
    assert empty_bin["mean_probability"] is None
    assert empty_bin["observed_frequency"] is None
    assert empty_bin["gap"] is None
