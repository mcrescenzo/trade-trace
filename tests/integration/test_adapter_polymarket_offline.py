from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests._mcp_helpers import with_legacy_idempotency_key
from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.adapters.polymarket.config import PolymarketConfig
from trade_trace.adapters.polymarket.errors import AdapterError
from trade_trace.adapters.polymarket.retry import retry_policy_kwargs
from trade_trace.mcp_server import mcp_call
from trade_trace.tools._market_rows import adapter_cache_hit_row_dict
from trade_trace.tools.adapter_polymarket import (
    _apply_caller_resolution_rule,
    _market_cache_hit,
    _market_payload,
    _normalize_gamma_market,
    _snapshot_from_raw,
)


def test_journal_status_adapter_state_default_offline(tmp_path: Path):
    env = mcp_call("journal.status", {"home": str(tmp_path / "home")})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    data = body["data"]
    assert data["outbound_network_active"] is False
    assert data["adapter_state"] == {
        "polymarket": {
            "enabled": False,
            "configured_endpoints": {"gamma_base_url": False, "polygon_rpc_url": False},
            "cached_markets_count": 0,
            "last_successful_fetch_at": None,
        }
    }


def test_journal_init_status_schema_with_adapter_foundation(tmp_path: Path):
    home = str(tmp_path / "home")
    for tool, args in (
        ("journal.init", {"home": home}),
        ("journal.status", {"home": home}),
        ("journal.schema", {}),
    ):
        env = mcp_call(tool, args)
        assert env.ok, env
        if tool != "journal.schema":
            assert env.data["outbound_network_active"] is False


