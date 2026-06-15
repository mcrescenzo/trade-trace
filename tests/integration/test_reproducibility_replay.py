"""Deterministic-replay tests per bead trade-trace-64q.

Each test invokes one read tool three times against an identical
fixture under a frozen clock; the canonicalized JSON envelope must hash
to the same SHA-256 across all three invocations.

Canonicalization strips known non-deterministic transport metadata
(`request_id`, `recall_id`, `event_id`) before hashing. The bead's
acceptance phrase 'canonicalized JSON' covers this — what's tested is
the *semantic* envelope content, not the transport framing.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.tools._helpers import CLOCK_OVERRIDE

_FROZEN = datetime(2026, 5, 18, 14, 0, 0, tzinfo=UTC)


@pytest.fixture
def frozen_clock():
    token = CLOCK_OVERRIDE.set(_FROZEN)
    try:
        yield _FROZEN
    finally:
        CLOCK_OVERRIDE.reset(token)


@pytest.fixture
def populated_home(tmp_path, frozen_clock):
    """Build a deterministic fixture under the frozen clock."""

    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    venue = mcp_call("venue.add", {
        "home": str(h), "name": "PM", "kind": "prediction_market",
        "idempotency_key": "00000000-0000-4000-8000-rep-v-1",
    }).data["id"]
    inst = mcp_call("instrument.add", {
        "home": str(h), "venue_id": venue,
        "asset_class": "prediction_market", "title": "X",
        "idempotency_key": "00000000-0000-4000-8000-rep-i-1",
    }).data["id"]
    thesis = mcp_call("thesis.add", {
        "home": str(h), "instrument_id": inst,
        "side": "yes", "body": "thesis body for repro",
        "idempotency_key": "00000000-0000-4000-8000-rep-t-1",
    }).data["id"]
    mcp_call("forecast.add", {
        "home": str(h), "thesis_id": thesis, "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
        "idempotency_key": "00000000-0000-4000-8000-rep-f-1",
    })
    mcp_call("decision.add", {
        "home": str(h), "type": "actual_enter", "instrument_id": inst,
        "thesis_id": thesis, "side": "yes",
        "quantity": 1, "price": 0.5, "tags": ["repro-test"],
        "idempotency_key": "00000000-0000-4000-8000-rep-d-1",
    })
    mcp_call("resolution.add", {
        "home": str(h), "instrument_id": inst,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
        "idempotency_key": "00000000-0000-4000-8000-rep-o-1",
    })
    mcp_call("memory.retain", {
        "home": str(h), "node_type": "observation",
        "body": "Memory body for deterministic recall",
        "idempotency_key": "00000000-0000-4000-8000-rep-m-1",
    })
    return h


# -- canonicalization ----------------------------------------


_TRANSPORT_KEYS = {"request_id", "event_id", "recall_id"}


def _canonicalize(body: dict) -> str:
    """Strip transport-metadata keys at any depth and return sorted-key
    JSON for hashing."""

    def _strip(value):
        if isinstance(value, dict):
            return {k: _strip(v) for k, v in value.items()
                    if k not in _TRANSPORT_KEYS}
        if isinstance(value, list):
            return [_strip(v) for v in value]
        return value

    return json.dumps(_strip(body), sort_keys=True)


def _hash(env_dict: dict) -> str:
    return hashlib.sha256(_canonicalize(env_dict).encode("utf-8")).hexdigest()


def _three_call_hashes(home: Path, tool: str, args: dict) -> set[str]:
    """Invoke `tool` three times against `home` and return the set of
    canonical-JSON hashes. Determinism passes when the set has 1 entry."""

    payload = {"home": str(home), **args}
    hashes: set[str] = set()
    for _ in range(3):
        env = mcp_call(tool, payload, actor_id="agent:default")
        hashes.add(_hash(env.model_dump(mode="json", exclude_none=False)))
    return hashes


# -- 8 read-tool determinism tests --------------------------


def test_report_calibration_replay_deterministic(populated_home):
    hashes = _three_call_hashes(populated_home, "report.calibration", {})
    assert len(hashes) == 1, f"non-deterministic: {hashes}"


def test_report_mistakes_replay_deterministic(populated_home):
    hashes = _three_call_hashes(populated_home, "report.mistakes", {})
    assert len(hashes) == 1


def test_report_strengths_replay_deterministic(populated_home):
    hashes = _three_call_hashes(populated_home, "report.strengths", {})
    assert len(hashes) == 1


def test_report_pnl_replay_deterministic(populated_home):
    hashes = _three_call_hashes(populated_home, "report.pnl", {})
    assert len(hashes) == 1


def test_report_watchlist_replay_deterministic(populated_home):
    hashes = _three_call_hashes(populated_home, "report.watchlist", {})
    assert len(hashes) == 1


def test_report_unscored_forecasts_replay_deterministic(populated_home):
    hashes = _three_call_hashes(populated_home, "report.unscored_forecasts", {})
    assert len(hashes) == 1


def test_report_playbook_adherence_replay_deterministic(populated_home):
    hashes = _three_call_hashes(populated_home, "report.playbook_adherence", {})
    assert len(hashes) == 1


def test_report_decision_velocity_replay_deterministic(populated_home):
    hashes = _three_call_hashes(populated_home, "report.decision_velocity", {})
    assert len(hashes) == 1


# -- memory.recall per-strategy determinism -----------------


@pytest.mark.parametrize("strategy", ["bm25", "temporal", "graph"])
def test_memory_recall_per_strategy_deterministic(populated_home, strategy):
    """Each retrieval strategy independently produces the same envelope
    across runs under the frozen clock."""

    hashes = _three_call_hashes(populated_home, "memory.recall", {
        "query": "memory body", "k": 5, "strategies": [strategy],
    })
    assert len(hashes) == 1, f"non-deterministic on {strategy}: {hashes}"


def test_memory_recall_fused_deterministic(populated_home):
    hashes = _three_call_hashes(populated_home, "memory.recall", {
        "query": "memory body", "k": 5,
    })
    assert len(hashes) == 1


# -- meta-field presence checks ------------------------------


def test_report_meta_carries_reproducibility_fields(populated_home):
    env = mcp_call("report.calibration", {
        "home": str(populated_home),
    }, actor_id="agent:default")
    assert env.ok
    assert env.meta.generated_at is not None
    assert env.meta.package_version is not None
    assert env.meta.normalized_filter is not None


def test_recall_meta_carries_retrieval_strategy_metadata(populated_home):
    env = mcp_call("memory.recall", {
        "home": str(populated_home), "query": "memory", "k": 3,
    }, actor_id="agent:default")
    assert env.ok
    md = env.meta.retrieval_strategy_metadata
    assert md is not None
    assert md["k"] == 3
    assert md["k_rrf"] == 60
    assert md["importance_boost_slope"] == 0.05
    assert md["supersession_discount"] == 0.25
    assert set(md["strategies_used"]) >= {"bm25", "temporal", "graph"}


# -- clock injection contract --------------------------------


def test_clock_injection_freezes_now_iso():
    """When CLOCK_OVERRIDE is set, now_iso() returns the override's
    ISO8601 form. Without override, it returns the system time."""

    from trade_trace.tools._helpers import now_iso

    fixed = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
    token = CLOCK_OVERRIDE.set(fixed)
    try:
        assert now_iso() == "2030-01-01T12:00:00.000Z"
    finally:
        CLOCK_OVERRIDE.reset(token)

    # After reset, now_iso() reverts to the system clock — confirmed by
    # the timestamp NOT being the frozen one.
    assert now_iso() != "2030-01-01T12:00:00.000Z"
