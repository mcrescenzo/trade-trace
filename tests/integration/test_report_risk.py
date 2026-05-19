"""risk-unit write surface + report.risk per trade-trace-8z2."""

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


def _instrument(home: Path, title: str = "R") -> str:
    """Seed venue + instrument + thesis and return the instrument id.
    A thesis is needed because actual_enter decisions require thesis_id
    per PRD §3.1; the tests below use that decision type so the seed
    creates the thesis up-front rather than per-call."""

    venue = _env(home, "venue.add", {"name": f"PM-{title}", "kind": "prediction_market"})
    inst = _env(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": title,
    })
    instrument_id = inst["data"]["id"]
    _env(home, "thesis.add", {
        "instrument_id": instrument_id,
        "side": "long",
        "body": f"test thesis for {title}",
    })
    return instrument_id


def _closed_position(home: Path, instrument_id: str, realized_pnl: float, status: str = "closed") -> None:
    db = open_database(db_path(home))
    try:
        with db.transaction():
            db.connection.execute(
                "INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, "
                "closed_at, resolved_at, realized_pnl, unrealized_pnl, avg_entry_price, updated_at) "
                "VALUES (?, ?, 'paper', 'long', ?, '2026-05-18T14:00:00Z', "
                "'2026-05-18T16:00:00Z', NULL, ?, NULL, 0.40, '2026-05-18T16:00:00Z')",
                (new_id("pos"), instrument_id, status, realized_pnl),
            )
    finally:
        db.close()


def test_report_risk_registered():
    assert "report.risk" in default_registry().names()


def test_decision_add_persists_all_risk_fields(home):
    inst = _instrument(home)
    env = _env(home, "decision.add", {
        "type": "add", "instrument_id": inst, "side": "long",
        "quantity": 10, "price": 2.0, "declared_risk_amount": "100",
        "declared_risk_unit": "USD", "expected_edge": "1.25",
        "expected_edge_after_costs": "1.0", "cost_basis_estimate": "20.5",
        "risk_reward_estimate": "2.5",
    })
    assert env["ok"], env
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT declared_risk_amount, declared_risk_unit, expected_edge, "
            "expected_edge_after_costs, cost_basis_estimate, risk_reward_estimate "
            "FROM decisions WHERE id = ?",
            (env["data"]["id"],),
        ).fetchone()
    finally:
        db.close()
    assert tuple(row) == (100.0, "USD", 1.25, 1.0, 20.5, 2.5)


@pytest.mark.parametrize("bad_args,field", [
    ({"declared_risk_amount": -1}, "declared_risk_amount"),
    ({"declared_risk_amount": "abc"}, "declared_risk_amount"),
    ({"expected_edge": 0.5, "expected_edge_after_costs": 0.6}, "expected_edge_after_costs"),
])
def test_invalid_risk_fields_return_validation_error(home, bad_args, field):
    inst = _instrument(home, field)
    env = _env(home, "decision.add", {
        "type": "add", "instrument_id": inst, "side": "long",
        "quantity": 1, "price": 1.0, **bad_args,
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == field
    assert "sqlite_error" not in env["error"].get("details", {})


def test_report_risk_aggregates_r_and_missing_caveats_and_pnl_still_works(home):
    inst_win = _instrument(home, "win")
    inst_loss = _instrument(home, "loss")
    inst_missing = _instrument(home, "missing")
    inst_pending = _instrument(home, "pending")

    _env(home, "decision.add", {"type": "add", "instrument_id": inst_win, "side": "long", "quantity": 1, "price": 1, "declared_risk_amount": 100})
    _env(home, "decision.add", {"type": "add", "instrument_id": inst_loss, "side": "long", "quantity": 1, "price": 1, "declared_risk_amount": 50})
    _env(home, "decision.add", {"type": "add", "instrument_id": inst_missing, "side": "long", "quantity": 1, "price": 1})
    _env(home, "decision.add", {"type": "add", "instrument_id": inst_pending, "side": "long", "quantity": 1, "price": 1, "declared_risk_amount": 25})
    _closed_position(home, inst_win, 250.0)
    _closed_position(home, inst_loss, -25.0)
    _closed_position(home, inst_missing, 10.0)

    risk = _env(home, "report.risk", {})
    assert risk["ok"], risk
    metrics = risk["data"]["summary"]["metrics"]
    assert metrics["n_closed_with_risk"] == 2
    assert metrics["n_closed_total"] == 3
    assert metrics["mean_r"] == pytest.approx(1.0)
    assert metrics["median_r"] == pytest.approx(1.0)
    assert metrics["expectancy_r"] == pytest.approx(1.0)
    assert metrics["win_rate_r"] == pytest.approx(0.5)
    assert metrics["payoff_ratio_r"] == pytest.approx(5.0)
    assert risk["data"]["summary"]["missing_risk_count"] == 1
    assert risk["data"]["summary"]["pending_risk_count"] == 1
    assert any("missing declared_risk_amount" in c for c in risk["data"]["summary"]["caveats"])

    pnl = _env(home, "report.pnl", {})
    assert pnl["ok"], pnl
    assert pnl["data"]["summary"]["metrics"]["realized_pnl"] == pytest.approx(235.0)


def test_report_risk_rejects_unsupported_filters_cleanly(home):
    env = _env(home, "report.risk", {"filter": {"decision": {"decision_type": ["actual_enter"]}}})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert "unsupported_filter_paths" in env["error"]["details"]
