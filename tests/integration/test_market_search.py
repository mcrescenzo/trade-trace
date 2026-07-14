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


def test_market_search_is_registered_experimental_and_read_only():
    registry = build_registry()
    assert "market.search" not in registry.public_names()
    assert "market.search" in registry.public_names(include_experimental=True)
    reg = registry.get("market.search")
    assert reg.is_write is False
    assert reg.metadata()["catalog_visibility"] == "experimental"


def test_market_search_disabled_fails_closed(tmp_path: Path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    env = mcp_call("market.search", {"home": home, "query": "election"})
    assert not env.ok
    assert isinstance(env, ErrorEnvelope)
    assert env.error.code == "ADAPTER_DISABLED"


def test_market_search_query_uses_public_search_and_flattens_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # trade-trace-yz3q: a query must hit Gamma's real search endpoint
    # (/public-search), NOT /markets (whose `q` is silently ignored). The
    # /public-search payload nests markets under events, so the tool must
    # flatten events[].markets[] before projecting binary candidates.
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)
    calls: list[str] = []

    def fake_gamma_get(self: PolymarketClient, path: str):
        calls.append(path)
        return {
            "events": [
                {
                    "id": "evt-1",
                    "title": "Event one",
                    "markets": [
                        _binary_market(
                            "540844", question="Will A happen?", slug="will-a", close_at="2026-12-31T00:00:00Z"
                        ),
                        # Non-binary nested market: filtered out.
                        {"id": "999", "question": "Multi?", "slug": "multi", "outcomes": '["A","B","C"]'},
                    ],
                },
                {
                    "id": "evt-2",
                    "title": "Event two",
                    "markets": [
                        _binary_market(
                            "540999", question="Will B happen?", slug="will-b", close_at="2027-01-15T00:00:00Z"
                        ),
                    ],
                },
            ],
            "pagination": {"hasMore": False},
        }

    monkeypatch.setattr(PolymarketClient, "gamma_get", fake_gamma_get)

    env = mcp_call("market.search", {"home": home, "query": "happen", "limit": 20})

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert len(calls) == 1
    # The query path must route to /public-search, never /markets.
    assert calls[0].startswith("/public-search?")
    assert "q=happen" in calls[0]
    assert not calls[0].startswith("/markets")
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


def test_market_search_zero_results_multiword_query_carries_search_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # AX dogfood AX-026: Gamma /public-search is conjunctive — a natural
    # multi-keyword query ("bitcoin ethereum price") can match no single market
    # even though related markets exist. A bot must not silently dead-end on the
    # empty result; the response carries a search_hint nudging it to relax the
    # query. AX-035: a single-term zero-result query also carries a hint — a
    # distinct one telling the bot the search ran but the term matched no live
    # market (so it isn't misread as a silent search failure, the AX-019 trap).
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)

    def fake_gamma_get(self: PolymarketClient, path: str):
        return {"events": [], "pagination": {"hasMore": False}}

    monkeypatch.setattr(PolymarketClient, "gamma_get", fake_gamma_get)

    multi = mcp_call("market.search", {"home": home, "query": "bitcoin ethereum price", "limit": 20})
    assert multi.ok, multi
    assert multi.data["count"] == 0
    assert multi.data["search_hint"] is not None
    assert "conjunctive" in multi.data["search_hint"]

    single = mcp_call("market.search", {"home": home, "query": "bitcoin", "limit": 20})
    assert single.ok, single
    assert single.data["count"] == 0
    # AX-035: single-term zero result gets its own (non-relaxation) hint.
    assert single.data["search_hint"] is not None
    assert "conjunctive" not in single.data["search_hint"]
    assert "closed=true" in single.data["search_hint"]


def test_market_search_query_drops_closed_markets_from_public_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # /public-search returns closed markets too; market.search must drop them
    # unless the caller opts in via closed=True (trade-trace-yz3q).
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)

    open_market = _binary_market("100", question="Open?", slug="open", close_at="2027-01-01T00:00:00Z")
    closed_market = _binary_market("200", question="Closed?", slug="closed", close_at="2025-01-01T00:00:00Z")
    closed_market["closed"] = True

    monkeypatch.setattr(
        PolymarketClient,
        "gamma_get",
        lambda self, path: {"events": [{"id": "e", "markets": [open_market, closed_market]}]},
    )

    env = mcp_call("market.search", {"home": home, "query": "x", "limit": 20})
    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert [c["external_id"] for c in env.data["candidates"]] == ["100"]

    env_closed = mcp_call("market.search", {"home": home, "query": "x", "limit": 20, "closed": True})
    assert env_closed.ok, env_closed
    assert sorted(c["external_id"] for c in env_closed.data["candidates"]) == ["100", "200"]


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


