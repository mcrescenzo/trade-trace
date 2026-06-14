"""report.autonomy_readiness — earned-autonomy readiness EVIDENCE BUNDLE
(bead trade-trace-r91l).

These tests pin the load-bearing properties:

* The bundle COMPOSES report.phase_gate_readiness rather than duplicating its
  verdict — its `summary.ready` / `gate_status` are the gate's, verbatim.
* It is EVIDENCE-ONLY: a strong calibration trend can NEVER turn a not-ready
  gate into a ready one; the agent cannot self-grant a wallet by leaning on the
  trend.
* Each gate criterion is re-projected with a stable
  pass/fail/insufficient_data `state` and contributing record_ids
  (reports.md §3.0/§3.1).
* The longitudinal calibration trend and expectancy series are partitioned into
  resolution-time windows with their own record_ids and insufficient_data flags
  (never zero-filled).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _data(home: Path, args: dict | None = None) -> dict:
    env = mcp_call(
        "report.autonomy_readiness",
        {"home": str(home), **(args or {})},
        actor_id="agent:default",
    )
    assert env.ok, env
    return env.model_dump(mode="json", exclude_none=True)["data"]


def _env(home: Path, tool: str, args: dict) -> dict:
    out = mcp_call(tool, {"home": str(home), **args}, actor_id="agent:default")
    assert out.ok, out
    return out.model_dump(mode="json", exclude_none=True)["data"]


def _seed_resolved_forecast(
    home: Path,
    idx: int,
    *,
    probability: float,
    resolves_yes: bool,
    resolved_at: str = "2027-01-12T00:00:00Z",
) -> None:
    venue = _env(home, "venue.add", {"name": f"PM{idx}", "kind": "prediction_market"})["id"]
    inst = _env(
        home,
        "instrument.add",
        {"venue_id": venue, "asset_class": "prediction_market", "title": f"Market {idx}?"},
    )["id"]
    _env(
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
            "resolved_at": resolved_at,
        },
    )
    thesis = _env(home, "thesis.add", {"instrument_id": inst, "side": "yes", "body": "t"})["id"]
    _env(
        home,
        "forecast.add",
        {
            "thesis_id": thesis,
            "kind": "binary",
            "yes_label": "yes",
            "resolution_at": resolved_at,
            "outcomes": [
                {"outcome_label": "yes", "probability": probability},
                {"outcome_label": "no", "probability": 1.0 - probability},
            ],
        },
    )
    _env(
        home,
        "outcome.add",
        {
            "instrument_id": inst,
            "resolved_at": resolved_at,
            "outcome_label": "yes" if resolves_yes else "no",
            "status": "resolved_final",
            "confidence": 0.99,
        },
    )


_FULL_THRESHOLDS = {
    "resolved_n": 2,
    "brier": 1.0,
    "skill_vs_market": -10.0,
    "reconciliation_cleanliness": 0,
    "audit_readiness": True,
    "paper_fill_coverage": 0.0,
}


def test_report_registered_and_public():
    names = set(default_registry().public_names())
    assert "report.autonomy_readiness" in names


def test_bundle_composes_all_evidence_sections(home: Path):
    data = _data(home)
    # The four longitudinal/composed sections plus the criteria projection.
    for key in (
        "summary",
        "criteria",
        "gate",
        "calibration_trend",
        "expectancy_series",
        "audit_hygiene",
    ):
        assert key in data, key
    # It is an evidence bundle, never a verdict surface.
    assert data["summary"]["evidence_only"] is True
    assert data["contract_version"] == "autonomy_readiness.v0"
    # The composed gate is the real report.phase_gate_readiness payload.
    assert "gate_status" in data["gate"]["summary"]


def test_empty_journal_unset_thresholds_insufficient_not_ready(home: Path):
    data = _data(home)
    summary = data["summary"]
    assert summary["ready"] is False
    assert summary["gate_status"] == "owner_thresholds_unset"
    assert summary["owner_thresholds_complete"] is False
    # Every criterion is indeterminate -> insufficient_data, never fail/pass.
    states = {c["key"]: c["state"] for c in data["criteria"]}
    assert set(states.values()) == {"insufficient_data"}
    assert summary["criteria_insufficient_data"] == len(data["criteria"])


def test_ready_passthrough_matches_underlying_gate(home: Path):
    """summary.ready / gate_status are the gate's verbatim — the bundle adds no
    verdict of its own."""
    _seed_resolved_forecast(home, 1, probability=0.7, resolves_yes=True)
    _seed_resolved_forecast(home, 2, probability=0.7, resolves_yes=True)
    bundle = _data(home, {"thresholds": _FULL_THRESHOLDS})
    gate = _env(home, "report.phase_gate_readiness", {"thresholds": _FULL_THRESHOLDS})
    assert bundle["summary"]["ready"] == gate["summary"]["ready"]
    assert bundle["summary"]["gate_status"] == gate["summary"]["gate_status"]
    # The embedded gate is byte-identical to a standalone phase_gate call.
    assert bundle["gate"]["criteria"] == gate["criteria"]


def test_strong_trend_cannot_self_grant_when_threshold_unset(home: Path):
    """The load-bearing safety invariant: a passing track record + a clean
    trend CANNOT make the bundle ready while ANY owner threshold is unset. The
    trend is evidence, not a vote."""
    _seed_resolved_forecast(home, 1, probability=0.7, resolves_yes=True)
    _seed_resolved_forecast(home, 2, probability=0.7, resolves_yes=True)
    partial = {k: v for k, v in _FULL_THRESHOLDS.items() if k != "paper_fill_coverage"}
    data = _data(home, {"thresholds": partial})
    assert data["summary"]["ready"] is False
    assert data["summary"]["gate_status"] == "owner_thresholds_unset"


def test_criteria_state_vocabulary_and_record_ids(home: Path):
    """Each criterion carries a stable pass/fail/insufficient_data state; the
    failing reconciliation criterion carries contributing record_ids."""
    rec = mcp_call(
        "reconciliation.record",
        {
            "home": str(home),
            "semantic_key": "ar-recon-critical",
            "as_of": "2027-02-01T00:00:00Z",
            "mismatch_codes": ["DUPLICATE_FILL"],
            "resolution_status": "unresolved",
            "idempotency_key": "ar-recon-critical",
        },
        actor_id="agent:default",
    )
    assert rec.ok, rec
    _seed_resolved_forecast(home, 1, probability=0.6, resolves_yes=True)
    _seed_resolved_forecast(home, 2, probability=0.4, resolves_yes=False)
    data = _data(home, {"thresholds": {**_FULL_THRESHOLDS, "reconciliation_cleanliness": 0}})
    by_key = {c["key"]: c for c in data["criteria"]}
    assert set(by_key) == {
        "resolved_n",
        "brier",
        "skill_vs_market",
        "reconciliation_cleanliness",
        "audit_readiness",
        "paper_fill_coverage",
    }
    # resolved_n clears (2 >= 2).
    assert by_key["resolved_n"]["state"] == "pass"
    # The open critical reconciliation record fails cleanliness and lists its id.
    recon = by_key["reconciliation_cleanliness"]
    assert recon["state"] == "fail"
    assert len(recon["record_ids"]["reconciliation_records"]) >= 1
    # The audit_hygiene section re-surfaces the same open-critical signal.
    assert data["audit_hygiene"]["reconciliation_cleanliness"]["open_critical_count"] >= 1
    assert "DUPLICATE_FILL" in data["audit_hygiene"]["reconciliation_cleanliness"]["critical_codes"]


def test_calibration_trend_windows_have_record_ids_and_low_n_flag(home: Path):
    _seed_resolved_forecast(home, 1, probability=0.6, resolves_yes=True)
    _seed_resolved_forecast(home, 2, probability=0.4, resolves_yes=False)
    data = _data(home, {"min_sample": 20})
    trend = data["calibration_trend"]
    assert trend["coverage"]["eligible_count"] == 2
    assert trend["windows"], "expected at least one resolution-time window"
    # Two resolved forecasts in the same window; N=2 < min_sample=20 is flagged
    # insufficient_data, but the metrics are still surfaced (never zero-filled).
    total = sum(w["sample_size"] for w in trend["windows"])
    assert total == 2
    flagged = [w for w in trend["windows"] if w["sample_size"] > 0]
    assert flagged and all(w["insufficient_data"] for w in flagged)
    populated = next(w for w in flagged if w["sample_size"] > 0)
    assert len(populated["record_ids"]["forecasts"]) == populated["sample_size"]
    assert populated["metrics"] is not None


def test_calibration_trend_partitions_by_resolution_time(home: Path):
    """Forecasts resolved far apart land in distinct trailing windows."""
    _seed_resolved_forecast(home, 1, probability=0.6, resolves_yes=True, resolved_at="2027-01-05T00:00:00Z")
    _seed_resolved_forecast(home, 2, probability=0.4, resolves_yes=False, resolved_at="2027-06-05T00:00:00Z")
    data = _data(home, {"window_days": 30})
    windows = data["calibration_trend"]["windows"]
    nonempty = [w for w in windows if w["sample_size"] > 0]
    # ~5 months apart with 30-day windows -> two separate occupied windows.
    assert len(nonempty) == 2


def test_empty_journal_trends_are_empty_not_fabricated(home: Path):
    data = _data(home)
    assert data["calibration_trend"]["windows"] == []
    assert data["calibration_trend"]["coverage"]["eligible_count"] == 0
    assert data["expectancy_series"]["windows"] == []
    assert data["expectancy_series"]["coverage"]["eligible_count"] == 0


def test_unknown_threshold_key_rejected(home: Path):
    env = mcp_call(
        "report.autonomy_readiness",
        {"home": str(home), "thresholds": {"bogus_bar": 1}},
        actor_id="agent:default",
    )
    assert not env.ok
    assert env.error.code == "VALIDATION_ERROR"


def test_non_object_thresholds_rejected(home: Path):
    env = mcp_call(
        "report.autonomy_readiness",
        {"home": str(home), "thresholds": [1, 2, 3]},
        actor_id="agent:default",
    )
    assert not env.ok
    assert env.error.code == "VALIDATION_ERROR"


def test_bad_window_days_rejected(home: Path):
    env = mcp_call(
        "report.autonomy_readiness",
        {"home": str(home), "window_days": 0},
        actor_id="agent:default",
    )
    assert not env.ok
    assert env.error.code == "VALIDATION_ERROR"


def test_bad_max_windows_rejected(home: Path):
    env = mcp_call(
        "report.autonomy_readiness",
        {"home": str(home), "max_windows": 0},
        actor_id="agent:default",
    )
    assert not env.ok
    assert env.error.code == "VALIDATION_ERROR"
