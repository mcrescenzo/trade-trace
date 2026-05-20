"""ECharts/Vite charting contract for the clean-break Console."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "frontend" / "console"
STATIC_APP = REPO_ROOT / "src" / "trade_trace" / "console" / "static" / "app"


def test_charting_uses_echarts_not_chartjs_bootstrap() -> None:
    package_json = (FRONTEND_ROOT / "package.json").read_text(encoding="utf-8")
    chart_panel = (FRONTEND_ROOT / "src" / "ui" / "ChartPanel.tsx").read_text(
        encoding="utf-8",
    )
    assert '"echarts"' in package_json
    assert "echarts.init" in chart_panel


def test_static_console_assets_are_vite_app_only() -> None:
    static_root = REPO_ROOT / "src" / "trade_trace" / "console" / "static"
    assert sorted(path.name for path in static_root.iterdir()) == ["app", "favicon.svg"]
    assert sorted(path.name for path in STATIC_APP.iterdir()) == ["assets", "index.html", "provenance.json"]


def test_built_bundle_contains_echarts_runtime() -> None:
    bundle = (STATIC_APP / "assets" / "console.js").read_text(encoding="utf-8")
    assert "echarts" in bundle.lower() or "setOption" in bundle
