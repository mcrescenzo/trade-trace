"""React/Vite Console shell contract tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from trade_trace.console.security import external_resources_in_markup

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "frontend" / "console"
APP_ROOT = REPO_ROOT / "src" / "trade_trace" / "console" / "static" / "app"
PY_ROUTE_CATALOG = REPO_ROOT / "src" / "trade_trace" / "console" / "route_catalog.json"
FRONTEND_ROUTE_CATALOG = FRONTEND_ROOT / "src" / "routeCatalog.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frontend_workspace_declares_recommended_stack() -> None:
    package_json = json.loads((FRONTEND_ROOT / "package.json").read_text(encoding="utf-8"))
    declared_deps = set(package_json["dependencies"]) | set(package_json["devDependencies"])

    for dep in (
        "react",
        "react-dom",
        "vite",
        "@tanstack/react-router",
        "@tanstack/react-query",
        "@tanstack/react-table",
        "echarts",
        "@radix-ui/react-tooltip",
        "tailwindcss",
        "lucide-react",
    ):
        assert dep in declared_deps

    removed_deps = {
        "@tanstack/" + "react-" + "virtual",
        "@radix-ui/" + "react-" + "tabs",
    }
    assert declared_deps.isdisjoint(removed_deps)


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
    assert '"trade_trace.console" = ["static/**/*", "route_catalog.json"]' in pyproject


def test_console_route_catalogs_stay_aligned() -> None:
    assert json.loads(PY_ROUTE_CATALOG.read_text(encoding="utf-8")) == json.loads(
        FRONTEND_ROUTE_CATALOG.read_text(encoding="utf-8")
    )


def test_packaged_static_assets_match_build_provenance() -> None:
    manifest_path = APP_ROOT / "provenance.json"
    assert manifest_path.is_file(), "run npm --prefix frontend/console run build to refresh provenance"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["generated_by"] == "npm --prefix frontend/console run build"

    for rel_path, expected_hash in manifest["source_hashes"].items():
        assert _sha256(FRONTEND_ROOT / rel_path) == expected_hash, f"stale Console source provenance for {rel_path}"

    actual_asset_paths = {
        path.relative_to(APP_ROOT).as_posix()
        for path in APP_ROOT.rglob("*")
        if path.is_file() and path.name != "provenance.json"
    }
    assert actual_asset_paths == set(manifest["asset_hashes"]), "packaged Console assets differ from provenance manifest"

    for rel_path, expected_hash in manifest["asset_hashes"].items():
        assert _sha256(APP_ROOT / rel_path) == expected_hash, f"packaged Console asset drift for {rel_path}"
