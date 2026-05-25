from __future__ import annotations

from trade_trace.adapters.polymarket.errors import error_details, scrub_endpoint, structured_response_log


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


def test_structured_response_log_excludes_body():
    payload = structured_response_log(status_code=500, latency_ms=123)
    assert payload == {"status_code": 500, "latency_ms": 123}
    assert "body" not in payload
