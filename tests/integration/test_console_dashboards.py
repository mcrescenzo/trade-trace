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
    """Legacy context helpers still emit a JSON chart config for
    projection coverage even though the shipped React app renders
    charts with ECharts."""

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


def test_dashboard_overview_combines_pnl_and_risk_per_w422(rich_home: Path) -> None:
    """Overview MUST surface both P&L and risk summary metrics in one
    dashboard context (per bead trade-trace-w422). The headline tiles
    cover the P&L lane; mean R + expectancy round out the risk lane."""

    from trade_trace.console.pages import dashboard_overview_context

    ctx = dashboard_overview_context(str(rich_home))
    assert ctx["dashboard_slug"] == "overview"
    assert ctx["evidence"]["tool"] == "report.pnl"
    tile_keys = {tile["key"] for tile in ctx["highlighted_metrics"]}
    # P&L tiles
    assert {"realized_pnl", "unrealized_pnl", "open_position_count"} & tile_keys
    # Risk tiles (mean_r + expectancy_r at minimum)
    assert "mean_r" in tile_keys
    assert "expectancy_r" in tile_keys
    # record_ids are aggregated across both reports.
    assert isinstance(ctx["evidence"]["record_ids"], dict)


def test_report_export_packet_returns_full_envelope_per_sqtq(rich_home: Path) -> None:
    """Export packets bundle the full ReportResult envelope + filter +
    request_id + record_ids + exported_at; the rest is metadata for
    reproducing the call."""

    from trade_trace.console.pages import report_export_packet

    packet = report_export_packet(home=str(rich_home), tool="report.pnl")
    assert packet["tool"] == "report.pnl"
    assert packet["cli_invocation"] == "tt report pnl"
    assert packet["envelope"]["ok"] is True
    assert packet["envelope"]["data"]["summary"]["metrics"]
    assert "exported_at" in packet
    assert packet["filter"] is not None
    assert isinstance(packet["record_ids"], dict)


def test_report_export_packet_rejects_lazy_write_tool(rich_home: Path) -> None:
    """The export packet endpoint inherits the safe-report allowlist.
    Attempting to export report.coach must raise ReportAdapterError."""

    import pytest as _pytest

    from trade_trace.console.pages import report_export_packet
    from trade_trace.console.reporting import ReportAdapterError

    with _pytest.raises(ReportAdapterError):
        report_export_packet(home=str(rich_home), tool="report.coach")


def test_dashboard_compare_context_uses_report_compare(rich_home: Path) -> None:
    from trade_trace.console.pages import dashboard_compare_context

    ctx = dashboard_compare_context(str(rich_home))
    assert ctx["evidence"]["tool"] == "report.compare"
    assert "compare_form" in ctx
    assert ctx["compare_form"]["base_report"] == "calibration"
    assert "strategy_id" in ctx["compare_form"]["allowed_group_by"]


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
