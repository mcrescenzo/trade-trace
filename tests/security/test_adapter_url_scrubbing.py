from __future__ import annotations

from unittest.mock import Mock, patch

from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.adapters.polymarket.config import PolymarketConfig
from trade_trace.adapters.polymarket.errors import error_details, scrub_endpoint


def test_scrub_endpoint_removes_scheme_credentials_query_fragment_and_key():
    raw = "https://user:secret@polygon.example.com/rpc/v2/APIKEY123?token=LEAK#frag"
    scrubbed = scrub_endpoint(raw)
    assert scrubbed == "polygon.example.com/rpc/v2/APIKEY123"
    assert scrubbed is not None
    # Query-string API keys are common for RPC providers and must not leak.
    assert "token=LEAK" not in scrubbed
    assert "user" not in scrubbed
    assert "secret" not in scrubbed


def test_error_details_strip_body_and_scrub_endpoint():
    details = error_details(
        endpoint="https://rpc.example.test/path?apiKey=SHOULD_NOT_LEAK#frag",
        status_code=429,
        body="sensitive response body",
        response_body="also sensitive",
    )
    assert details == {"status_code": 429, "endpoint": "rpc.example.test/path"}
    rendered = repr(details)
    assert "SHOULD_NOT_LEAK" not in rendered
    assert "sensitive response body" not in rendered


def test_polymarket_response_log_excludes_body_and_scrubs_endpoint():
    client = PolymarketClient(PolymarketConfig(enabled=True))
    client._logger = Mock()

    with patch("trade_trace.adapters.polymarket.client.time.perf_counter", return_value=2.123):
        client._log_response(
            method="GET",
            endpoint="https://user:***@gamma-api.polymarket.com/markets?apiKey=***#frag",
            status_code=500,
            started_at=2.0,
        )

    client._logger.info.assert_called_once()
    message, = client._logger.info.call_args.args
    assert message == "polymarket adapter response"
    payload = client._logger.info.call_args.kwargs["extra"]
    assert payload == {
        "tool": "adapter.polymarket",
        "method": "GET",
        "endpoint": "gamma-api.polymarket.com/markets",
        "status_code": 500,
        "latency_ms": 123,
    }
    rendered = repr(payload)
    assert "body" not in payload
    assert "response_body" not in payload
    assert "secret response body" not in rendered
    assert "apiKey" not in rendered
    assert "user" not in rendered
