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


def _manual_market(home: str, external_id: str = "pm-snap") -> str:
    env = mcp_call(
        "market.bind",
        {"home": home, "source": "polymarket", "external_id": external_id, "state": "open", "mechanism": "clob", "bound_via": "manual"},
    )
    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    return env.data["id"]


def _enable_adapter(home: str) -> None:
    assert mcp_call(
        "journal.config_set",
        with_legacy_idempotency_key("journal.config_set", {"home": home, "key": "network.polymarket.enabled", "value": "true", "confirm": True}),
    ).ok


def _legacy_call(tool: str, args: dict):
    return mcp_call(tool, with_legacy_idempotency_key(tool, args))


def test_snapshot_fetch_disabled_fails_closed(tmp_path: Path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    market_id = _manual_market(home)
    env = _legacy_call("snapshot.fetch", {"home": home, "market_id": market_id})
    assert not env.ok
    assert isinstance(env, ErrorEnvelope)
    assert env.error.code == "ADAPTER_DISABLED"


def test_snapshot_fetch_series_disabled_fails_closed(tmp_path: Path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    market_id = _manual_market(home)
    env = _legacy_call(
        "snapshot.fetch_series",
        {"home": home, "market_id": market_id, "from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"},
    )
    assert not env.ok
    assert isinstance(env, ErrorEnvelope)
    assert env.error.code == "ADAPTER_DISABLED"


def test_snapshot_fetch_enabled_captures_fixture_book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    market_id = _manual_market(home, external_id="pm-book")
    _enable_adapter(home)
    calls: list[str] = []

    def fake_gamma_get(self: PolymarketClient, path: str):
        calls.append(path)
        return _fixture("snapshot_thick_book.json")

    monkeypatch.setattr(PolymarketClient, "gamma_get", fake_gamma_get)

    env = _legacy_call("snapshot.fetch", {"home": home, "market_id": market_id, "at": "now"})

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert calls == ["/markets/pm-book"]
    assert env.data["instrument_id"] == market_id
    assert env.data["bid"] == 0.61
    assert env.data["ask"] == 0.63
    assert env.data["mid"] == pytest.approx(0.62)
    assert env.data["implied_probability"] == pytest.approx(0.62)


def test_snapshot_fetch_derives_from_live_gamma_market_payload_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    market_id = _manual_market(home, external_id="540844")
    _enable_adapter(home)
    calls: list[str] = []

    def fake_gamma_get(self: PolymarketClient, path: str):
        calls.append(path)
        return {
            "id": "540844",
            "question": "Live Gamma style market?",
            "outcomes": '["Yes","No"]',
            "clobTokenIds": '["token-yes","token-no"]',
            "bestBid": "0.41",
            "bestAsk": "0.43",
            "lastTradePrice": "0.42",
            "volume": "12345.67",
            "liquidity": "890.12",
        }

    monkeypatch.setattr(PolymarketClient, "gamma_get", fake_gamma_get)

    env = _legacy_call("snapshot.fetch", {"home": home, "market_id": market_id, "at": "now"})

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert calls == ["/markets/540844"]
    assert all(not path.endswith("/book") for path in calls)
    assert env.data["bid"] == 0.41
    assert env.data["ask"] == 0.43
    assert env.data["mid"] == pytest.approx(0.42)
    assert env.data["volume"] == "12345.67"


@pytest.mark.parametrize("field", ["bestBid", "bestAsk", "price"])
def test_snapshot_fetch_rejects_invalid_numeric_book_fields_with_typed_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    market_id = _manual_market(home, external_id=f"pm-invalid-{field}")
    _enable_adapter(home)
    raw = _fixture("snapshot_thick_book.json") | {field: "abc"}
    if field == "price":
        raw.pop("bestBid", None)
        raw.pop("bestAsk", None)

    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: raw)

    env = _legacy_call("snapshot.fetch", {"home": home, "market_id": market_id, "at": "now"})
    assert not env.ok
    assert isinstance(env, ErrorEnvelope)
    assert env.error.code == "ADAPTER_PROTOCOL_ERROR"


def test_snapshot_fetch_blank_and_missing_numeric_book_fields_stay_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    market_id = _manual_market(home, external_id="pm-blank-book")
    _enable_adapter(home)

    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: {"volume": "10"})

    env = _legacy_call("snapshot.fetch", {"home": home, "market_id": market_id, "at": "now"})
    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert env.data["bid"] is None
    assert env.data["ask"] is None
    assert env.data["price"] is None
    assert env.data["mid"] is None


def test_snapshot_fetch_blank_string_numeric_book_fields_stay_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    market_id = _manual_market(home, external_id="pm-blank-string-book")
    _enable_adapter(home)

    monkeypatch.setattr(
        PolymarketClient,
        "gamma_get",
        lambda self, path: {"bestBid": "", "bestAsk": "", "price": "", "volume": "10"},
    )

    env = _legacy_call("snapshot.fetch", {"home": home, "market_id": market_id, "at": "now"})
    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert env.data["bid"] is None
    assert env.data["ask"] is None
    assert env.data["price"] is None
    assert env.data["mid"] is None


def test_snapshot_fetch_series_enabled_writes_each_fixture_point(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    market_id = _manual_market(home, external_id="pm-series")
    _enable_adapter(home)

    points = [
        _fixture("snapshot_thin_book.json") | {"captured_at": "2026-01-01T00:00:00Z"},
        _fixture("snapshot_amm_curve.json") | {"captured_at": "2026-01-01T01:00:00Z"},
    ]
    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: {"points": points})

    env = _legacy_call(
        "snapshot.fetch_series",
        {"home": home, "market_id": market_id, "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T02:00:00Z"},
    )

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert env.data["count"] == 2
    assert [item["captured_at"] for item in env.data["items"]] == ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"]
