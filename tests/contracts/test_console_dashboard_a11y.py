"""Static accessibility checks for the React Console source."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "frontend" / "console" / "src"


def test_shell_has_primary_nav_and_main_landmark() -> None:
    source = (SRC_ROOT / "main.tsx").read_text(encoding="utf-8")
    assert 'aria-label="Primary"' in source
    assert "<main" in source
    assert "Outlet" in source


def test_chart_panel_labels_canvas_equivalent_region() -> None:
    source = (SRC_ROOT / "ui" / "ChartPanel.tsx").read_text(encoding="utf-8")
    assert 'role="img"' in source
    assert "aria-label={title}" in source


def test_data_table_uses_semantic_table_head() -> None:
    source = (SRC_ROOT / "ui" / "DataTable.tsx").read_text(encoding="utf-8")
    assert "<table" in source
    assert "<thead" in source
    assert "<th" in source


def test_no_positive_tabindex_in_frontend_source() -> None:
    for path in SRC_ROOT.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        assert "tabIndex={1}" not in text
        assert 'tabindex="1"' not in text
