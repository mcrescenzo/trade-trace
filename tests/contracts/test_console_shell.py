"""React/Vite Console shell contract tests."""

from __future__ import annotations

from pathlib import Path

from trade_trace.console.security import external_resources_in_markup

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "frontend" / "console"
APP_ROOT = REPO_ROOT / "src" / "trade_trace" / "console" / "static" / "app"


def test_frontend_workspace_declares_recommended_stack() -> None:
    package_json = (FRONTEND_ROOT / "package.json").read_text(encoding="utf-8")
    for dep in (
        '"react"',
        '"vite"',
        '"@tanstack/react-router"',
        '"@tanstack/react-query"',
        '"@tanstack/react-table"',
        '"@tanstack/react-virtual"',
        '"echarts"',
        '"@radix-ui/react-tabs"',
        '"tailwindcss"',
        '"lucide-react"',
    ):
        assert dep in package_json


def test_spa_source_uses_router_and_accessible_landmarks() -> None:
    source = (FRONTEND_ROOT / "src" / "main.tsx").read_text(encoding="utf-8")
    assert "createRouter" in source
    assert 'aria-label="Primary"' in source
    assert "<main" in source
    assert "read-only" in source


def test_prebuilt_console_app_assets_ship() -> None:
    assert (APP_ROOT / "index.html").is_file()
    assert (APP_ROOT / "assets" / "console.js").is_file()
    assert any((APP_ROOT / "assets").glob("*.css"))


def test_built_index_uses_external_assets_only() -> None:
    html = (APP_ROOT / "index.html").read_text(encoding="utf-8")
    assert external_resources_in_markup(html) == []
    assert "<script type=\"module\"" in html
    assert "src=\"/assets/console.js\"" in html
    assert "http://" not in html
    assert "https://" not in html


def test_package_data_points_at_static_app_only() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"trade_trace.console" = ["static/**/*"]' in pyproject
