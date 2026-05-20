"""`report.coach` synthesized packet per trade-trace-2g2.

Covers ux0 chunk 4 acceptance:
- Coach output forbidden phrases (positive grep gate).
- Coach never makes LLM calls or network calls.
- ≥4 tests including forbidden-phrase scan.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.reports.coach import (
    FORBIDDEN_PHRASES,
    TradingAdvicePhraseError,
    _assert_no_trade_advice,
)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


# -- registration --------------------------------------------------------


def test_coach_registered():
    assert "report.coach" in default_registry().names()


# -- envelope shape ---------------------------------------------------


def test_coach_empty_db_returns_advisory_packet(home):
    env = _envelope(home, "report.coach", {})
    assert env["ok"] is True
    data = env["data"]
    for key in (
        "filter", "top_mistakes", "top_strengths", "unscored_forecasts",
        "stale_watches", "sample_warnings", "calibration_drift",
        "override_outcomes", "callouts", "is_advisory_only",
    ):
        assert key in data, f"missing coach packet field {key!r}"
    assert data["is_advisory_only"] is True


# -- forbidden-phrase scan --------------------------------------------


def test_coach_output_contains_no_forbidden_phrases_on_empty_db(home):
    env = _envelope(home, "report.coach", {})
    serialized = json.dumps(env["data"], sort_keys=True).lower()
    import re

    pattern = re.compile(
        r"\b(" + "|".join(re.escape(p) for p in FORBIDDEN_PHRASES) + r")\b",
        re.IGNORECASE,
    )
    matches = pattern.findall(serialized)
    assert matches == [], (
        f"coach packet contains forbidden trade-advice phrase(s): {matches}"
    )


def test_coach_packet_with_data_remains_clean(home):
    """Real data flowing through the packet still produces a clean output."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"],
        "forecast_id": f["data"]["id"],
        "thesis_id": thesis["data"]["id"],
        "type": "paper_enter", "side": "yes", "quantity": 100, "price": 0.6,
        "tags": ["pattern-a"],
    })
    _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
    })

    env = _envelope(home, "report.coach", {})
    assert env["ok"] is True
    import re

    serialized = json.dumps(env["data"]).lower()
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(p) for p in FORBIDDEN_PHRASES) + r")\b",
        re.IGNORECASE,
    )
    assert pattern.findall(serialized) == []


def test_assert_no_trade_advice_raises_on_violation():
    """Direct unit test on the gate: a hand-crafted packet with a forbidden
    phrase trips the runtime check."""

    packet = {"callouts": ["this looks profitable to me"]}
    with pytest.raises(TradingAdvicePhraseError) as exc:
        _assert_no_trade_advice(packet)
    assert "profitable" in exc.value.matches


def test_assert_no_trade_advice_catches_every_documented_phrase():
    for phrase in FORBIDDEN_PHRASES:
        with pytest.raises(TradingAdvicePhraseError):
            _assert_no_trade_advice({"text": f"please {phrase} this position"})


def test_forbidden_phrases_pinned():
    """The forbidden set is part of the contract; pin it so a future edit
    surfaces in code review."""

    assert FORBIDDEN_PHRASES == (
        "buy", "sell", "profitable", "recommended trade", "long", "short",
    )


# -- no LLM / no network: positive grep gate ------------------------


def test_coach_source_contains_no_network_or_llm_primitives():
    """The coach implementation must not import LLM SDKs or open network
    connections. Positive grep gate over the coach module."""

    src = Path(__file__).resolve().parents[2] / "src" / "trade_trace" / "reports" / "coach.py"
    text = src.read_text(encoding="utf-8")
    forbidden = [
        "import openai", "import anthropic", "from openai", "from anthropic",
        "httpx", "requests.", "urllib", "socket.", "urlopen", "websocket",
    ]
    offenders = [needle for needle in forbidden if needle in text]
    assert offenders == [], (
        f"coach module imports forbidden network/LLM primitive(s): {offenders}"
    )


# -- aggregation surfaces ------------------------------------------


def test_coach_surfaces_unscored_callout(home):
    """When there's a pending forecast past resolution_at, the coach emits a
    callout pointing to it."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "resolution_at": "2026-04-01T00:00:00Z",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.5},
            {"outcome_label": "no", "probability": 0.5},
        ],
    })
    env = _envelope(home, "report.coach", {})
    data = env["data"]
    assert data["unscored_forecasts"]["count"] == 1
    assert any("pending forecast" in c for c in data["callouts"])
