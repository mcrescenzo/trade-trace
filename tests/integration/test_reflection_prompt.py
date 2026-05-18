"""reflection.prompt_for_outcome determinism + structure per bead wnj."""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _mcp(home: Path, tool: str, args: dict | None = None):
    payload = {"home": str(home), **(args or {})}
    return mcp_call(tool, payload, actor_id="agent:default")


def _seed_resolved_forecast(home: Path) -> str:
    venue = _mcp(home, "venue.add",
                 {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": "X",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes",
        "body": "Earnings beat by 5%+ on AI demand.",
    }).data["id"]
    _mcp(home, "forecast.add", {
        "thesis_id": thesis, "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    outcome = _mcp(home, "outcome.add", {
        "instrument_id": inst,
        "resolved_at": "2026-05-22T20:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
        "idempotency_key": "00000000-0000-4000-8000-wnj-outc-1",
    }).data["id"]
    return outcome


def test_reflection_prompt_registered():
    assert "reflection.prompt_for_outcome" in default_registry().names()


def test_packet_is_byte_deterministic(home):
    """Three calls with the same inputs and same DB state must produce
    byte-identical JSON output (packet_sha256 stable)."""

    outcome = _seed_resolved_forecast(home)
    hashes: set[str] = set()
    for _ in range(3):
        env = _mcp(home, "reflection.prompt_for_outcome", {
            "outcome_id": outcome,
            "include_forecast": True,
            "include_thesis": True,
            "include_prior_reflections": True,
        })
        assert env.ok, env
        hashes.add(env.data["packet_sha256"])
    assert len(hashes) == 1, (
        f"packet_sha256 changed across runs; got {hashes}"
    )


def test_packet_structure_matches_flag_combinations(home):
    outcome = _seed_resolved_forecast(home)

    # all flags on
    full = _mcp(home, "reflection.prompt_for_outcome", {
        "outcome_id": outcome,
    }).data
    assert full["forecast"] is not None
    assert full["thesis"] is not None
    assert isinstance(full["prior_reflections"], list)

    # forecast only
    fc_only = _mcp(home, "reflection.prompt_for_outcome", {
        "outcome_id": outcome,
        "include_forecast": True,
        "include_thesis": False,
        "include_prior_reflections": False,
    }).data
    assert fc_only["forecast"] is not None
    assert fc_only["thesis"] is None
    assert fc_only["prior_reflections"] == []

    # thesis only
    th_only = _mcp(home, "reflection.prompt_for_outcome", {
        "outcome_id": outcome,
        "include_forecast": False,
        "include_thesis": True,
        "include_prior_reflections": False,
    }).data
    assert th_only["forecast"] is None
    assert th_only["thesis"] is not None


def test_packet_includes_calibration_delta(home):
    outcome = _seed_resolved_forecast(home)
    packet = _mcp(home, "reflection.prompt_for_outcome", {
        "outcome_id": outcome,
    }).data
    # p_predicted=0.6 on YES, outcome=YES → delta = |1.0 - 0.6| = 0.4
    assert packet["calibration_delta"] == pytest.approx(0.4)


def test_missing_outcome_returns_not_found(home):
    env = _mcp(home, "reflection.prompt_for_outcome", {
        "outcome_id": "o_does_not_exist",
    })
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details["entity_kind"] == "outcome"


def test_prior_reflections_respect_as_of_filter(home):
    outcome = _seed_resolved_forecast(home)
    # Write a reflection on the outcome AFTER the as_of in the packet.
    _mcp(home, "memory.reflect", {
        "target_kind": "outcome", "target_id": outcome,
        "body": "Future reflection",
        "idempotency_key": "00000000-0000-4000-8000-wnj-refl-fut",
    })
    # Past as_of should exclude this reflection (created today).
    env = _mcp(home, "reflection.prompt_for_outcome", {
        "outcome_id": outcome,
        "as_of": "2020-01-01T00:00:00Z",
    })
    assert env.ok
    assert env.data["prior_reflections"] == []
