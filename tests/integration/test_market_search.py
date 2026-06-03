"""Integration coverage for the live market discovery surface (market.search).

Bead trade-trace-663l: a bot must be able to discover bindable binary markets
through the system without an out-of-band Gamma curl and without a pre-known
external_id or an already-bound market. market.search is the read-only adapter
discovery tool that closes that gap.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests._mcp_helpers import with_legacy_idempotency_key
from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.contracts.envelope import ErrorEnvelope, SuccessEnvelope
from trade_trace.core import build_registry
from trade_trace.mcp_server import mcp_call


def _enable_adapter(home: str) -> None:
    assert mcp_call(
        "journal.config_set",
        with_legacy_idempotency_key(
            "journal.config_set",
            {"home": home, "key": "network.polymarket.enabled", "value": "true", "confirm": True},
        ),
    ).ok


def _binary_market(market_id: str, *, question: str, slug: str, close_at: str) -> dict:
    return {
        "id": market_id,
        "question": question,
        "slug": slug,
        "endDate": close_at,
        "eventSlug": f"event-{slug}",
        "outcomes": '["Yes","No"]',
        "active": True,
        "closed": False,
    }


def test_market_search_is_registered_public_and_read_only():
    registry = build_registry()
    assert "market.search" in registry.public_names()
    reg = registry.get("market.search")
    assert reg.is_write is False


def test_market_search_disabled_fails_closed(tmp_path: Path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    env = mcp_call("market.search", {"home": home, "query": "election"})
    assert not env.ok
    assert isinstance(env, ErrorEnvelope)
    assert env.error.code == "ADAPTER_DISABLED"


def test_market_search_returns_binary_candidates_without_prebound_market(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)
    calls: list[str] = []

    def fake_gamma_get(self: PolymarketClient, path: str):
        calls.append(path)
        return [
            _binary_market("540844", question="Will A happen?", slug="will-a", close_at="2026-12-31T00:00:00Z"),
            # Non-binary: filtered out so callers only see bindable markets.
            {"id": "999", "question": "Multi?", "slug": "multi", "outcomes": '["A","B","C"]'},
            _binary_market("540999", question="Will B happen?", slug="will-b", close_at="2027-01-15T00:00:00Z"),
        ]

    monkeypatch.setattr(PolymarketClient, "gamma_get", fake_gamma_get)

    env = mcp_call("market.search", {"home": home, "query": "happen", "limit": 20})

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert len(calls) == 1
    assert calls[0].startswith("/markets?")
    assert "q=happen" in calls[0]
    assert "active=true" in calls[0]
    data = env.data
    assert data["source"] == "polymarket"
    assert data["count"] == 2
    ids = [c["external_id"] for c in data["candidates"]]
    assert ids == ["540844", "540999"]
    first = data["candidates"][0]
    assert first["gamma_market_id"] == "540844"
    assert first["slug"] == "will-a"
    assert first["question"] == "Will A happen?"
    assert first["outcomes"] == ["yes", "no"]
    assert first["close_at"] == "2026-12-31T00:00:00Z"
    assert data["no_advice_boundary"]["db_write_performed"] is False
    assert data["no_advice_boundary"]["trade_execution_performed"] is False


def test_market_search_respects_limit_after_binary_filtering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)

    markets = [
        _binary_market(str(i), question=f"Q{i}?", slug=f"q-{i}", close_at="2026-12-31T00:00:00Z")
        for i in range(10)
    ]
    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: markets)

    env = mcp_call("market.search", {"home": home, "limit": 3})

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert env.data["count"] == 3
    assert [c["external_id"] for c in env.data["candidates"]] == ["0", "1", "2"]


def test_market_search_rejects_out_of_range_limit(tmp_path: Path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    env = mcp_call("market.search", {"home": home, "limit": 0})
    assert not env.ok
    assert isinstance(env, ErrorEnvelope)
    assert env.error.code == "VALIDATION_ERROR"


def test_market_search_handles_wrapped_markets_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)

    monkeypatch.setattr(
        PolymarketClient,
        "gamma_get",
        lambda self, path: {
            "markets": [
                _binary_market("1", question="Wrapped?", slug="wrapped", close_at="2026-12-31T00:00:00Z")
            ]
        },
    )

    env = mcp_call("market.search", {"home": home})

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert env.data["count"] == 1
    assert env.data["candidates"][0]["external_id"] == "1"
