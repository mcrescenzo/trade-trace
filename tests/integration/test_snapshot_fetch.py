from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._mcp_helpers import with_legacy_idempotency_key
from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.contracts.envelope import ErrorEnvelope, SuccessEnvelope
from trade_trace.mcp_server import mcp_call
from trade_trace.storage.paths import db_path
from trade_trace.tools.adapter_polymarket import _gamma_request_id, _snapshot_from_raw

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
    assert "liquidity_depth_json" in env.data
    assert env.data["metadata_json"]["tick_size"] is None or "tick_size" in env.data["metadata_json"]


def test_snapshot_from_raw_without_depth_fields_does_not_dump_whole_payload():
    """A closed/sports market payload that carries no book/liquidity/orderBook/
    depth field must NOT have the entire raw Gamma object dumped into
    liquidity_depth_json (ax-dogfood AX-031). A live market with a numeric
    `liquidity` is unchanged; a depthless market stores nothing instead of the
    5KB market blob (conditionId, clobTokenIds, description, …)."""

    resolved_like = {
        "bestBid": 0.999,
        "bestAsk": 1.0,
        "lastTradePrice": 0.999,
        "conditionId": "0xdeadbeef",
        "clobTokenIds": ["111", "222"],
        "description": "Long resolution rule prose " * 50,
        "outcomePrices": ["1", "0"],
        "closed": True,
    }
    snap = _snapshot_from_raw(resolved_like)
    assert snap["liquidity_depth_json"] is None
    # The market metadata must not leak into the depth column.
    assert snap["liquidity_depth_json"] != resolved_like

    live_like = {"bestBid": 0.41, "bestAsk": 0.44, "liquidity": "21232.26239"}
    assert _snapshot_from_raw(live_like)["liquidity_depth_json"] == "21232.26239"