def test_journal_init_reread_reports_enabled_adapter_without_endpoint_values(tmp_path: Path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    assert mcp_call(
        "journal.config_set",
        with_legacy_idempotency_key("journal.config_set", {
            "home": home,
            "key": "network.polymarket.enabled",
            "value": "true",
            "confirm": True,
        }),
    ).ok
    assert mcp_call(
        "journal.config_set",
        with_legacy_idempotency_key("journal.config_set", {
            "home": home,
            "key": "network.polymarket.polygon_rpc_url",
            "value": "https://polygon-rpc.com/rpc/super-secret-key?token=***",
            "confirm": True,
        }),
    ).ok

    env = mcp_call("journal.init", {"home": home})
    assert env.ok, env
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["data"]["outbound_network_active"] is True
    assert body["data"]["adapter_state"] == {
        "polymarket": {
            "enabled": True,
            "configured_endpoints": {"gamma_base_url": False, "polygon_rpc_url": True},
            "cached_markets_count": 0,
            "last_successful_fetch_at": None,
        }
    }
    assert "super-secret-key" not in str(env.model_dump(mode="json"))


def test_polymarket_client_disabled_by_default_fails_closed():
    client = PolymarketClient(PolymarketConfig())
    try:
        client.check_resolution_available()
    except AdapterError as exc:
        assert exc.code.value == "ADAPTER_DISABLED"
        assert exc.details["config_key"] == "network.polymarket.enabled"
    else:  # pragma: no cover
        raise AssertionError("expected disabled adapter error")


def test_retry_policy_shape_is_exposed():
    assert retry_policy_kwargs()["multiplier"] == 2
    assert retry_policy_kwargs()["max"] == 30
    assert retry_policy_kwargs()["attempts"] == 4


def test_market_cache_policy_enforces_state_ttls():
    assert _market_cache_hit(
        "open",
        '{"adapter_cached_at":"2026-05-25T12:00:00.000Z"}',
        None,
        now="2026-05-25T12:30:00.000Z",
    ) is True
    assert _market_cache_hit(
        "open",
        '{"adapter_cached_at":"2026-05-25T12:00:00.000Z"}',
        None,
        now="2026-05-25T13:01:00.000Z",
    ) is False
    assert _market_cache_hit(
        "resolving",
        '{"adapter_cached_at":"2026-05-25T12:00:00.000Z"}',
        None,
        now="2026-05-25T12:04:59.000Z",
    ) is True
    assert _market_cache_hit(
        "ambiguous",
        '{"adapter_cached_at":"2026-05-25T12:00:00.000Z"}',
        None,
        now="2026-05-25T12:00:01.000Z",
    ) is False


def test_market_cache_hit_row_surface_stays_narrow_and_ordered():
    row = (
        "mkt_1",
        "polymarket",
        "ext-1",
        "Title",
        "Question?",
        "https://example.invalid/market/ext-1",
        "open",
        "clob",
        "market_contract",
        None,
        "adapter",
        '{"adapter":"polymarket"}',
        '{"raw":true}',
        "2026-05-25T12:00:00.000Z",
    )

    data = adapter_cache_hit_row_dict(row) | {"cache_hit": True, "state_changed": False}

    assert list(data) == [
        "id",
        "source",
        "external_id",
        "title",
        "question",
        "url",
        "state",
        "mechanism",
        "resolution_source",
        "ambiguity_kind",
        "bound_via",
        "metadata_json",
        "venue_metadata_json",
        "created_at",
        "cache_hit",
        "state_changed",
    ]


def test_adapter_normalizes_false_like_booleans_and_token_id_string_variants():
    market = _market_payload(
        {
            "id": "m1",
            "question": "Question?",
            "outcomes": '["Yes","No"]',
            "tokenIds": '["yes-token","no-token"]',
            "negRisk": "false",
            "active": "false",
            "acceptingOrders": "0",
        },
        "m1",
    )
    metadata = json.loads(market["metadata_json"])

    assert metadata["negative_risk"]["enabled"] is False
    assert metadata["market_microstructure"]["tradable"] is False
    assert metadata["market_microstructure"]["accepting_orders"] is False
    assert metadata["polymarket_identity"]["outcome_token_ids_by_label"] == {"yes": "yes-token", "no": "no-token"}
    assert _normalize_gamma_market({"token_ids": '["a","b"]'}, "m2")["token_ids"] == ["a", "b"]
    snap = _snapshot_from_raw({"bestBid": "0.1", "bestAsk": "0.2", "active": "false", "accepting_orders": "false"})
    assert snap["metadata_json"]["tradable"] is False
    assert snap["metadata_json"]["accepting_orders"] is False


def test_snapshot_price_marks_to_book_mid_not_off_book_last_trade():
    """ax-dogfood AX-027: `snapshots.price` is the canonical YES mark the
    positions projection values open positions against. When a live two-sided
    book exists, that mark must be the within-book mid, NOT `lastTradePrice`,
    which can be a stale print outside the current bid/ask. A live ETH market
    printed lastTrade=0.49 while the book was 0.41/0.44 — marking a 0.44 entry
    against 0.49 reported +PnL on a position the mid said was underwater."""
    snap = _snapshot_from_raw({"bestBid": "0.41", "bestAsk": "0.44", "lastTradePrice": "0.49"})
    assert snap["mid"] == pytest.approx(0.425)
    # price must agree with the same snapshot's mid / implied_probability,
    # not the off-book last trade (0.49, which is above the 0.44 ask).
    assert snap["price"] == pytest.approx(0.425)
    assert snap["implied_probability"] == pytest.approx(0.425)
    assert snap["price"] != pytest.approx(0.49)


def test_snapshot_price_falls_back_to_last_trade_without_two_sided_book():
    """When no two-sided book is present the mid is undefined, so `price`
    falls back to the last/raw price rather than dropping the only mark."""
    snap = _snapshot_from_raw({"lastTradePrice": "0.33"})
    assert snap["mid"] == pytest.approx(0.33)
    assert snap["price"] == pytest.approx(0.33)


def test_adapter_market_payload_maps_description_to_rule_text():
    """trade-trace-n33z (was AX-037 root cause): Polymarket carries the
    resolution prose in `description`, not the `resolutionCriteria`/`rules` keys.
    The adapter now reads `description` into the structured
    `resolution_rule.text` so the criterion an agent needs to forecast travels
    in the structured field instead of being null while the rule sits unreadable
    in venue_metadata_json.description."""
    rule_text = "Resolves YES per some venue page; full rule lives here."
    market = _market_payload(
        {
            "id": "m1",
            "question": "Will X happen?",
            "outcomes": '["Yes","No"]',
            "description": rule_text,
        },
        "m1",
    )
    metadata = json.loads(market["metadata_json"])
    assert metadata["resolution_rule"]["text"] == rule_text
    assert metadata["resolution_rule"]["provenance"] == "polymarket_gamma_payload"


def test_adapter_bind_preserves_caller_resolution_rule_text_when_venue_has_none():
    """ax-dogfood AX-037: the adapter bind path silently dropped a
    caller-supplied resolution_rule_text — the Gamma-derived resolution_rule
    (text=null, since Polymarket's rule is in `description`) overwrote it, so
    the documented n33z workaround ("the agent can just supply the rule text")
    was ineffective on the path a live bot uses. The manual path preserved it.
    Now a null/blank venue text is filled from the caller's text, marked
    caller_supplied; venue text (when present) still wins."""
    venue_null = {"resolution_rule": {"text": None, "source": "https://x", "provenance": "polymarket_gamma_payload"}}

    # 1) resolution_rule_text fills a null venue text.
    filled = _apply_caller_resolution_rule(json.loads(json.dumps(venue_null)), {"resolution_rule_text": "Agent-supplied rule."})
    assert filled["resolution_rule"]["text"] == "Agent-supplied rule."
    assert filled["resolution_rule"]["provenance"] == "caller_supplied"
    assert filled["resolution_rule"]["source"] == "https://x"

    # 2) nested resolution_rule.text also fills.
    nested = _apply_caller_resolution_rule(json.loads(json.dumps(venue_null)), {"resolution_rule": {"text": "Nested rule."}})
    assert nested["resolution_rule"]["text"] == "Nested rule."

    # 3) venue-supplied text always wins; caller text does not clobber it.
    venue_present = {"resolution_rule": {"text": "Venue rule.", "provenance": "polymarket_gamma_payload"}}
    kept = _apply_caller_resolution_rule(json.loads(json.dumps(venue_present)), {"resolution_rule_text": "Agent rule."})
    assert kept["resolution_rule"]["text"] == "Venue rule."
    assert kept["resolution_rule"]["provenance"] == "polymarket_gamma_payload"

    # 4) blank/absent caller text is a no-op (null preserved, no fake provenance).
    untouched = _apply_caller_resolution_rule(json.loads(json.dumps(venue_null)), {"resolution_rule_text": "   "})
    assert untouched["resolution_rule"]["text"] is None
    assert untouched["resolution_rule"]["provenance"] == "polymarket_gamma_payload"
    assert _apply_caller_resolution_rule(json.loads(json.dumps(venue_null)), {})["resolution_rule"]["text"] is None


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, *, headers: dict[str, str] | None = None, invalid_json: bool = False) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._invalid_json = invalid_json

    def json(self) -> Any:
        if self._invalid_json:
            raise ValueError("invalid json")
        return self._payload


