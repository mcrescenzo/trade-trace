"""Docs contract for report.strategy_performance rescope (trade-trace-7h9n)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS_DOC = ROOT / "docs" / "architecture" / "reports.md"


def _strategy_performance_section() -> str:
    text = REPORTS_DOC.read_text()
    start = text.index("### 4.7.1 `report.strategy_performance` (shipped wrapper)")
    end = text.index("### 4.8 `report.calibration_integrity`", start)
    return text[start:end]


def test_strategy_performance_docs_define_wrapper_only_contract_and_defer_old_prd_metrics():
    section = _strategy_performance_section()
    normalized = " ".join(section.split())

    assert "report.compare(base_report='pnl', group_by='strategy_id')" in section
    assert "not a separate metric stack" in normalized
    assert "Current output fields" in section
    assert "P&L metrics inherited from `report.compare`/`report.pnl`" in normalized

    for deferred_metric in (
        "calibration trend",
        "mistake-tag frequency",
        "playbook-adherence summary",
    ):
        assert deferred_metric in section
    assert "Deferred old-PRD fields" in section
    assert "not emitted" in section


def test_strategy_performance_docs_give_drill_downs_and_caveats_without_advice_language():
    section = _strategy_performance_section()

    for expected in (
        "`report.calibration`",
        "`report.compare(base_report='calibration'",
        "`report.mistakes`",
        "`report.playbook_adherence`",
        "local journal rows only",
        "does not provide trading advice",
    ):
        assert expected in section

    forbidden = (
        "profitable strategy",
        "alpha",
        "buy signal",
        "sell signal",
        "recommend increasing",
    )
    lowered = section.lower()
    for phrase in forbidden:
        assert phrase not in lowered
