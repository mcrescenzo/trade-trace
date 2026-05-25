from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.contracts.envelope import ErrorEnvelope, SuccessEnvelope
from trade_trace.mcp_server import mcp_call


FIXTURES = Path(__file__).parent / "fixtures" / "polymarket"
REQUIRED_FIXTURES = {
    "market_binary_open.json",
    "market_binary_open_amm.json",
    "market_binary_resolved_yes.json",
    "market_binary_resolved_no.json",
    "market_binary_ambiguous.json",
    "market_binary_voided.json",
    "market_binary_disputed.json",
    "market_categorical_rejected.json",
    "market_scalar_rejected.json",
    "snapshot_thick_book.json",
    "snapshot_thin_book.json",
    "snapshot_amm_curve.json",
    "polygon_resolution_tx.json",
}


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _enable_adapter(home: str) -> None:
    assert mcp_call(
        "journal.config_set",
        {"home": home, "key": "network.polymarket.enabled", "value": "true", "confirm": True},
    ).ok


def test_market_bind_manual_disabled_adapter(tmp_path: Path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    env = mcp_call(
        "market.bind",
        {
            "home": home,
            "source": "polymarket",
            "external_id": "pm-manual",
            "state": "open",
            "mechanism": "clob",
            "title": "Manual PM",
            "bound_via": "manual",
        },
    )
    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert env.data["bound_via"] == "manual"


def test_polymarket_fixture_corpus_is_complete_and_parseable():
    names = {p.name for p in FIXTURES.glob("*.json")}
    assert names == REQUIRED_FIXTURES
    for name in REQUIRED_FIXTURES:
        assert isinstance(_fixture(name), dict), name


def test_market_bind_enabled_fetches_fixture_backed_market(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)
    calls: list[str] = []

    def fake_gamma_get(self: PolymarketClient, path: str):
        calls.append(path)
        return _fixture("market_binary_open_amm.json")

    monkeypatch.setattr(PolymarketClient, "gamma_get", fake_gamma_get)

    env = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": "pm-open-amm"})

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert calls == ["/markets/pm-open-amm"]
    assert env.data["source"] == "polymarket"
    assert env.data["external_id"] == "pm-open-amm"
    assert env.data["bound_via"] == "adapter"
    assert env.data["mechanism"] == "amm"


@pytest.mark.parametrize("fixture_name", ["market_categorical_rejected.json", "market_scalar_rejected.json"])
def test_market_bind_rejects_non_binary_polymarket_fixtures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)

    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: _fixture(fixture_name))

    env = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": fixture_name})
    assert not env.ok
    assert isinstance(env, ErrorEnvelope)
    assert env.error.code == "ADAPTER_PROTOCOL_ERROR"