class _FakeHttpClient:
    def __init__(self, owner: _FakePolymarketClient) -> None:
        self.owner = owner

    def __enter__(self) -> _FakeHttpClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def get(self, _url: str) -> _FakeResponse:
        self.owner.calls.append("get")
        next_value = self.owner.responses.pop(0)
        if isinstance(next_value, BaseException):
            raise next_value
        return next_value

    def post(self, _url: str, *, json: dict[str, Any]) -> _FakeResponse:
        self.owner.calls.append(f"post:{json['method']}")
        next_value = self.owner.responses.pop(0)
        if isinstance(next_value, BaseException):
            raise next_value
        return next_value


class _FakePolymarketClient(PolymarketClient):
    def __init__(self, responses: list[Any], *, polygon_rpc_url: str | None = None) -> None:
        super().__init__(
            PolymarketConfig(
                enabled=True,
                gamma_base_url="https://gamma-api.polymarket.com",
                polygon_rpc_url=polygon_rpc_url,
            )
        )
        self.responses = responses
        self.calls: list[str] = []
        self.sleeps: list[tuple[int, str | None]] = []

    def _client(self) -> Any:
        return _FakeHttpClient(self)

    def _sleep_before_retry(self, attempt_index: int, retry_after: str | None = None) -> None:
        self.sleeps.append((attempt_index, retry_after))


