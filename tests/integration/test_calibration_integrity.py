"""Anti-goodhart calibration integrity diagnostics per bead trade-trace-jzn.

≥2 tests per diagnostic (positive + negative) over the six hygiene panels
that surface in `report.calibration_integrity`, `report.calibration`, and
`report.coach`. The framing is intentionally hygiene-not-fraud: tests assert
the diagnostic fires on dirty fixtures and stays quiet on clean ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _mcp(home: Path, tool: str, args: dict | None = None):
    payload = {"home": str(home), **(args or {})}
    env = mcp_call(tool, payload, actor_id="agent:default")
    return env


def _seed_instrument(home: Path) -> str:
    venue = _mcp(home, "venue.add",
                 {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue,
        "asset_class": "prediction_market", "title": "X",
    }).data["id"]
    return inst


def _seed_resolved_binary_forecast(
    home: Path, *, p_yes: float = 0.6,
    resolved_label: str = "yes", status: str = "resolved_final",
    forecast_first: bool = True,
    scoring_support: str = "supported",
    instrument_id: str | None = None,
    resolved_at: str = "2026-06-30T00:00:00Z",
) -> dict:
    """Walk one forecast end-to-end. If `forecast_first=False`, the outcome
    is recorded before the forecast (used to construct suspicious_late
    fixtures)."""

    inst = instrument_id or _seed_instrument(home)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "t",
    }).data["id"]

    if forecast_first:
        f = _mcp(home, "forecast.add", {
            "thesis_id": thesis, "kind": "binary",
            "yes_label": "yes",
            "outcomes": [
                {"outcome_label": "yes", "probability": p_yes},
                {"outcome_label": "no", "probability": 1.0 - p_yes},
            ],
            "scoring_support": scoring_support,
        }).data["id"]
        _mcp(home, "outcome.add", {
            "instrument_id": inst,
            "resolved_at": resolved_at,
            "outcome_label": resolved_label, "status": status,
        })
    else:
        _mcp(home, "outcome.add", {
            "instrument_id": inst,
            "resolved_at": resolved_at,
            "outcome_label": resolved_label, "status": status,
        })
        f = _mcp(home, "forecast.add", {
            "thesis_id": thesis, "kind": "binary",
            "yes_label": "yes",
            "outcomes": [
                {"outcome_label": "yes", "probability": p_yes},
                {"outcome_label": "no", "probability": 1.0 - p_yes},
            ],
            "scoring_support": scoring_support,
        }).data["id"]
    return {"instrument_id": inst, "thesis_id": thesis, "forecast_id": f}


# -- registration ----------------------------------------------------


def test_report_calibration_integrity_registered():
    from trade_trace.core import default_registry
    assert "report.calibration_integrity" in default_registry().names()


def test_empty_db_returns_no_data_warning(home):
    env = _mcp(home, "report.calibration_integrity", {})
    assert env.ok
    summary = env.data["summary"]
    assert summary["total_decisions"] == 0
    assert summary["total_forecasts"] == 0
    assert summary["sample_warning"] == "no_data"


# -- (1) forecast_coverage --------------------------------------------


def test_forecast_coverage_reports_denominators(home):
    """positive: with some decisions + forecasts seeded, coverage reports
    the three denominator numbers and the percent."""

    _seed_resolved_binary_forecast(home, p_yes=0.6)
    env = _mcp(home, "report.calibration_integrity", {})
    diag = env.data["diagnostics"]["forecast_coverage"]
    assert diag["total_forecasts"] >= 1
    assert diag["scored_forecasts"] >= 1
    assert diag["denominator_coverage_pct"] is None or \
        isinstance(diag["denominator_coverage_pct"], float)


def test_forecast_coverage_clean_with_decisions(home):
    """positive variant: when a decision exists with a scored forecast,
    denominator_coverage_pct is computable."""

    seed = _seed_resolved_binary_forecast(home, p_yes=0.6)
    _mcp(home, "decision.add", {
        "type": "actual_enter",
        "instrument_id": seed["instrument_id"],
        "thesis_id": seed["thesis_id"],
        "forecast_id": seed["forecast_id"],
        "side": "yes", "quantity": 1, "price": 0.6,
        "idempotency_key": "00000000-0000-4000-8000-000000000100",
    })
    env = _mcp(home, "report.calibration_integrity", {})
    diag = env.data["diagnostics"]["forecast_coverage"]
    assert diag["total_decisions"] == 1
    assert diag["denominator_coverage_pct"] is not None


# -- (2) unsupported_rate --------------------------------------------


def test_unsupported_rate_fires_when_forecast_has_unsupported_kind(home):
    """positive: a forecast with `kind='categorical'` is stamped
    scoring_support='unsupported' by the M1 ledger (categorical/scalar
    scoring is P1 — scoring.md §4.3); the diagnostic catches it."""

    inst = _seed_instrument(home)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "t",
    }).data["id"]
    fcst = _mcp(home, "forecast.add", {
        "thesis_id": thesis, "kind": "categorical",
        "outcomes": [
            {"outcome_label": "low", "probability": 0.5},
            {"outcome_label": "high", "probability": 0.5},
        ],
    }).data["id"]
    env = _mcp(home, "report.calibration_integrity", {})
    diag = env.data["diagnostics"]["unsupported_rate"]
    assert diag["count"] == 1
    assert fcst in diag["sample_ids"]["forecasts"]
    assert diag["rate_pct"] == 100.0


def test_unsupported_rate_silent_on_clean_data(home):
    """negative: every forecast is `supported` → diagnostic emits 0."""

    _seed_resolved_binary_forecast(home, p_yes=0.6)
    _seed_resolved_binary_forecast(home, p_yes=0.7)
    env = _mcp(home, "report.calibration_integrity", {})
    diag = env.data["diagnostics"]["unsupported_rate"]
    assert diag["count"] == 0
    assert diag["sample_ids"]["forecasts"] == []


# -- (3) ambiguous_rate ---------------------------------------------


def test_ambiguous_rate_fires_on_ambiguous_outcome(home):
    """positive: one outcome marked status='ambiguous' → diagnostic counts
    it and surfaces the outcome id."""

    inst = _seed_instrument(home)
    out = _mcp(home, "outcome.add", {
        "instrument_id": inst,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "ambiguous",
    }).data["id"]
    env = _mcp(home, "report.calibration_integrity", {})
    diag = env.data["diagnostics"]["ambiguous_rate"]
    assert diag["count"] == 1
    assert out in diag["sample_ids"]["outcomes"]


def test_ambiguous_rate_silent_on_clean_data(home):
    _seed_resolved_binary_forecast(home, p_yes=0.6)  # resolved_final
    env = _mcp(home, "report.calibration_integrity", {})
    diag = env.data["diagnostics"]["ambiguous_rate"]
    assert diag["count"] == 0


# -- (4) disputed_rate ----------------------------------------------


def test_disputed_rate_fires_on_disputed_outcome(home):
    inst = _seed_instrument(home)
    out = _mcp(home, "outcome.add", {
        "instrument_id": inst,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "disputed",
    }).data["id"]
    env = _mcp(home, "report.calibration_integrity", {})
    diag = env.data["diagnostics"]["disputed_rate"]
    assert diag["count"] == 1
    assert out in diag["sample_ids"]["outcomes"]


def test_disputed_rate_silent_on_clean_data(home):
    _seed_resolved_binary_forecast(home, p_yes=0.6)
    env = _mcp(home, "report.calibration_integrity", {})
    diag = env.data["diagnostics"]["disputed_rate"]
    assert diag["count"] == 0


# -- (5) void_cancelled_rate ----------------------------------------


def test_void_cancelled_rate_fires_on_void_or_cancelled(home):
    inst = _seed_instrument(home)
    out_void = _mcp(home, "outcome.add", {
        "instrument_id": inst,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "void",
    }).data["id"]
    inst2 = _seed_instrument(home)
    out_cancelled = _mcp(home, "outcome.add", {
        "instrument_id": inst2,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "no", "status": "cancelled",
    }).data["id"]
    env = _mcp(home, "report.calibration_integrity", {})
    diag = env.data["diagnostics"]["void_cancelled_rate"]
    assert diag["count"] == 2
    ids = diag["sample_ids"]["outcomes"]
    assert out_void in ids and out_cancelled in ids


def test_void_cancelled_rate_silent_on_clean_data(home):
    _seed_resolved_binary_forecast(home, p_yes=0.6)
    env = _mcp(home, "report.calibration_integrity", {})
    diag = env.data["diagnostics"]["void_cancelled_rate"]
    assert diag["count"] == 0


# -- (6) suspicious_late_rate --------------------------------------


def test_suspicious_late_rate_fires_when_forecast_created_after_outcome(home):
    """positive: outcome.resolved_at is *in the past* relative to the
    forecast's `created_at` (which is `now()`), so the forecast was filed
    after the market had already resolved — the dogfood-protocol §2.2
    hygiene signal."""

    seed = _seed_resolved_binary_forecast(
        home, p_yes=0.6, forecast_first=False,
        resolved_at="2020-01-01T00:00:00Z",
    )
    env = _mcp(home, "report.calibration_integrity", {})
    diag = env.data["diagnostics"]["suspicious_late_rate"]
    assert diag["count"] == 1
    assert seed["forecast_id"] in diag["sample_ids"]["forecasts"]


def test_suspicious_late_rate_silent_when_forecast_first(home):
    """negative: forecast filed BEFORE outcome resolution → no late
    forecast, diagnostic emits zero."""

    _seed_resolved_binary_forecast(home, p_yes=0.6, forecast_first=True)
    env = _mcp(home, "report.calibration_integrity", {})
    diag = env.data["diagnostics"]["suspicious_late_rate"]
    assert diag["count"] == 0


# -- embedding: report.calibration includes integrity panel ----------


def test_report_calibration_embeds_integrity_diagnostics(home):
    """jzn acceptance: report.calibration's envelope carries the integrity
    panel under `data.integrity_diagnostics`, so an agent reading the
    Brier number always sees the denominator/hygiene context."""

    _seed_resolved_binary_forecast(home, p_yes=0.6)
    env = _mcp(home, "report.calibration", {})
    assert env.ok
    integrity = env.data["integrity_diagnostics"]
    assert "summary" in integrity
    assert "diagnostics" in integrity
    for required in (
        "forecast_coverage", "unsupported_rate", "ambiguous_rate",
        "disputed_rate", "void_cancelled_rate", "suspicious_late_rate",
    ):
        assert required in integrity["diagnostics"]


def test_report_coach_embeds_integrity_diagnostics(home):
    """jzn acceptance (extension): report.coach surfaces the same panel
    plus callouts for any non-zero rate."""

    seed = _seed_resolved_binary_forecast(
        home, p_yes=0.6, forecast_first=False,
        resolved_at="2020-01-01T00:00:00Z",
    )
    env = _mcp(home, "report.coach", {})
    assert env.ok, env
    coach = env.data
    assert "integrity_diagnostics" in coach
    # The late-recorded forecast triggers suspicious_late_rate → callout.
    callouts = " ".join(coach["callouts"])
    assert "suspicious_late_rate" in callouts
