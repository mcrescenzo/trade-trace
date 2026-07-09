"""`report.coach` synthesized packet per trade-trace-2g2.

Covers ux0 chunk 4 acceptance:
- Coach output forbidden phrases (positive grep gate).
- Coach never makes LLM calls or network calls.
- ≥4 tests including forbidden-phrase scan.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._direct_sql_builders import (
    insert_forecast,
    insert_forecast_outcome,
    insert_forecast_score,
    insert_instrument,
    insert_outcome,
    insert_thesis,
    insert_venue,
)
from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.reports.coach import (
    FORBIDDEN_PHRASES,
    TradingAdvicePhraseError,
    _assert_no_trade_advice,
    report_coach,
)
from trade_trace.storage.paths import db_path


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


def _seed_calibration_drift_case(home: Path) -> None:
    """Seed 20 older low-Brier rows followed by 20 recent high-Brier rows."""

    with sqlite3.connect(db_path(home)) as conn:
        insert_venue(conn, venue_id="v_drift", name="PM drift", kind="prediction_market")
        insert_instrument(
            conn,
            instrument_id="i_drift",
            venue_id="v_drift",
            title="Drift Case",
        )
        insert_thesis(conn, thesis_id="t_drift", instrument_id="i_drift")
        for idx in range(40):
            forecast_id = f"f_drift_{idx:02d}"
            outcome_id = f"o_drift_{idx:02d}"
            score_id = f"fs_drift_{idx:02d}"
            resolves_yes = idx < 20
            outcome_label = "yes" if resolves_yes else "no"
            y = 1 if resolves_yes else 0
            p_yes = 0.9
            insert_forecast(
                conn,
                forecast_id=forecast_id,
                thesis_id="t_drift",
                created_at=f"2026-05-01T00:{idx:02d}:00Z",
            )
            insert_forecast_outcome(
                conn,
                fo_id=f"fo_drift_yes_{idx:02d}",
                forecast_id=forecast_id,
                outcome_label="yes",
                probability=p_yes,
            )
            insert_forecast_outcome(
                conn,
                fo_id=f"fo_drift_no_{idx:02d}",
                forecast_id=forecast_id,
                outcome_label="no",
                probability=1.0 - p_yes,
            )
            insert_outcome(
                conn,
                outcome_id=outcome_id,
                instrument_id="i_drift",
                resolved_at=f"2026-06-01T00:{idx:02d}:00Z",
                outcome_label=outcome_label,
            )
            insert_forecast_score(
                conn,
                fs_id=score_id,
                forecast_id=forecast_id,
                outcome_id=outcome_id,
                score=(p_yes - y) ** 2,
                scored_at=f"2026-07-01T00:{idx:02d}:00Z",
            )
        conn.commit()


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
        "override_outcomes", "low_sample_context", "callouts", "next_actions",
        "is_advisory_only",
    ):
        assert key in data, f"missing coach packet field {key!r}"
    assert data["is_advisory_only"] is True
    assert data["calibration_drift"]["status"] == "insufficient_data"
    assert data["calibration_drift"]["brier_delta"] is None


def test_coach_calibration_drift_compares_recent_to_older_brier(home):
    _seed_calibration_drift_case(home)

    env = _envelope(home, "report.coach", {})
    assert env["ok"] is True
    data = env["data"]
    panel = data["calibration_drift"]
    assert panel["status"] == "comparison_available"
    assert panel["bucket"] == "recent_higher_brier"
    assert panel["sample_size"] == 40
    assert panel["min_window_sample"] == 20
    assert panel["older_window"]["sample_size"] == 20
    assert panel["older_window"]["mean_brier"] == pytest.approx(0.01)
    assert panel["older_window"]["sample_forecast_ids"] == [
        "f_drift_00", "f_drift_01", "f_drift_02", "f_drift_03", "f_drift_04",
    ]
    assert panel["recent_window"]["sample_size"] == 20
    assert panel["recent_window"]["mean_brier"] == pytest.approx(0.81)
    assert panel["brier_delta"] == pytest.approx(0.8)
    assert panel["sample_warning"] is None
    assert any("calibration_drift" in callout for callout in data["callouts"])


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
    _envelope(home, "resolution.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
        "confidence": 0.99,
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


# -- instrument-level forecast linkage (trade-trace-t9n5) ------------


def test_coach_does_not_flag_forecasted_then_skipped_market(home):
    """A market with a real forecast that was then deliberately skipped must
    NOT be flagged as 'no linked forecast' (bead trade-trace-t9n5).

    The skip decision carries no forecast_id of its own, but the instrument is
    forecasted; coach evaluates forecast linkage at the instrument level, so
    the decision_completeness 'backfill a forecast link' warning must not
    point at the skip."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    # Real forecast recorded on the market.
    _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.55},
            {"outcome_label": "no", "probability": 0.45},
        ],
    })
    # Deliberate skip for insufficient edge — carries no forecast_id of its own.
    skip = _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "skip",
        "reason": "Forecast recorded but edge too thin after costs.",
    })
    skip_id = skip["data"]["id"]

    env = _envelope(home, "report.coach", {})
    assert env["ok"] is True
    completeness = [
        a for a in env["data"]["next_actions"]
        if a["category"] == "decision_completeness"
        and "no linked forecast" in a["reason"]
    ]
    # The forecasted-then-skipped decision must not be flagged as unforecasted.
    flagged_ids = [
        did for a in completeness for did in a["record_ids"].get("decisions", [])
    ]
    assert skip_id not in flagged_ids, (
        "forecasted-then-skipped decision was wrongly flagged as unforecasted"
    )


