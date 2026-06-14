"""`report.mistakes` + `report.strengths` per trade-trace-nxn."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.reports.tag_aggregates import (
    load_mistakes_and_strengths,
    report_mistakes,
    report_strengths,
)
from trade_trace.storage.paths import db_path


class _QueryTrace:
    """Capture every SQL statement a connection executes via the sqlite
    trace callback so a test can count how many times a query ran."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, sql: str) -> None:
        self.statements.append(" ".join(sql.split()))

    def count_substr(self, needle: str) -> int:
        return sum(1 for s in self.statements if needle in s)


# The distinguishing prefix of the decision_tags→decisions→forecast_scores
# join shared by report.mistakes / report.strengths (and report.coach).
_TAG_BRIER_JOIN = "FROM decision_tags dt JOIN decisions d"


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


def _seed_tagged_decision_with_scored_forecast(
    home: Path, *, tag: str, p_yes: float
) -> None:
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": f"X-{tag}-{p_yes}",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": p_yes},
            {"outcome_label": "no", "probability": 1.0 - p_yes},
        ],
    })
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"],
        "thesis_id": thesis["data"]["id"],
        "forecast_id": f["data"]["id"],
        "type": "paper_enter", "side": "yes", "quantity": 100, "price": p_yes,
        "tags": [tag],
    })
    _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
        "confidence": 0.99,
    })


# -- registration ------------------------------------------------------


def test_mistakes_registered():
    assert "report.mistakes" in default_registry().names()


def test_strengths_registered():
    assert "report.strengths" in default_registry().names()


# -- ordering ---------------------------------------------------------


def test_mistakes_orders_by_mean_brier_descending(home):
    # "bad-pattern" → p=0.1 (very wrong on y=1, Brier=0.81)
    # "good-pattern" → p=0.9 (very right on y=1, Brier=0.01)
    _seed_tagged_decision_with_scored_forecast(home, tag="bad-pattern", p_yes=0.1)
    _seed_tagged_decision_with_scored_forecast(home, tag="good-pattern", p_yes=0.9)
    env = _envelope(home, "report.mistakes", {})
    keys = [g["key"] for g in env["data"]["groups"]]
    assert keys == ["bad-pattern", "good-pattern"]


def test_strengths_orders_by_mean_brier_ascending(home):
    _seed_tagged_decision_with_scored_forecast(home, tag="bad-pattern", p_yes=0.1)
    _seed_tagged_decision_with_scored_forecast(home, tag="good-pattern", p_yes=0.9)
    env = _envelope(home, "report.strengths", {})
    keys = [g["key"] for g in env["data"]["groups"]]
    assert keys == ["good-pattern", "bad-pattern"]


# -- drill-down record_ids -------------------------------------------


def test_groups_carry_record_ids(home):
    _seed_tagged_decision_with_scored_forecast(home, tag="pat-1", p_yes=0.5)
    env = _envelope(home, "report.mistakes", {})
    g = env["data"]["groups"][0]
    assert len(g["record_ids"]["decisions"]) == 1
    assert len(g["record_ids"]["forecasts"]) == 1


# -- empty DB -------------------------------------------------------


def test_empty_db_returns_no_groups(home):
    env = _envelope(home, "report.mistakes", {})
    assert env["data"]["groups"] == []
    assert env["data"]["summary"]["metrics"]["tag_count"] == 0


# -- AX-048: unscored tags carry no Brier evidence -------------------


def _seed_tagged_decision_unscored(home: Path, *, tag: str, p_yes: float) -> None:
    """A tagged decision whose forecast is NOT yet scored (no outcome)."""
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": f"open-{tag}",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": p_yes},
            {"outcome_label": "no", "probability": 1.0 - p_yes},
        ],
    })
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"],
        "thesis_id": thesis["data"]["id"],
        "forecast_id": f["data"]["id"],
        "type": "paper_enter", "side": "yes", "quantity": 100, "price": p_yes,
        "tags": [tag],
    })