def test_snapshot_add_persists_top_level_snapshot_metadata_fields(tmp_path: Path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    market_id = _manual_market(home, external_id="pm-manual-snapshot-meta")

    env = _legacy_call(
        "snapshot.add",
        {
            "home": home,
            "instrument_id": market_id,
            "captured_at": "2026-01-01T00:00:00Z",
            "source": "manual",
            "implied_probability": 0.55,
            "tick_size": 0.01,
            "fee_rate_bps": 12,
            "rewards": {"daily_rate": "1"},
            "rebates": {"maker": "0"},
            "tradable": False,
            "freshness": {"as_of": "2026-01-01T00:00:00Z", "provenance": "caller_supplied"},
            "depth_provenance": "caller_supplied",
            "metadata_json": {"note": "kept"},
        },
    )

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    with sqlite3.connect(db_path(Path(home))) as conn:
        (metadata_text,) = conn.execute("SELECT metadata_json FROM snapshots WHERE id=?", (env.data["id"],)).fetchone()
    metadata = json.loads(metadata_text)
    assert metadata["note"] == "kept"
    assert metadata["snapshot_metadata"]["tick_size"] == 0.01
    assert metadata["snapshot_metadata"]["fee_rate_bps"] == 12
    assert metadata["snapshot_metadata"]["tradable"] is False
    assert metadata["snapshot_metadata"]["depth_provenance"] == "caller_supplied"


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


def test_snapshot_fetch_normalizes_false_like_booleans_and_persists_wrapped_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    market_id = _manual_market(home, external_id="pm-false-snapshot")
    _enable_adapter(home)

    monkeypatch.setattr(
        PolymarketClient,
        "gamma_get",
        lambda self, path: {"bestBid": "0.10", "bestAsk": "0.20", "active": "false", "acceptingOrders": "0"},
    )

    env = _legacy_call("snapshot.fetch", {"home": home, "market_id": market_id, "at": "now"})

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert env.data["metadata_json"]["tradable"] is False
    assert env.data["metadata_json"]["accepting_orders"] is False
    with sqlite3.connect(db_path(Path(home))) as conn:
        (metadata_text,) = conn.execute("SELECT metadata_json FROM snapshots WHERE id=?", (env.data["id"],)).fetchone()
    metadata = json.loads(metadata_text)
    assert metadata["polymarket_snapshot"]["tradable"] is False
    assert metadata["polymarket_snapshot"]["accepting_orders"] is False


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


# -- market.refresh emits market.refreshed, which must be registered (AX-068) --
# market.refresh re-syncs a bound market row from Gamma and emits a
# `market.refreshed` event. The events log is default-deny: an unregistered
# event type hard-errors ("event_type 'market.refreshed' is not registered in
# events_semantic_keys"). Before AX-068 the event type was never added to
# SEMANTIC_KEYS, so EVERY market.refresh call failed and the tool was wholly
# non-functional. This pins the round-trip.


def test_market_refresh_succeeds_and_emits_registered_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    market_id = _manual_market(home, external_id="540844")
    _enable_adapter(home)

    # Force a cache MISS so refresh actually re-fetches and emits
    # market.refreshed. A freshly bound row is inside the open-market TTL
    # (1h) and would short-circuit as cache_hit without touching the
    # event path — that is exactly why the unregistered-event drift went
    # unnoticed until a stale market was refreshed live (AX-068).
    conn = sqlite3.connect(db_path(Path(home)))
    try:
        conn.execute(
            "UPDATE markets SET created_at='2020-01-01T00:00:00Z', metadata_json='{}' WHERE id=?",
            (market_id,),
        )
        conn.commit()
    finally:
        conn.close()

    def fake_gamma_get(self: PolymarketClient, path: str):
        return {
            "id": "540844",
            "question": "Refreshable market?",
            "outcomes": '["Yes","No"]',
            "clobTokenIds": '["token-yes","token-no"]',
            "bestBid": "0.41",
            "bestAsk": "0.43",
            "lastTradePrice": "0.42",
            "closed": False,
        }

    monkeypatch.setattr(PolymarketClient, "gamma_get", fake_gamma_get)

    env = _legacy_call("market.refresh", {"home": home, "market_id": market_id})

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert env.data["id"] == market_id
    # The market.refreshed event must have been written (default-deny would
    # have raised KeyError -> ErrorEnvelope otherwise).
    conn = sqlite3.connect(db_path(Path(home)))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='market.refreshed'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_market_refreshed_is_registered_in_semantic_keys():
    """Guard the specific drift class: a tool emits an event type the
    default-deny registry rejects. market.refresh emits market.refreshed."""

    from trade_trace.events.semantic_keys import SEMANTIC_KEYS

    assert "market.refreshed" in SEMANTIC_KEYS


# -- _gamma_request_id: prefer gamma_market_id over external_id (AX-009) --
# snapshot.fetch / snapshot.fetch_series / market.refresh build the Gamma
# /markets/{id} URL from the bound market row. Gamma expects the bare numeric
# market id, so a namespaced external_id (e.g. "polymarket:2334107") used to
# 422. When market.bind captured a gamma_market_id, the fetch now uses it.


def test_gamma_request_id_prefers_gamma_market_id():
    meta = json.dumps({"polymarket_identity": {"gamma_market_id": "2334107"}})
    assert _gamma_request_id("polymarket:2334107", meta) == "2334107"


def test_gamma_request_id_falls_back_to_external_id_when_absent():
    assert _gamma_request_id("2334107", None) == "2334107"
    assert _gamma_request_id("2334107", "{}") == "2334107"
    assert _gamma_request_id(
        "2334107", json.dumps({"polymarket_identity": {}})
    ) == "2334107"


def test_gamma_request_id_falls_back_on_malformed_metadata():
    assert _gamma_request_id("2334107", "not-json") == "2334107"
    assert _gamma_request_id("2334107", json.dumps({"polymarket_identity": None})) == "2334107"
