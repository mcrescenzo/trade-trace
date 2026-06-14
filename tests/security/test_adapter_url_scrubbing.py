from __future__ import annotations

from unittest.mock import Mock, patch

from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.adapters.polymarket.config import PolymarketConfig
from trade_trace.adapters.polymarket.errors import error_details, scrub_endpoint


def test_scrub_endpoint_removes_scheme_credentials_query_and_fragment():
    # Keyless host: scheme, userinfo, query, fragment stripped; path preserved
    # for debuggability (no secret rides the path on this host).
    raw = "https://user:secret@polygon-rpc.com/rpc?token=LEAK#frag"
    scrubbed = scrub_endpoint(raw)
    assert scrubbed == "polygon-rpc.com/rpc"
    assert scrubbed is not None
    assert "token=LEAK" not in scrubbed
    assert "user" not in scrubbed
    assert "secret" not in scrubbed


def test_scrub_endpoint_drops_path_segment_keys_for_known_rpc_providers():
    """trade-trace-2sm7 regression: path-embedded RPC keys must not survive.

    Alchemy /v2/KEY, Infura /v3/KEY, Ankr /polygon/KEY, and QuickNode
    /path/SECRET all carry the credential in the URL path. scrub_endpoint must
    strip the path for these providers so the key never reaches logs, error
    details, or outcomes.metadata_json.
    """

    cases = [
        # (raw_url, expected_scrub, key_material)
        ("https://polygon-mainnet.g.alchemy.com/v2/ALCHEMY_KEY_abc123",
         "polygon-mainnet.g.alchemy.com", "ALCHEMY_KEY_abc123"),
        ("https://polygon-mainnet.infura.io/v3/INFURA_KEY_def456",
         "polygon-mainnet.infura.io", "INFURA_KEY_def456"),
        ("https://rpc.ankr.com/polygon/ANKR_KEY_ghi789",
         "rpc.ankr.com", "ANKR_KEY_ghi789"),
        ("https://my-endpoint.matic.quicknode.pro/QUICKNODE_SECRET_jkl012/",
         "my-endpoint.matic.quicknode.pro", "QUICKNODE_SECRET_jkl012"),
    ]
    for raw, expected, key in cases:
        scrubbed = scrub_endpoint(raw)
        assert scrubbed == expected, f"{raw} -> {scrubbed!r}"
        assert scrubbed is not None
        assert key not in scrubbed, f"key {key!r} leaked through scrub_endpoint"


def test_scrub_endpoint_drops_path_key_through_error_details_and_log():
    """The three documented leak sites all flow through scrub_endpoint, so the
    Alchemy key must be absent from error_details output too."""

    raw = "https://polygon-mainnet.g.alchemy.com/v2/ALCHEMY_KEY_abc123"
    details = error_details(endpoint=raw, status_code=500)
    assert details["endpoint"] == "polygon-mainnet.g.alchemy.com"
    assert "ALCHEMY_KEY_abc123" not in repr(details)


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
