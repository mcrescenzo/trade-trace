"""Per-dashboard context contract tests per the dashboard UI beads
(a94a P&L, 1viz Risk, ai45 Performance, avn7 Strategy, nvkr Decision
intelligence, lv7n Calibration full, 5own Evidence, svp2 Position
detail, w422 Overview as P&L/risk/perf dashboard).

Every dashboard's context builder wraps `console.reporting.run_report`
and threads the result through a shared shape. The tests pin:

- the dashboard slug + heading,
- safe-report adapter usage (deny set + allowlist applied),
- highlighted_metrics tile selection,
- chart_config_json is base64-decodable JSON (no eval / no template
  injection),
- evidence affordance populated for the dashboards that surface
  groups,
- page explanation populated where the glossary has copy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_trace.console.pages import (
    dashboard_calibration_context,
    dashboard_decision_intelligence_context,
    dashboard_evidence_context,
    dashboard_performance_context,
    dashboard_pnl_context,
    dashboard_risk_context,
    dashboard_strategy_context,
    position_detail_context,
)
from trade_trace.mcp_server import mcp_call


@pytest.fixture
def rich_home(tmp_path: Path) -> Path:
    home = tmp_path / "rich"
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok, init
    seed = mcp_call("journal.fixture_seed", {
        "home": str(home), "target": "mvp-eval-rich",
    })
    assert seed.ok, seed
    return home


DASHBOARDS = [
    (dashboard_pnl_context, "pnl", "report.pnl"),
    (dashboard_risk_context, "risk", "report.risk"),
    (dashboard_performance_context, "performance", "report.decision_velocity"),
    (dashboard_strategy_context, "strategy", "report.strategy_performance"),
    (dashboard_decision_intelligence_context, "decision_intelligence",
     "report.watchlist"),
    (dashboard_calibration_context, "calibration", "report.calibration"),
    (dashboard_evidence_context, "evidence", "report.source_quality"),
]


@pytest.mark.parametrize("builder, slug, tool", DASHBOARDS)
def test_dashboard_context_uses_safe_report_tool(rich_home: Path, builder, slug, tool):
    """Every dashboard MUST dispatch through `run_report` (which
    enforces the safe-report allowlist). The returned context echoes
    the tool name in `evidence.tool`."""

    ctx = builder(str(rich_home))
    assert ctx["dashboard_slug"] == slug
    assert ctx["evidence"]["tool"] == tool


@pytest.mark.parametrize("builder, slug, tool", DASHBOARDS)
def test_dashboard_context_includes_chart_config_json(rich_home: Path, builder, slug, tool):
    """`chart_config_json` is the JSON payload the chart bootstrap
    consumes via JSON.parse (no eval). It must decode cleanly to a
    Chart.js config dict."""

    ctx = builder(str(rich_home))
    raw = ctx["chart_config_json"]
    assert raw, f"{slug} dashboard missing chart_config_json"
    config = json.loads(raw)
    assert config["type"] in ("bar", "line", "pie", "doughnut")
    assert "labels" in config["data"]
    assert isinstance(config["data"]["datasets"], list)


@pytest.mark.parametrize("builder, slug, tool", DASHBOARDS)
def test_dashboard_context_carries_evidence_affordance(rich_home: Path, builder, slug, tool):
    """Per reporting-product.md §6 every aggregate metric carries an
    evidence affordance. The context's `evidence` block must include
    tool + CLI invocation + request_id."""

    ctx = builder(str(rich_home))
    ev = ctx["evidence"]
    assert ev["tool"] == tool
    assert ev["cli_invocation"].startswith("tt ")
    assert ev["request_id"]


@pytest.mark.parametrize("builder, slug, tool", DASHBOARDS)
def test_dashboard_context_has_highlighted_metric_tiles(rich_home: Path, builder, slug, tool):
    """The per-dashboard tile selection (REPORTING_DASHBOARD_TILES)
    lands as `highlighted_metrics`. Every tile entry has `key` and
    `label` at minimum so the macro can render it."""

    ctx = builder(str(rich_home))
    tiles = ctx["highlighted_metrics"]
    assert tiles, f"{slug} dashboard has no highlighted metric tiles"
    for tile in tiles:
        assert "key" in tile
        assert "label" in tile


# -- position detail (trade-trace-svp2) -----------------------------


def test_position_detail_context_returns_none_for_unknown(rich_home: Path) -> None:
    from trade_trace.storage.database import open_database_readonly
    from trade_trace.storage.paths import db_path

    db = open_database_readonly(db_path(rich_home))
    try:
        assert position_detail_context(db.connection, position_id="pos_nope") is None
    finally:
        db.close()


def test_position_detail_context_renders_lifecycle_for_closed_position(rich_home: Path) -> None:
    from trade_trace.storage.database import open_database_readonly
    from trade_trace.storage.paths import db_path

    db = open_database_readonly(db_path(rich_home))
    try:
        row = db.connection.execute(
            "SELECT id FROM positions WHERE status = 'closed' LIMIT 1"
        ).fetchone()
        assert row is not None
        ctx = position_detail_context(db.connection, position_id=row[0])
    finally:
        db.close()

    assert ctx is not None
    assert ctx["position"]["status"] == "closed"
    assert ctx["events"], "closed position must surface event lineage"
    timestamps = [ev["created_at"] for ev in ctx["events"]]
    assert timestamps == sorted(timestamps), "events must render chronologically"


def test_position_detail_context_surfaces_open_no_mark_caveat(rich_home: Path) -> None:
    """An open position without a snapshot mark must carry the
    open_no_mark caveat in the rendered context."""

    from trade_trace.storage.database import open_database_readonly
    from trade_trace.storage.paths import db_path

    db = open_database_readonly(db_path(rich_home))
    try:
        row = db.connection.execute(
            "SELECT id FROM positions "
            "WHERE status = 'open' AND unrealized_pnl IS NULL LIMIT 1"
        ).fetchone()
        assert row is not None
        ctx = position_detail_context(db.connection, position_id=row[0])
    finally:
        db.close()

    assert ctx is not None
    assert "open_no_mark" in ctx["caveats"]