def test_market_search_candidate_exposes_resolution_description(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # trade-trace-n33z: a bot must be able to read what YES actually resolves on
    # at discovery time — e.g. to tell a literal-event market from one whose
    # price reflects release-timing mechanics — without binding first. Gamma
    # carries that prose in `description`, so the search candidate echoes it.
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)

    rule_text = "Resolves YES if the event is officially confirmed before the deadline."
    market = _binary_market("777", question="Will it?", slug="will-it", close_at="2027-01-01T00:00:00Z")
    market["description"] = rule_text
    monkeypatch.setattr(
        PolymarketClient,
        "gamma_get",
        lambda self, path: {"events": [{"id": "e", "markets": [market]}]},
    )

    env = mcp_call("market.search", {"home": home, "query": "will", "limit": 20})
    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    candidate = env.data["candidates"][0]
    assert candidate["external_id"] == "777"
    assert candidate["description"] == rule_text


def test_market_search_candidate_surfaces_liquidity_signals_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """trade-trace-ffuo7: live Gamma /public-search and /markets market rows
    DO carry liquidity signals (verified against the real payload, not
    merely documented as absent) -- surface them so the universe volume gate
    can run at discovery time instead of only post-bind, which previously
    left 2-5 orphan gate-failing binds per discovery run."""
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)

    market = _binary_market("888", question="Will it?", slug="will-it", close_at="2027-01-01T00:00:00Z")
    market["volume"] = "123456.78"
    market["volumeNum"] = 123456.78
    market["volume24hr"] = 4321.5
    market["liquidity"] = "999.1"
    market["liquidityNum"] = 999.1
    monkeypatch.setattr(
        PolymarketClient,
        "gamma_get",
        lambda self, path: {"events": [{"id": "e", "markets": [market]}]},
    )

    env = mcp_call("market.search", {"home": home, "query": "will", "limit": 20})
    assert env.ok, env
    candidate = env.data["candidates"][0]
    assert candidate["volume"] == pytest.approx(123456.78)
    assert candidate["volume_24h"] == pytest.approx(4321.5)
    assert candidate["liquidity"] == pytest.approx(999.1)


def test_market_search_candidate_liquidity_fields_absent_not_fabricated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """When Gamma genuinely omits a liquidity field (common for volume_24h/
    liquidity even though cumulative volume is reliably present), the
    candidate carries None rather than a fabricated/derived value."""
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)

    market = _binary_market("889", question="Will it too?", slug="will-it-too", close_at="2027-01-01T00:00:00Z")
    # No volume/volumeNum/volume24hr/liquidity/liquidityNum keys at all.
    monkeypatch.setattr(
        PolymarketClient,
        "gamma_get",
        lambda self, path: {"events": [{"id": "e", "markets": [market]}]},
    )

    env = mcp_call("market.search", {"home": home, "query": "will", "limit": 20})
    assert env.ok, env
    candidate = env.data["candidates"][0]
    assert candidate["volume"] is None
    assert candidate["volume_24h"] is None
    assert candidate["liquidity"] is None


def test_market_search_candidate_tolerates_malformed_volume_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A malformed volume field on one discovery candidate must not fail the
    whole market.search call -- it degrades to None instead of raising
    (unlike bind/snapshot numeric fields, which are strict and fail closed)."""
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)

    market = _binary_market("890", question="Bad volume?", slug="bad-volume", close_at="2027-01-01T00:00:00Z")
    market["volume"] = "not-a-number"
    monkeypatch.setattr(
        PolymarketClient,
        "gamma_get",
        lambda self, path: {"events": [{"id": "e", "markets": [market]}]},
    )

    env = mcp_call("market.search", {"home": home, "query": "bad", "limit": 20})
    assert env.ok, env
    assert env.data["candidates"][0]["volume"] is None


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