def test_coach_still_flags_decision_on_unforecasted_instrument(home):
    """The instrument-level check must not silence the warning entirely: a
    decision on a market with NO forecast at all is still legitimately flagged
    (bead trade-trace-t9n5 keeps the true positive)."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "Y",
    })
    # No forecast on this instrument at all.
    skip = _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "skip",
        "reason": "Out of scope; no forecast recorded.",
    })
    skip_id = skip["data"]["id"]

    env = _envelope(home, "report.coach", {})
    assert env["ok"] is True
    flagged_ids = [
        did
        for a in env["data"]["next_actions"]
        if a["category"] == "decision_completeness"
        and "no linked forecast" in a["reason"]
        for did in a["record_ids"].get("decisions", [])
    ]
    assert skip_id in flagged_ids, (
        "decision on a genuinely unforecasted instrument should still be flagged"
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
    assert any(a["category"] == "unresolved_forecasts" for a in data["next_actions"])


def test_coach_low_sample_separates_caveat_from_process_actions(home):
    """N=1 remains explicitly insufficient while process gaps are actionable."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    forecast = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"],
        "forecast_id": forecast["data"]["id"],
        "thesis_id": thesis["data"]["id"],
        "type": "paper_enter", "side": "yes", "quantity": 1, "price": 0.6,
    })
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "watch",
        "reason": "needs a dated revisit",
    })
    _envelope(home, "resolution.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
        "confidence": 0.99,
    })

    env = _envelope(home, "report.coach", {})
    assert env["ok"] is True
    data = env["data"]
    assert data["low_sample_context"]["scored_forecast_count"] == 1
    assert "Insufficient calibration sample" in data["low_sample_context"]["statistical_caveat"]
    categories = {a["category"] for a in data["next_actions"]}
    assert "calibration_data" in categories
    assert "watch_review" in categories
    assert "decision_completeness" in categories
    assert "reflection_hygiene" in categories
    assert not any("infer skill" in a["action"] and a["category"] != "calibration_data"
                   for a in data["next_actions"])


# -- single-execution of the tag→Brier join (trade-trace-bg12) -------


class _QueryTrace:
    """Capture every SQL statement a connection executes via the sqlite
    trace callback so a test can count how many times a query ran."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, sql: str) -> None:
        self.statements.append(" ".join(sql.split()))

    def count_substr(self, needle: str) -> int:
        return sum(1 for s in self.statements if needle in s)


# Distinguishing prefix of the decision_tags→decisions→forecast_scores join
# that report.mistakes and the coach strengths view share. This substring
# isolates the ranked-report query the coach consumes.
_TAG_BRIER_JOIN = "FROM decision_tags dt JOIN decisions d ON d.id = dt.decision_id LEFT JOIN forecast_scores"


def test_coach_runs_tag_brier_join_exactly_once(home):
    """report.coach builds mistake and strength tag views from one query."""

    _seed = _envelope  # local alias for brevity below
    venue = _seed(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _seed(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    thesis = _seed(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    f = _seed(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    _seed(home, "decision.add", {
        "instrument_id": inst["data"]["id"],
        "forecast_id": f["data"]["id"],
        "thesis_id": thesis["data"]["id"],
        "type": "paper_enter", "side": "yes", "quantity": 100, "price": 0.6,
        "tags": ["pattern-a"],
    })
    _seed(home, "resolution.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
        "confidence": 0.99,
    })

    with sqlite3.connect(db_path(home)) as conn:
        trace = _QueryTrace()
        conn.set_trace_callback(trace)
        report_coach(conn)
        conn.set_trace_callback(None)

    assert trace.count_substr(_TAG_BRIER_JOIN) == 1, [
        s for s in trace.statements if "decision_tags" in s
    ]
