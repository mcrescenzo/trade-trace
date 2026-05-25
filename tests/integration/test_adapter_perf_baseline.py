from __future__ import annotations

import os
import time
from typing import Any

import pytest

from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.adapters.polymarket.config import PolymarketConfig

PERF_TESTS_ENV = "TRADE_TRACE_RUN_PERF_TESTS"
ADAPTER_FIXTURE_BUDGET_SECONDS = 0.25

pytestmark = pytest.mark.skipif(
    os.environ.get(PERF_TESTS_ENV) != "1",
    reason=f"Perf baseline opt-in; set {PERF_TESTS_ENV}=1 to run.",
)


class _FakeResponse:
    status_code = 200
    headers: dict[str, str] = {}

    def json(self) -> dict[str, bool]:
        return {"ok": True}


class _FakeHttpClient:
    def __enter__(self) -> _FakeHttpClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def get(self, _url: str) -> _FakeResponse:
        return _FakeResponse()


class _FixturePolymarketClient(PolymarketClient):
    def _client(self) -> Any:
        return _FakeHttpClient()


def test_adapter_fixture_mocked_fetch_under_budget():
    client = _FixturePolymarketClient(
        PolymarketConfig(enabled=True, gamma_base_url="https://gamma-api.polymarket.com")
    )

    start = time.perf_counter()
    for _ in range(100):
        assert client.gamma_get("/markets/perf-fixture") == {"ok": True}
    elapsed = time.perf_counter() - start

    assert elapsed < ADAPTER_FIXTURE_BUDGET_SECONDS, (
        f"100 fixture-mocked adapter fetches took {elapsed:.3f}s "
        f"(budget {ADAPTER_FIXTURE_BUDGET_SECONDS}s)"
    )
