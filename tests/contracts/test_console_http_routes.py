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
    "/review",
    "/reports/pnl",
    "/reports/risk",
    "/reports/performance",
    "/reports/strategy",
    "/reports/decisions",
    "/process",
    "/reports/compare",
    "/calibration",
    "/evidence",
    "/strategies",
    "/playbooks",
    "/journal",
    "/decisions",
]


@pytest.mark.parametrize("route", SPA_ROUTES)
def test_spa_route_serves_prebuilt_index(client: TestClient, route: str) -> None:
    response = client.get(route)
    assert response.status_code == 200, response.text[:300]
    assert "text/html" in response.headers["content-type"]
    assert "/assets/console.js" in response.text


def test_security_headers_present_on_http_responses(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"]
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response.headers["Cross-Origin-Embedder-Policy"] == "require-corp"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"


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
    "/api/console/positions?cursor=not-a-real-cursor",
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
    assert "/logs" not in body["routes"]
    assert "/raw" not in body["routes"]


def test_trade_detail_is_not_exposed_as_console_http_route(rich_client: TestClient) -> None:
    """`trade_detail()` is an external Python read-model API only.

    The Console intentionally exposes `/api/console/trades` for the list
    contract, but no HTTP/UI trade-detail route is implied today.
    """

    response = rich_client.get("/api/console/trades/dec_does_not_exist")
    assert response.status_code == 404


def test_positions_list_endpoint_returns_rows_filters_and_paginates(rich_client: TestClient) -> None:
    first = rich_client.get("/api/console/positions?limit=2")
    assert first.status_code == 200, first.text[:300]
    body = first.json()
    assert set(body) == {"rows", "next_cursor", "limit"}
    assert body["limit"] == 2
    assert len(body["rows"]) == 2
    assert body["next_cursor"] is not None
    row = body["rows"][0]
    for key in [
        "position_id", "instrument_id", "kind", "status", "outcome",
        "opened_at", "net_quantity", "add_count", "reduce_count",
        "event_count", "opening_decision_id", "opening_strategy_id",
        "caveats", "caveat_entries",
    ]:
        assert key in row

    second = rich_client.get(f"/api/console/positions?limit=2&cursor={body['next_cursor']}")
    assert second.status_code == 200, second.text[:300]
    assert {r["position_id"] for r in body["rows"]}.isdisjoint(
        {r["position_id"] for r in second.json()["rows"]},
    )

    filtered = rich_client.get(
        "/api/console/positions",
        params={
            "status": row["status"],
            "kind": row["kind"],
            "instrument_id": row["instrument_id"],
            "outcome": row["outcome"],
            "opened_from": row["opened_at"],
            "opened_to": row["opened_at"],
            "limit": 50,
        },
    )
    assert filtered.status_code == 200, filtered.text[:300]
    filtered_rows = filtered.json()["rows"]
    assert filtered_rows
    assert all(r["status"] == row["status"] for r in filtered_rows)
    assert all(r["kind"] == row["kind"] for r in filtered_rows)
    assert all(r["instrument_id"] == row["instrument_id"] for r in filtered_rows)
    assert all(r["outcome"] == row["outcome"] for r in filtered_rows)

    empty = rich_client.get("/api/console/positions?status=not-a-status")
    assert empty.status_code == 200
    assert empty.json()["rows"] == []


def test_positions_list_endpoint_strategy_filter(rich_client: TestClient) -> None:
    all_rows = rich_client.get("/api/console/positions?limit=100").json()["rows"]
    target = next(r for r in all_rows if r["opening_strategy_id"] is not None)
    filtered = rich_client.get(
        "/api/console/positions",
        params={"strategy_id": target["opening_strategy_id"], "limit": 100},
    )
    assert filtered.status_code == 200, filtered.text[:300]
    rows = filtered.json()["rows"]
    assert rows
    assert all(r["opening_strategy_id"] == target["opening_strategy_id"] for r in rows)


def test_journal_events_support_local_audit_filters_and_related_context(rich_client: TestClient) -> None:
    first_page = rich_client.get("/api/console/events?limit=10")
    assert first_page.status_code == 200, first_page.text[:300]
    first_rows = first_page.json()["rows"]
    assert first_rows
    actor_id = first_rows[0]["actor_id"]

    page = rich_client.get(f"/api/console/events?limit=10&actor_id={actor_id}")
    assert page.status_code == 200, page.text[:300]
    rows = page.json()["rows"]
    assert rows
    assert all(row["actor_id"] == actor_id for row in rows)
    assert "subject_id" in rows[0]
    assert "idempotency_key" in rows[0]

    related = rich_client.get(f"/api/console/events/{rows[0]['id']}/related")
    assert related.status_code == 200, related.text[:300]
    body = related.json()
    assert body["event_id"] == rows[0]["id"]
    assert "subject_events" in body


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
