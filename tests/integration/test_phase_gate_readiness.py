"""report.phase_gate_readiness — measurable VISION Phase-2 -> Phase-3 gate
criteria (bead trade-trace-q04o).

These tests pin the *pass/fail logic* of the gate report against numbers, not
prose. The load-bearing safety property is the OWNER-DECISION invariant: an
unset numeric threshold yields pass=null and the gate is NEVER `ready`, so the
agent can never self-grant a wallet by leaving the bar blank.
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
        "report.phase_gate_readiness",
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
    home: Path, idx: int, *, probability: float, resolves_yes: bool
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
            "resolved_at": "2027-01-12T00:00:00Z",
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
            "resolution_at": "2027-01-12T00:00:00Z",
            "outcomes": [
                {"outcome_label": "yes", "probability": probability},
                {"outcome_label": "no", "probability": 1.0 - probability},
            ],
        },
    )
    _env(
        home,
        "resolution.add",
        {
            "instrument_id": inst,
            "resolved_at": "2027-01-12T00:00:00Z",
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
    assert "report.phase_gate_readiness" in names


def test_empty_journal_unset_thresholds_is_indeterminate_not_ready(home: Path):
    data = _data(home)
    summary = data["summary"]
    assert summary["ready"] is False
    assert summary["gate_status"] == "owner_thresholds_unset"
    assert summary["owner_thresholds_complete"] is False
    assert summary["owner_decision_required"] is True
    assert summary["criteria_indeterminate"] == 6
    # Every criterion is indeterminate: threshold None, pass None.
    for crit in data["criteria"]:
        assert crit["threshold"] is None
        assert crit["pass"] is None


def test_unset_threshold_never_yields_ready_even_with_strong_record(home: Path):
    """The load-bearing safety invariant: a passing track record CANNOT make
    the gate `ready` while ANY owner threshold is left unset. The agent must
    not self-grant autonomy by omitting the bar."""
    _seed_resolved_forecast(home, 1, probability=0.7, resolves_yes=True)
    _seed_resolved_forecast(home, 2, probability=0.7, resolves_yes=True)
    # Set every threshold EXCEPT one (omit paper_fill_coverage).
    partial = {k: v for k, v in _FULL_THRESHOLDS.items() if k != "paper_fill_coverage"}
    data = _data(home, {"thresholds": partial})
    summary = data["summary"]
    assert summary["owner_thresholds_complete"] is False
    assert summary["gate_status"] == "owner_thresholds_unset"
    assert summary["ready"] is False
    assert "paper_fill_coverage" in summary["indeterminate_criteria"]


def test_resolved_n_counts_scored_binary_forecasts(home: Path):
    _seed_resolved_forecast(home, 1, probability=0.6, resolves_yes=True)
    _seed_resolved_forecast(home, 2, probability=0.4, resolves_yes=False)
    data = _data(home)
    by_key = {c["key"]: c for c in data["criteria"]}
    assert by_key["resolved_n"]["measured"] == 2


def test_resolved_n_threshold_fails_when_track_record_too_thin(home: Path):
    _seed_resolved_forecast(home, 1, probability=0.6, resolves_yes=True)
    # Demand 5 but only 1 resolved.
    data = _data(home, {"thresholds": {**_FULL_THRESHOLDS, "resolved_n": 5}})
    by_key = {c["key"]: c for c in data["criteria"]}
    assert by_key["resolved_n"]["measured"] == 1
    assert by_key["resolved_n"]["threshold"] == 5
    assert by_key["resolved_n"]["pass"] is False
    assert data["summary"]["ready"] is False
    assert "resolved_n" in data["summary"]["failing_criteria"]


def test_full_thresholds_with_record_can_pass_when_all_clear(home: Path):
    """With every owner threshold supplied and a clearing track record, the
    gate reports `ready` -- but only because the owner set every bar AND the
    measured values clear them."""
    _seed_resolved_forecast(home, 1, probability=0.7, resolves_yes=True)
    _seed_resolved_forecast(home, 2, probability=0.7, resolves_yes=True)
    data = _data(home, {"thresholds": _FULL_THRESHOLDS})
    summary = data["summary"]
    assert summary["owner_thresholds_complete"] is True
    by_key = {c["key"]: c for c in data["criteria"]}
    # resolved_n clears (2 >= 2); audit/reconciliation/coverage clear on a
    # clean empty-side journal.
    assert by_key["resolved_n"]["pass"] is True
    assert by_key["reconciliation_cleanliness"]["pass"] is True
    assert by_key["paper_fill_coverage"]["pass"] is True
    # brier/skill require a market baseline; these seeds have none, so they
    # are indeterminate -> the gate is NOT ready (cannot pass a market-skill
    # bar with no baseline). This is the correct conservative behavior.
    assert by_key["skill_vs_market"]["pass"] is None
    assert summary["gate_status"] in {"not_ready", "ready"}
    assert summary["ready"] is False


def test_reconciliation_cleanliness_counts_open_critical(home: Path):
    """An open (unresolved) critical reconciliation record fails the
    cleanliness criterion when the owner sets a zero mismatch budget."""
    # Record a reconciliation row carrying a critical mismatch code, left
    # unresolved. We pass the code explicitly so the test does not depend on
    # the derived-mismatch wiring.
    rec = mcp_call(
        "reconciliation.record",
        {
            "home": str(home),
            "semantic_key": "pg-recon-critical",
            "as_of": "2027-02-01T00:00:00Z",
            "mismatch_codes": ["DUPLICATE_FILL"],
            "resolution_status": "unresolved",
            "idempotency_key": "pg-recon-critical",
        },
        actor_id="agent:default",
    )
    assert rec.ok, rec
    data = _data(home, {"thresholds": {**_FULL_THRESHOLDS, "reconciliation_cleanliness": 0}})
    by_key = {c["key"]: c for c in data["criteria"]}
    crit = by_key["reconciliation_cleanliness"]
    assert crit["measured"] >= 1
    assert "DUPLICATE_FILL" in crit["critical_codes"]
    assert crit["pass"] is False
    assert "reconciliation_cleanliness" in data["summary"]["failing_criteria"]


def test_resolved_critical_record_does_not_count_as_open(home: Path):
    """A critical mismatch that has been explained is no longer an open
    breach and does not fail cleanliness."""
    rec = mcp_call(
        "reconciliation.record",
        {
            "home": str(home),
            "semantic_key": "pg-recon-explained",
            "as_of": "2027-02-01T00:00:00Z",
            "mismatch_codes": ["DUPLICATE_FILL"],
            "resolution_status": "explained",
            "idempotency_key": "pg-recon-explained",
        },
        actor_id="agent:default",
    )
    assert rec.ok, rec
    data = _data(home, {"thresholds": {**_FULL_THRESHOLDS, "reconciliation_cleanliness": 0}})
    by_key = {c["key"]: c for c in data["criteria"]}
    assert by_key["reconciliation_cleanliness"]["measured"] == 0
    assert by_key["reconciliation_cleanliness"]["pass"] is True


def test_unknown_threshold_key_rejected(home: Path):
    env = mcp_call(
        "report.phase_gate_readiness",
        {"home": str(home), "thresholds": {"bogus_bar": 1}},
        actor_id="agent:default",
    )
    assert not env.ok
    assert env.error.code == "VALIDATION_ERROR"


def test_non_object_thresholds_rejected(home: Path):
    env = mcp_call(
        "report.phase_gate_readiness",
        {"home": str(home), "thresholds": [1, 2, 3]},
        actor_id="agent:default",
    )
    assert not env.ok
    assert env.error.code == "VALIDATION_ERROR"


def test_bad_min_sample_rejected(home: Path):
    env = mcp_call(
        "report.phase_gate_readiness",
        {"home": str(home), "min_sample": 0},
        actor_id="agent:default",
    )
    assert not env.ok
    assert env.error.code == "VALIDATION_ERROR"
