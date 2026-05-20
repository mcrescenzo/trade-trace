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

from trade_trace.console.reporting import run_report
from trade_trace.console.reporting.filter_state import encode_filter
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


@pytest.fixture()
def rich_client(tmp_path: Path) -> TestClient:
    home = tmp_path / "rich"
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok, init
    seed = mcp_call("journal.fixture_seed", {
        "home": str(home),
        "target": "mvp-eval-rich",
        "_allow_no_idempotency": True,
    })
    assert seed.ok, seed
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


def test_report_dashboard_route_decodes_f_and_passes_filter_to_report(
    rich_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict] = []

    def _capture_run_report(tool, args, **kwargs):
        if tool == "report.calibration":
            captured.append(args)
        return run_report(tool, args, **kwargs)

    monkeypatch.setattr(
        "trade_trace.console.reporting.run_report",
        _capture_run_report,
    )

    filter_payload = {"actors": {"actor_id": ["agent:fixture-alpha"]}}
    encoded = encode_filter(filter_payload)
    response = rich_client.get(f"/reports/calibration?f={encoded}")

    assert response.status_code == 200, response.text[:300]
    assert captured
    assert captured[-1]["filter"] == filter_payload


def test_report_export_route_decodes_f_and_preserves_originating_filter(
    rich_client: TestClient,
) -> None:
    filter_payload = {"actors": {"actor_id": ["agent:fixture-alpha"]}}
    encoded = encode_filter(filter_payload)

    unfiltered = rich_client.get("/reports/report.calibration/export.json")
    filtered = rich_client.get(f"/reports/report.calibration/export.json?f={encoded}")

    assert unfiltered.status_code == 200, unfiltered.text[:300]
    assert filtered.status_code == 200, filtered.text[:300]
    unfiltered_body = unfiltered.json()
    filtered_body = filtered.json()
    assert filtered_body["filter"]["actors"]["actor_id"] == ["agent:fixture-alpha"]
    assert filtered_body["filter"] != unfiltered_body["filter"]
    assert (
        filtered_body["envelope"]["data"]["summary"]["metrics"]
        != unfiltered_body["envelope"]["data"]["summary"]["metrics"]
    )


@pytest.mark.parametrize("route", [
    "/reports/calibration",
    "/reports/compare",
    "/reports/report.calibration/export.json",
    "/evidence",
])
def test_report_routes_reject_malformed_or_unknown_axis_f(
    rich_client: TestClient,
    route: str,
) -> None:
    malformed = rich_client.get(f"{route}?f=not valid base64url")
    assert malformed.status_code == 400
    assert malformed.json()["detail"]["type"] == "filter_state_error"

    import base64
    import json
    unknown_axis = base64.urlsafe_b64encode(
        json.dumps({"not_a_real_axis": {"x": 1}}).encode("utf-8")
    ).decode("ascii").rstrip("=")
    invalid = rich_client.get(f"{route}?f={unknown_axis}")
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["type"] == "filter_state_error"


def test_evidence_route_rejects_valid_non_empty_filter_as_unsupported(
    rich_client: TestClient,
) -> None:
    encoded = encode_filter({"actors": {"actor_id": ["agent:fixture-alpha"]}})
    response = rich_client.get(f"/evidence?f={encoded}")

    assert response.status_code == 400
    assert "report.source_quality does not support ReportFilter" in response.text


def test_filter_state_error_details_do_not_echo_raw_query_value(
    rich_client: TestClient,
) -> None:
    response = rich_client.get("/reports/calibration?f=not valid base64url")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["type"] == "filter_state_error"
    assert "raw" not in detail.get("details", {})
