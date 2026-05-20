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
    assert "Chart.js" not in chart_panel


def test_legacy_chartjs_bootstrap_removed() -> None:
    legacy_paths = [
        REPO_ROOT / "src" / "trade_trace" / "console" / "static" / "js" / "chart-bootstrap.js",
        REPO_ROOT / "src" / "trade_trace" / "console" / "static" / "vendor" / "chartjs",
    ]
    for path in legacy_paths:
        assert not path.exists(), f"legacy Chart.js artifact still present: {path}"


def test_built_bundle_contains_echarts_runtime() -> None:
    bundle = (STATIC_APP / "assets" / "console.js").read_text(encoding="utf-8")
    assert "echarts" in bundle.lower() or "setOption" in bundle
