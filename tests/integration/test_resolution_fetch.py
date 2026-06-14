from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._mcp_helpers import with_legacy_idempotency_key
from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.contracts.envelope import ErrorEnvelope, SuccessEnvelope
from trade_trace.mcp_server import mcp_call

FIXTURES = Path(__file__).parent / "fixtures" / "polymarket"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _enable_adapter(home: str, *, polygon_rpc_url: str | None = None) -> None:
    assert mcp_call(
        "journal.config_set",
        with_legacy_idempotency_key("journal.config_set", {"home": home, "key": "network.polymarket.enabled", "value": "true", "confirm": True}),
    ).ok
    if polygon_rpc_url is not None:
        assert mcp_call(
            "journal.config_set",
            with_legacy_idempotency_key("journal.config_set", {"home": home, "key": "network.polymarket.polygon_rpc_url", "value": polygon_rpc_url, "confirm": True}),
        ).ok


def _legacy_call(tool: str, args: dict):
    return mcp_call(tool, with_legacy_idempotency_key(tool, args))


def test_outcome_fetch_disabled_fails_closed(tmp_path: Path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    market = mcp_call(
        "market.bind",
        {"home": home, "source": "polymarket", "external_id": "pm-outcome", "state": "resolved", "mechanism": "clob", "bound_via": "manual"},
    )
    assert market.ok, market
    assert isinstance(market, SuccessEnvelope)
    env = _legacy_call("outcome.fetch", {"home": home, "market_id": market.data["id"]})
    assert not env.ok
    assert isinstance(env, ErrorEnvelope)
    assert env.error.code == "ADAPTER_DISABLED"


def test_outcome_fetch_enabled_requires_polygon_rpc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)
    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: _fixture("market_binary_resolved_yes.json"))
    market = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": "pm-res-yes"})
    assert market.ok, market
    assert isinstance(market, SuccessEnvelope)

    env = _legacy_call("outcome.fetch", {"home": home, "market_id": market.data["id"]})

    assert not env.ok
    assert isinstance(env, ErrorEnvelope)
    assert env.error.code == "CONFIG_REQUIRED"
    assert env.error.details["config_key"] == "network.polymarket.polygon_rpc_url"
    # trade-trace-isqo: when polygon_rpc_url is unset, outcome.fetch must signpost
    # the no-RPC Gamma resolution-evidence route (snapshot.fetch) instead of
    # dead-ending an automated resolution feeder.
    assert env.error.details["no_rpc_resolution_evidence_route"] == "snapshot.fetch"
    hint = env.error.details["hint"]
    assert "snapshot.fetch" in hint
    assert "resolution.add" in hint


def test_outcome_fetch_enabled_records_fixture_resolution_idempotently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home, polygon_rpc_url="https://polygon.example/rpc/secret-token")
    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: _fixture("market_binary_resolved_yes.json"))
    monkeypatch.setattr(PolymarketClient, "polygon_rpc", lambda self, method, params=None: _fixture("polygon_resolution_tx.json"))

    market = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": "pm-res-yes"})
    assert market.ok, market
    assert isinstance(market, SuccessEnvelope)

    first = _legacy_call("outcome.fetch", {"home": home, "market_id": market.data["id"]})
    second = _legacy_call("outcome.fetch", {"home": home, "market_id": market.data["id"]})

    assert first.ok, first
    assert isinstance(first, SuccessEnvelope)
    assert first.data["status"] == "resolved_final"
    assert first.data["outcome_label"] == "Yes"
    assert "secret-token" not in first.data["metadata_json"]
    assert second.ok, second
    assert isinstance(second, SuccessEnvelope)
    assert second.data["id"] == first.data["id"]
    assert second.data["idempotent_replay"] is True
