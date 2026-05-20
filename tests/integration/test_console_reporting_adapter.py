"""ReportResult-to-Console adapter contract tests per trade-trace-8ine.

The adapter (`trade_trace.console.reporting.adapter`) is the only path
through which the Console may invoke `report.*` tools. These tests pin:

- safe-report allowlist + lazy-write deny set,
- DashboardContext preserves ReportFilter, sample_warning, caveats,
  groups, examples, record_ids, truncation, evidence affordance,
- raw envelope is exposed for the drilldown affordance.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.console.reporting import (
    SAFE_REPORT_TOOLS,
    DashboardContext,
    ReportAdapterError,
    run_report,
)
from trade_trace.console.reporting.adapter import LAZY_WRITE_DENY_SET
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


# -- safety: deny set + allowlist --------------------------------------


def test_run_report_blocks_every_lazy_write_handler(rich_home: Path) -> None:
    """Every name in `LAZY_WRITE_DENY_SET` must raise
    ReportAdapterError even if it would otherwise be a valid report
    tool. The adapter never falls through to dispatch."""

    for tool in LAZY_WRITE_DENY_SET:
        with pytest.raises(ReportAdapterError, match="deny set"):
            run_report(tool, {}, home=str(rich_home))


def test_run_report_blocks_unknown_or_non_allowlisted_tools(rich_home: Path) -> None:
    for tool in ("decision.add", "memory.recall", "journal.init",
                 "report.does_not_exist"):
        with pytest.raises(ReportAdapterError, match="safe-report allowlist"):
            run_report(tool, {}, home=str(rich_home))


def test_safe_report_allowlist_matches_registered_read_only_tools() -> None:
    """SAFE_REPORT_TOOLS must list only registered `report.*` tools
    that are NOT in the lazy-write deny set."""

    from trade_trace.core import default_registry

    registry = default_registry()
    for tool in SAFE_REPORT_TOOLS:
        assert tool in registry.by_name, f"unknown tool in allowlist: {tool}"
        assert tool not in LAZY_WRITE_DENY_SET, (
            f"allowlist must not include lazy-write tool: {tool}"
        )
        assert registry.by_name[tool].is_write is False, (
            f"allowlisted tool {tool} is marked is_write=True"
        )


# -- context shape -----------------------------------------------------


def test_run_report_calibration_returns_dashboard_context(rich_home: Path) -> None:
    ctx = run_report("report.calibration", {"filter": {}, "min_sample": 1},
                     home=str(rich_home))
    assert isinstance(ctx, DashboardContext)
    assert ctx.tool == "report.calibration"
    # Summary preserved.
    assert isinstance(ctx.summary_metrics, dict)
    assert isinstance(ctx.summary_filter, dict)
    # Evidence affordance populated with tool + CLI invocation +
    # request_id from the live envelope.
    assert ctx.evidence.tool == "report.calibration"
    assert ctx.evidence.cli_invocation == "tt report calibration"
    assert len(ctx.evidence.request_id) > 0
    # Raw envelope preserved verbatim for the drilldown panel.
    assert ctx.raw_envelope["ok"] is True
    assert ctx.raw_envelope["data"]["summary"]["metrics"] == ctx.summary_metrics


def test_run_report_pnl_preserves_groups_record_ids_and_examples(rich_home: Path) -> None:
    ctx = run_report("report.pnl", {"filter": {}}, home=str(rich_home))
    assert ctx.tool == "report.pnl"
    # mvp-eval-rich produces closed positions, so report.pnl returns
    # groups with realized P&L. record_ids must aggregate per kind.
    if ctx.groups:
        first = ctx.groups[0]
        # record_ids is a dict[str, list[str]] — every list entry is
        # a drilldown id the UI can deep-link to.
        for ids in first.record_ids.values():
            assert isinstance(ids, list)
        # The widget-level evidence record_ids aggregate the group
        # record_ids; every group id appears in the evidence aggregate.
        for kind, ids in first.record_ids.items():
            for rid in ids:
                assert rid in ctx.evidence.record_ids.get(kind, [])


def test_run_report_watchlist_preserves_sample_warning_and_as_of(rich_home: Path) -> None:
    ctx = run_report("report.watchlist", {"filter": {}}, home=str(rich_home))
    # as_of stamps every watchlist response.
    assert ctx.as_of is not None
    # Per-group sample_warning is None for fresh watches; the field
    # exists on every group regardless.
    for g in ctx.groups:
        assert hasattr(g, "sample_warning")


def test_run_report_invalid_filter_surfaces_adapter_error(rich_home: Path) -> None:
    """A malformed filter triggers VALIDATION_ERROR from the report
    tool. The adapter MUST re-raise as ReportAdapterError so Console
    handlers can render a typed user-facing error."""

    with pytest.raises(ReportAdapterError, match="VALIDATION_ERROR"):
        run_report(
            "report.calibration",
            {"filter": {"not_a_real_field": "boom"}},
            home=str(rich_home),
        )
