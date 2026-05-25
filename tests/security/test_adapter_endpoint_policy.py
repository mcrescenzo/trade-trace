from __future__ import annotations

from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.adapters.polymarket.config import PolymarketConfig
from trade_trace.adapters.polymarket.errors import AdapterError


def test_gamma_fetch_rejects_non_https_before_http_client():
    client = PolymarketClient(PolymarketConfig(enabled=True, gamma_base_url="http://gamma-api.polymarket.com"))

    try:
        client.gamma_get("/markets/1")
    except AdapterError as exc:
        assert exc.code.value == "CONFIG_REQUIRED"
        assert exc.details["tls_required"] is True
        assert exc.details["endpoint"] == "gamma-api.polymarket.com/markets/1"
    else:  # pragma: no cover
        raise AssertionError("expected TLS policy failure")


def test_gamma_fetch_rejects_unallowed_host_before_http_client():
    client = PolymarketClient(PolymarketConfig(enabled=True, gamma_base_url="https://evil.example"))

    try:
        client.gamma_get("/markets/1")
    except AdapterError as exc:
        assert exc.code.value == "CONFIG_REQUIRED"
        assert exc.details["allowed_host"] is False
        assert exc.details["endpoint"] == "evil.example/markets/1"
    else:  # pragma: no cover
        raise AssertionError("expected allowed-host policy failure")


def test_polygon_rpc_rejects_non_https_before_http_client():
    client = PolymarketClient(PolymarketConfig(enabled=True, polygon_rpc_url="http://polygon-rpc.com/rpc?token=SECRET"))

    try:
        client.polygon_rpc("eth_blockNumber")
    except AdapterError as exc:
        assert exc.code.value == "CONFIG_REQUIRED"
        assert exc.details["tls_required"] is True
        assert exc.details["endpoint"] == "polygon-rpc.com/rpc"
        assert "SECRET" not in repr(exc.details)
    else:  # pragma: no cover
        raise AssertionError("expected TLS policy failure")
