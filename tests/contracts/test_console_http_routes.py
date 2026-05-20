"""HTTP-level smoke tests for the Console FastAPI app.

The existing console tests exercise page-context functions and
endpoint helpers in isolation (no HTTP). That left a gap: route
handlers built by `_build_app` were never invoked through the
ASGI stack, so a misannotated `request` parameter (treated as a
query parameter rather than the injected `Request`) shipped
undetected and produced 422 on every page when actually served.

These tests fire requests through `TestClient` so every HTML page
and JSON endpoint is exercised end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call

pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi.testclient import TestClient  # noqa: E402

from trade_trace.console.serve import _build_app  # noqa: E402


def _seed_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    mcp_call("journal.init", {"home": str(home)})
    mcp_call(
        "memory.retain",
        {
            "home": str(home),
            "node_type": "observation",
            "body": "http smoke seed",
            "idempotency_key": "http-smoke-1",
        },
        actor_id="agent:default",
    )
    return home


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    home = _seed_home(tmp_path)
    app = _build_app(str(home))
    return TestClient(app)


HTML_ROUTES = [
    "/",
    "/journal",
    "/decisions",
    "/reports",
    "/calibration",
    "/strategies",
    "/playbooks",
    "/integrity",
    "/logs",
    "/raw",
]


@pytest.mark.parametrize("route", HTML_ROUTES)
def test_html_route_renders_200(client: TestClient, route: str) -> None:
    response = client.get(route)
    assert response.status_code == 200, (
        f"{route} returned {response.status_code}: {response.text[:300]}"
    )
    assert "text/html" in response.headers["content-type"]


def test_status_endpoint_serves_documented_fields(client: TestClient) -> None:
    response = client.get("/status")
    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert "db_path" in body
    assert "row_counts" in body