def test_unscored_tag_excluded_from_both_reports(home):
    # One scored tag (real Brier) + one tag whose forecast is still open. The
    # open tag has no Brier to attribute, so it is neither a recurring mistake
    # nor a recurring strength and must not appear in either ranked report —
    # matching report.mistake_tripwire / report.coach, which both gate on
    # scored evidence. Before the AX-048 fix the open tag surfaced (mean_brier
    # null) in BOTH reports, contradictorily labeled mistake AND strength.
    _seed_tagged_decision_with_scored_forecast(home, tag="scored-pat", p_yes=0.5)
    _seed_tagged_decision_unscored(home, tag="open-pat", p_yes=0.5)

    for report in ("report.mistakes", "report.strengths"):
        env = _envelope(home, report, {})
        keys = [g["key"] for g in env["data"]["groups"]]
        assert keys == ["scored-pat"], (report, keys)
        assert env["data"]["summary"]["metrics"]["tag_count"] == 1
        for g in env["data"]["groups"]:
            assert g["metrics"]["mean_brier"] is not None
            assert g["metrics"]["scored_forecast_count"] >= 1


# -- sample_size basis (trade-trace-1k5d) ---------------------------


def test_group_sample_size_counts_scored_forecasts_not_decisions(home):
    # trade-trace-1k5d: group.sample_size and sample_warning must share the
    # same basis (scored forecasts). Seed two scored decisions under one tag;
    # the group must report sample_size == scored_forecast_count, and the
    # report summary sample_size must count unique scored forecasts (2), not
    # the raw join-row count.
    _seed_tagged_decision_with_scored_forecast(home, tag="shared-tag", p_yes=0.3)
    _seed_tagged_decision_with_scored_forecast(home, tag="shared-tag", p_yes=0.7)
    env = _envelope(home, "report.mistakes", {})
    groups = env["data"]["groups"]
    assert len(groups) == 1
    g = groups[0]
    assert g["sample_size"] == g["metrics"]["scored_forecast_count"]
    assert g["sample_size"] == 2
    assert env["data"]["summary"]["sample_size"] == 2


# -- single-execution (trade-trace-bg12) ----------------------------


def test_each_ranked_report_runs_the_join_exactly_once(home):
    """report.mistakes and report.strengths each execute the tag→Brier
    join exactly once per call (the public single-report path is
    unchanged by the bg12 refactor)."""

    _seed_tagged_decision_with_scored_forecast(home, tag="a", p_yes=0.2)
    _seed_tagged_decision_with_scored_forecast(home, tag="b", p_yes=0.8)

    for fn in (report_mistakes, report_strengths):
        with sqlite3.connect(db_path(home)) as conn:
            trace = _QueryTrace()
            conn.set_trace_callback(trace)
            fn(conn)
            conn.set_trace_callback(None)
        assert trace.count_substr(_TAG_BRIER_JOIN) == 1, (
            fn.__name__, trace.statements,
        )


def test_load_mistakes_and_strengths_runs_join_once_for_both_views(home):
    """`load_mistakes_and_strengths` builds BOTH ranked reports from a
    single execution of the tag→Brier join (trade-trace-bg12), and each
    returned report is byte-for-byte identical to the separate calls."""

    _seed_tagged_decision_with_scored_forecast(home, tag="bad", p_yes=0.1)
    _seed_tagged_decision_with_scored_forecast(home, tag="good", p_yes=0.9)

    with sqlite3.connect(db_path(home)) as conn:
        trace = _QueryTrace()
        conn.set_trace_callback(trace)
        mistakes, strengths = load_mistakes_and_strengths(conn)
        conn.set_trace_callback(None)

        # The join must run exactly once for the combined load even though
        # two ranked views (desc + asc) are produced from it.
        assert trace.count_substr(_TAG_BRIER_JOIN) == 1, trace.statements

        # Equivalence: the combined results match the separate public calls
        # byte-for-byte.
        ref_mistakes = report_mistakes(conn)
        ref_strengths = report_strengths(conn)

    assert mistakes == ref_mistakes
    assert strengths == ref_strengths
    # Sanity: desc vs asc orderings really are distinct.
    assert [g["key"] for g in mistakes["groups"]] == ["bad", "good"]
    assert [g["key"] for g in strengths["groups"]] == ["good", "bad"]
