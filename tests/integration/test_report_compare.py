"""report.compare and report.strategy_performance (trade-trace-4md)."""

from __future__ import annotations

from pathlib import Path

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _env(home: Path, tool: str, args: dict):
    return mcp_call(tool, {"home": str(home), **args}, actor_id="agent:default").model_dump(
        mode="json", exclude_none=True
    )


def _seed_positions(home: Path) -> None:
    v = _env(home, "venue.add", {"name": "Compare PM", "kind": "prediction_market"})["data"]["id"]
    i1 = _env(home, "instrument.add", {"venue_id": v, "asset_class": "prediction_market", "title": "A"})["data"]["id"]
    i2 = _env(home, "instrument.add", {"venue_id": v, "asset_class": "prediction_market", "title": "B"})["data"]["id"]
    db = open_database(db_path(home))
    try:
        with db.transaction():
            for pos_id, instr, status, realized, unrealized in [
                ("pos_b", i1, "closed", 2.0, None),
                ("pos_a", i2, "closed", 1.0, None),
                ("pos_c", i2, "open", None, 0.5),
            ]:
                db.connection.execute(
                    "INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, closed_at, resolved_at, realized_pnl, unrealized_pnl, avg_entry_price, updated_at) "
                    "VALUES (?, ?, 'paper', 'long', ?, '2026-05-18T00:00:00Z', NULL, NULL, ?, ?, 1.0, '2026-05-18T01:00:00Z')",
                    (pos_id, instr, status, realized, unrealized),
                )
    finally:
        db.close()


def test_compare_and_strategy_performance_registered():
    names = default_registry().names()
    assert "report.compare" in names
    assert "report.strategy_performance" in names


def test_compare_pnl_grouping_stable_order_and_sample_warning(home):
    _seed_positions(home)
    first = _env(home, "report.compare", {"base_report": "pnl", "group_by": "status"})
    second = _env(home, "report.compare", {"base_report": "pnl", "group_by": "status"})
    assert first["ok"], first
    groups = first["data"]["groups"]
    assert [g["key"] for g in groups] == ["closed", "open"]
    assert [g["key"] for g in groups] == [g["key"] for g in second["data"]["groups"]]
    closed = groups[0]
    assert closed["metrics"]["closed_count"] == 2
    assert closed["sample_warning"] == "only 2 closed positions; pnl trend is unreliable below 5"
    assert first["data"]["summary"]["sample_warning"] == "one_or_more_groups_below_min_sample"


def test_compare_rejects_injected_group_by(home):
    env = _env(home, "report.compare", {"base_report": "pnl", "group_by": "status; DROP TABLE positions"})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_strategy_performance_wrapper_no_strategy_edge(home):
    _seed_positions(home)
    env = _env(home, "report.strategy_performance", {})
    assert env["ok"], env
    assert env["data"]["summary"]["base_report"] == "pnl"
    assert env["data"]["summary"]["group_by"] == "strategy_id"
    assert [g["key"] for g in env["data"]["groups"]] == ["__none__"]
    assert env["data"]["groups"][0]["metrics"]["closed_count"] == 2


def test_strategy_performance_single_strategy_absent_is_empty(home):
    _seed_positions(home)
    env = _env(home, "report.strategy_performance", {"strategy_id": "strat_missing"})
    assert env["ok"], env
    assert env["data"]["groups"] == []
    assert env["data"]["summary"]["sample_size"] == 0


# -- documented group_by matches runtime (trade-trace-cs0r) -----------


def test_documented_group_by_matches_runtime_support():
    """Per trade-trace-cs0r: `DOCUMENTED_GROUP_BY` must equal the union
    of the per-base-report runtime allowlists. Adding a value to the
    docs without wiring the SQL mapping silently breaks agents."""

    from trade_trace.reports.compare import (
        CALIBRATION_GROUP_SQL,
        DOCUMENTED_GROUP_BY,
        PNL_GROUP_SQL,
        SUPPORTED_GROUP_BY_BY_BASE_REPORT,
    )

    assert DOCUMENTED_GROUP_BY == set(CALIBRATION_GROUP_SQL) | set(PNL_GROUP_SQL)
    assert SUPPORTED_GROUP_BY_BY_BASE_REPORT == {
        "calibration": set(CALIBRATION_GROUP_SQL),
        "pnl": set(PNL_GROUP_SQL),
    }
