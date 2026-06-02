"""Retry policy constants and classifiers for Polymarket HTTP/JSON-RPC calls."""

from __future__ import annotations

RETRY_MULTIPLIER_SECONDS = 2
RETRY_MAX_SECONDS = 30
RETRY_STOP_AFTER_ATTEMPT = 4
RETRY_HTTP_STATUS_CODES = frozenset({408, 425, 429})
RETRY_JSON_RPC_ERROR_CODES = frozenset({-32005, -32603})


def is_retryable_http_status(status_code: int) -> bool:
    return status_code in RETRY_HTTP_STATUS_CODES or 500 <= status_code <= 599


def is_retryable_json_rpc_error(code: int | None) -> bool:
    return code in RETRY_JSON_RPC_ERROR_CODES


def retry_after_delay(retry_after: str | None, computed_backoff: float) -> float:
    if not retry_after:
        return computed_backoff
    try:
        parsed = float(retry_after.strip())
    except (TypeError, ValueError):
        return computed_backoff
    return min(RETRY_MAX_SECONDS, max(parsed, computed_backoff))


def retry_policy_kwargs() -> dict[str, object]:
    """Return the retry policy as plain config constants (wait/stop names,
    backoff bounds, retryable status/JSON-RPC codes). These mirror tenacity's
    API names for readability but are not a tenacity policy object; the adapter
    applies them with a hand-rolled stdlib backoff loop (see client.py)."""

    return {
        "wait": "wait_random_exponential",
        "multiplier": RETRY_MULTIPLIER_SECONDS,
        "max": RETRY_MAX_SECONDS,
        "stop": "stop_after_attempt",
        "attempts": RETRY_STOP_AFTER_ATTEMPT,
        "retry_http_status_codes": sorted(RETRY_HTTP_STATUS_CODES),
        "retry_json_rpc_error_codes": sorted(RETRY_JSON_RPC_ERROR_CODES),
    }
