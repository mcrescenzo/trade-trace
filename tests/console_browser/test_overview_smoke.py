"""Console browser smoke coverage for shipped routes (trade-trace-beqe).

Routes are loaded from ``frontend/console/src/routeCatalog.json`` so this
smoke test fails closed when the Console ships a new route without browser
coverage. No catalog routes are intentionally excluded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROUTE_CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "console"
    / "src"
    / "routeCatalog.json"
)


def _route_catalog() -> list[dict[str, object]]:
    with ROUTE_CATALOG_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


ROUTES = _route_catalog()


def _heading_for_route(route: dict[str, object]) -> str:
    """Return the route-specific PageHeader text expected after navigation.

    Prefer catalog title data where it matches the shipped page. Components
    without catalog titles have stable PageHeader titles in ``main.tsx``; keep
    that small local map explicit so every catalog route has a heading check.
    """

    path = str(route["path"])
    component = str(route["component"])
    if path == "/reports/pnl":
        return "Realized, unrealized, and grouped performance"
    if path == "/reports/risk":
        return "Risk/R-multiple and position analytics"
    if path == "/calibration":
        return "Forecast reliability and scoring integrity"
    if path == "/evidence":
        return "Source coverage and provenance diagnostics"
    if component == "report":
        return str(route["title"])
    return {
        "overview": "Journal intelligence at a glance",
        "trades": "Position lifecycle rows",
        "catalog": "Report catalog",
        "review": "Local period review packet",
        "process": "Supported local process analytics",
        "strategies": "Strategy performance and process review",
        "playbooks": "Playbook rule-adherence review",
        "events": str(route.get("title", "Journal timeline and replay")),
        "decisions": "Recorded decisions",
    }[component]


@pytest.mark.parametrize(
    "route",
    ROUTES,
    ids=lambda route: f"{route['label']} {route['path']}",
)
def test_shipped_console_route_renders_heading_and_no_console_errors(
    page,
    console_url,
    route,
):
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: errors.append(msg.text) if msg.type == "error" else None,
    )

    page.goto(console_url + str(route["path"]))

    expect(page.get_by_role("heading", name=_heading_for_route(route), level=2)).to_be_visible()
    assert page.get_by_text("Trade Trace").is_visible()
    assert page.get_by_text("Read-only Console").is_visible()
    assert errors == [], errors


def test_overview_renders_navigation_refresh_and_dashboard_content(page, console_url):
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: errors.append(msg.text) if msg.type == "error" else None,
    )
    page.goto(console_url + "/")

    # Header brand + read-only badge.
    assert page.get_by_text("Trade Trace").is_visible()
    assert page.get_by_text("Read-only Console").is_visible()
    assert page.get_by_text("read-only").first.is_visible()

    # Nav contains the catalog routes that the frontend exposes as primary nav
    # (routeCatalog.ts excludes /reports/* detail routes from primaryNavRoutes).
    for route in ROUTES:
        if str(route["path"]).startswith("/reports/"):
            continue
        assert page.get_by_role("link", name=str(route["label"])).is_visible(), route

    # Refresh control and dashboard content present.
    assert page.get_by_role("button", name="Refresh").is_visible()
    assert page.get_by_text("Journal intelligence at a glance").is_visible()

    assert errors == [], errors
