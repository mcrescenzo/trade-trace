"""Synthetic path-series coverage for report.opportunity (trade-trace-6z5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path
from trade_trace.tools._helpers import new_id


def _env(home: Path, tool: str, args: dict):
    return mcp_call(tool, {"home": str(home), **args}, actor_id="agent:default").model_dump(
        mode="json", exclude_none=True,
    )


@pytest.fixture
def home(initialized_home):
    """Alias to the shared `initialized_home` fixture in
    `tests/conftest.py` (trade-trace-qs5v / SIMP-008)."""

    return initialized_home


def _instrument(home: Path, title: str) -> str:
    venue = _env(home, "venue.add", {"name": f"Venue-{title}", "kind": "prediction_market"})
    inst = _env(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": title,
    })
    return inst["data"]["id"]


def _seed_decision_path(
    home: Path,
    *,
    title: str,
    decision_type: str,
    side: str = "long",
    decision_price: float = 1.0,
    risk: float | None = None,
    realized_pnl: float | None = None,
    outcome_value: float | None = None,
    snapshots: list[tuple[str, float]] | None = None,
) -> str:
    inst = _instrument(home, title)
    thesis_id = new_id("thesis")
    decision_id = new_id("decision")
    outcome_id = new_id("outcome")
    conn = open_database(db_path(home), create_parent=False).connection
    try:
        with conn:
            conn.execute(
                "INSERT INTO theses(id, instrument_id, side, body, time_horizon_at, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, '2026-01-03T00:00:00Z', '2026-01-01T00:00:00Z', 'agent:default')",
                (thesis_id, inst, side, f"thesis {title}"),
            )
            conn.execute(
                "INSERT INTO decisions(id, instrument_id, thesis_id, type, side, quantity, price, "
                "declared_risk_amount, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?, '2026-01-01T00:00:00Z', 'agent:default')",
                (decision_id, inst, thesis_id, decision_type, side, decision_price, risk),
            )
            if outcome_value is not None:
                conn.execute(
                    "INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, outcome_value, "
                    "status, created_at, actor_id) VALUES (?, ?, '2026-01-03T00:00:00Z', 'yes', ?, "
                    "'resolved_final', '2026-01-03T00:00:00Z', 'agent:default')",
                    (outcome_id, inst, outcome_value),
                )
            if realized_pnl is not None:
                conn.execute(
                    "INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, closed_at, "
                    "realized_pnl, avg_entry_price, updated_at) VALUES (?, ?, 'paper', ?, 'closed', "
                    "'2026-01-01T00:00:00Z', '2026-01-03T00:00:00Z', ?, ?, '2026-01-03T00:00:00Z')",
                    (new_id("pos"), inst, side, realized_pnl, decision_price),
                )
            for captured_at, price in (snapshots or []):
                conn.execute(
                    "INSERT INTO snapshots(id, instrument_id, captured_at, price, mid, created_at, actor_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'agent:default')",
                    (new_id("snap"), inst, captured_at, price, price, captured_at),
                )
    finally:
        conn.close()
    return decision_id


def _report(home: Path, **args):
    env = _env(home, "report.opportunity", args)
    assert env["ok"], env
    return env["data"]


def _record(data: dict, decision_id: str) -> dict:
    return next(r for r in data["records"] if r["decision_id"] == decision_id)


def test_report_opportunity_registered():
    assert "report.opportunity" in default_registry().names()


def test_favorable_skip_classifies_missed_positive_edge(home):
    decision_id = _seed_decision_path(
        home,
        title="favorable-skip",
        decision_type="skip",
        snapshots=[
            ("2026-01-01T06:00:00Z", 1.02),
            ("2026-01-01T12:00:00Z", 1.09),
            ("2026-01-01T18:00:00Z", 1.04),
            ("2026-01-02T00:00:00Z", 1.08),
            ("2026-01-02T12:00:00Z", 1.10),
            ("2026-01-03T00:00:00Z", 1.07),
        ],
    )
    data = _report(home)
    rec = _record(data, decision_id)
    assert rec["data_coverage"] == "complete"
    assert "missed_positive_edge" in rec["classification_labels"]
    assert rec["metrics"]["max_favorable_move"]["value"] == pytest.approx(0.10)
    assert "missed_positive_edge" in data["summary"]["buckets"]


def test_adverse_then_final_win_classifies_wrong_timing_and_good_outcome(home):
    decision_id = _seed_decision_path(
        home,
        title="adverse-win",
        decision_type="actual_enter",
        risk=0.10,
        realized_pnl=0.15,
        outcome_value=1.0,
        snapshots=[
            ("2026-01-01T06:00:00Z", 0.88),
            ("2026-01-01T12:00:00Z", 0.92),
            ("2026-01-02T00:00:00Z", 1.12),
            ("2026-01-02T12:00:00Z", 1.20),
            ("2026-01-03T00:00:00Z", 1.15),
        ],
    )
    rec = _record(_report(home), decision_id)
    assert rec["metrics"]["max_adverse_move"]["price_delta"] == pytest.approx(0.12)
    assert "right_thesis_wrong_timing" in rec["classification_labels"]
    assert "bad_process_good_outcome" in rec["classification_labels"]


def test_noisy_unfavorable_skip_classifies_good_skip(home):
    decision_id = _seed_decision_path(
        home,
        title="noisy-down",
        decision_type="watch",
        snapshots=[
            ("2026-01-01T06:00:00Z", 0.99),
            ("2026-01-01T12:00:00Z", 0.96),
            ("2026-01-02T00:00:00Z", 1.01),
            ("2026-01-02T12:00:00Z", 0.94),
            ("2026-01-03T00:00:00Z", 0.97),
        ],
    )
    rec = _record(_report(home), decision_id)
    assert "good_skip" in rec["classification_labels"]
    assert rec["metrics"]["max_adverse_move"]["value"] == pytest.approx(0.06)


def test_sparse_and_missing_snapshot_caveats(home):
    sparse_id = _seed_decision_path(
        home,
        title="sparse",
        decision_type="skip",
        snapshots=[("2026-01-01T01:00:00Z", 1.08)],
    )
    missing_id = _seed_decision_path(home, title="missing", decision_type="skip")

    data = _report(home)
    sparse = _record(data, sparse_id)
    missing = _record(data, missing_id)
    assert sparse["data_coverage"] == "sparse"
    assert any("sparse" in c for c in sparse["caveats"])
    assert missing["data_coverage"] == "missing"
    assert missing["metrics"]["max_favorable_move"]["value"] is None
    assert any("no post-decision snapshots" in c for c in missing["caveats"])
    assert data["summary"]["metrics"]["missing_snapshot_count"] == 1
    assert data["summary"]["metrics"]["sparse_snapshot_count"] == 1


def test_report_opportunity_rejects_unsupported_filters_cleanly(home):
    env = _env(home, "report.opportunity", {"filter": {"decision": {"decision_type": ["skip"]}}})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["report"] == "report.opportunity"
    assert "decision.decision_type" in env["error"]["details"]["unsupported_filter_paths"]
