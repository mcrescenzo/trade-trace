"""HTTP-level smoke tests for the React/Vite Console server."""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.console.reporting.filter_state import encode_filter
from trade_trace.mcp_server import mcp_call

pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi.testclient import TestClient  # noqa: E402

from trade_trace.console.serve import _build_app  # noqa: E402


def _seed_home(tmp_path: Path, *, rich: bool = False) -> Path:
    home = tmp_path / ("rich" if rich else "home")
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok, init
    if rich:
        seed = mcp_call(
            "journal.fixture_seed",
            {"home": str(home), "target": "mvp-eval-rich", "_allow_no_idempotency": True},
            actor_id="agent:test",
        )
    else:
        seed = mcp_call(
            "memory.retain",
            {
                "home": str(home),
                "node_type": "observation",
                "body": "http smoke seed",
                "idempotency_key": "http-smoke-1",
            },
            actor_id="agent:default",
        )
    assert seed.ok, seed
    return home


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(_build_app(str(_seed_home(tmp_path))))


@pytest.fixture()
def rich_client(tmp_path: Path) -> TestClient:
    return TestClient(_build_app(str(_seed_home(tmp_path, rich=True))), raise_server_exceptions=False)


@pytest.fixture()
def missing_db_client(tmp_path: Path) -> TestClient:
    return TestClient(_build_app(str(tmp_path / "missing")), raise_server_exceptions=False)


SPA_ROUTES = [
    "/",
    "/trades",
    "/reports",
    "/reports/pnl",
    "/reports/risk",
    "/calibration",
    "/evidence",
    "/strategies",
    "/playbooks",
    "/journal",
    "/decisions",
    "/logs",
    "/raw",
]


@pytest.mark.parametrize("route", SPA_ROUTES)
def test_spa_route_serves_prebuilt_index(client: TestClient, route: str) -> None:
    response = client.get(route)
    assert response.status_code == 200, response.text[:300]
    assert "text/html" in response.headers["content-type"]
    assert "/assets/console.js" in response.text


def test_status_endpoint_serves_documented_fields(client: TestClient) -> None:
    response = client.get("/api/console/status")
    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert "db_path" in body
    assert "row_counts" in body


def test_missing_db_status_returns_typed_json(missing_db_client: TestClient) -> None:
    response = missing_db_client.get("/api/console/status")
    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["reason"] == "missing"


@pytest.mark.parametrize("route", [
    "/api/console/events?cursor=not-a-real-cursor",
    "/api/console/decisions?cursor=not-a-real-cursor",
    "/api/console/strategies?cursor=not-a-real-cursor",
])
def test_json_list_routes_reject_malformed_cursor_as_400(
    rich_client: TestClient,
    route: str,
) -> None:
    response = rich_client.get(route)
    assert response.status_code == 400
    assert response.json()["detail"]["type"] == "pagination_error"


def test_catalog_endpoint_exposes_spa_routes_and_report_allowlist(client: TestClient) -> None:
    response = client.get("/api/console/catalog")
    assert response.status_code == 200
    body = response.json()
    assert "/trades" in body["routes"]
    assert "report.pnl" in body["report_tools"]
    assert "report.coach" in body["lazy_write_handlers_blocked"]


def test_static_favicon_and_built_assets_are_served(client: TestClient) -> None:
    favicon = client.get("/static/favicon.svg")
    bundle = client.get("/assets/console.js")
    assert favicon.status_code == 200
    assert "image/svg+xml" in favicon.headers["content-type"]
    assert bundle.status_code == 200
    assert "javascript" in bundle.headers["content-type"]


def test_report_run_endpoint_returns_dashboard_context(rich_client: TestClient) -> None:
    response = rich_client.post(
        "/api/console/reports/report.calibration/run",
        json={"filter": {}},
    )
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["tool"] == "report.calibration"
    assert "summary_metrics" in body
    assert body["evidence"]["tool"] == "report.calibration"


def test_report_export_decodes_f_and_preserves_originating_filter(
    rich_client: TestClient,
) -> None:
    filter_payload = {"actors": {"actor_id": ["agent:fixture-alpha"]}}
    encoded = encode_filter(filter_payload)

    unfiltered = rich_client.get("/api/console/reports/report.calibration/export")
    filtered = rich_client.get(f"/api/console/reports/report.calibration/export?f={encoded}")

    assert unfiltered.status_code == 200, unfiltered.text[:300]
    assert filtered.status_code == 200, filtered.text[:300]
    unfiltered_body = unfiltered.json()
    filtered_body = filtered.json()
    assert filtered_body["filter"]["actors"]["actor_id"] == ["agent:fixture-alpha"]
    assert filtered_body["filter"] != unfiltered_body["filter"]


def test_report_export_rejects_malformed_or_unknown_axis_f(
    rich_client: TestClient,
) -> None:
    malformed = rich_client.get("/api/console/reports/report.calibration/export?f=not valid")
    assert malformed.status_code == 400
    assert malformed.json()["detail"]["type"] == "filter_state_error"

    import base64
    import json

    unknown_axis = base64.urlsafe_b64encode(
        json.dumps({"not_a_real_axis": {"x": 1}}).encode("utf-8")
    ).decode("ascii").rstrip("=")
    invalid = rich_client.get(f"/api/console/reports/report.calibration/export?f={unknown_axis}")
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["type"] == "filter_state_error"