def test_get_json_retries_retryable_http_status_then_returns_payload():
    client = _FakePolymarketClient([
        _FakeResponse(429, {"error": "rate"}, headers={"Retry-After": "3"}),
        _FakeResponse(200, {"ok": True}),
    ])

    assert client.get_json("https://gamma-api.polymarket.com/markets/1") == {"ok": True}
    assert client.calls == ["get", "get"]
    assert client.sleeps == [(0, "3")]


def test_get_json_fails_closed_on_non_retryable_4xx_without_parsing_success():
    client = _FakePolymarketClient([_FakeResponse(404, {"looks": "valid"})])

    try:
        client.get_json("https://gamma-api.polymarket.com/markets/missing?api_key=secret")
    except AdapterError as exc:
        assert exc.code.value == "ADAPTER_PROTOCOL_ERROR"
        assert exc.details["status_code"] == 404
        assert exc.details["endpoint"] == "gamma-api.polymarket.com/markets/missing"
    else:  # pragma: no cover
        raise AssertionError("expected non-retryable 4xx adapter error")


def test_get_json_retries_transport_errors_with_bounded_attempts():
    client = _FakePolymarketClient([
        httpx.ConnectError("boom"),
        httpx.ConnectError("boom"),
        _FakeResponse(200, {"ok": True}),
    ])

    assert client.get_json("https://gamma-api.polymarket.com/markets/1") == {"ok": True}
    assert client.calls == ["get", "get", "get"]
    assert client.sleeps == [(0, None), (1, None)]


def test_get_json_invalid_json_is_protocol_error_not_success():
    client = _FakePolymarketClient([_FakeResponse(200, invalid_json=True)])

    try:
        client.get_json("https://gamma-api.polymarket.com/markets/1")
    except AdapterError as exc:
        assert exc.code.value == "ADAPTER_PROTOCOL_ERROR"
        assert exc.details["status_code"] == 200
    else:  # pragma: no cover
        raise AssertionError("expected invalid JSON adapter error")


def test_polygon_rpc_retries_retryable_json_rpc_error():
    client = _FakePolymarketClient(
        [
            _FakeResponse(200, {"error": {"code": -32005, "message": "rate limited"}}),
            _FakeResponse(200, {"result": "0x1"}),
        ],
        polygon_rpc_url="https://polygon-rpc.com/rpc/secret-token",
    )

    assert client.polygon_rpc("eth_call", []) == {"result": "0x1"}
    assert client.calls == ["post:eth_call", "post:eth_call"]
    assert client.sleeps == [(0, None)]


def test_polygon_rpc_http_and_payload_retries_share_attempt_budget():
    client = _FakePolymarketClient(
        [
            _FakeResponse(429, {"error": "rate"}, headers={"Retry-After": "2"}),
            _FakeResponse(200, {"error": {"code": -32005, "message": "rate limited"}}),
            _FakeResponse(200, {"result": "0x1"}),
        ],
        polygon_rpc_url="https://polygon-rpc.com/rpc/secret-token",
    )

    assert client.polygon_rpc("eth_call", []) == {"result": "0x1"}
    assert client.calls == ["post:eth_call", "post:eth_call", "post:eth_call"]
    assert client.sleeps == [(0, "2"), (1, None)]


def test_polygon_rpc_fails_closed_on_non_retryable_http_4xx():
    client = _FakePolymarketClient(
        [_FakeResponse(403, {"error": "forbidden"})],
        polygon_rpc_url="https://polygon-rpc.com/rpc/secret-token",
    )

    try:
        client.polygon_rpc("eth_call", [])
    except AdapterError as exc:
        assert exc.code.value == "ADAPTER_PROTOCOL_ERROR"
        assert exc.details["status_code"] == 403
        assert exc.details["endpoint"] == "polygon-rpc.com/rpc/secret-token"
    else:  # pragma: no cover
        raise AssertionError("expected polygon RPC 4xx adapter error")
