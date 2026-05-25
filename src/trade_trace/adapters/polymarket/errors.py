"""Polymarket adapter error envelope helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from trade_trace.contracts.errors import ErrorCode


def scrub_endpoint(url: str | None) -> str | None:
    """Return host + path only; strip scheme, credentials, query, fragment."""

    if not url:
        return None
    raw = str(url).strip()
    parts = urlsplit(raw if "://" in raw else f"//{raw}")
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path or ""
    if not host and path:
        # Last-resort for malformed values: still drop query/fragment and creds.
        host_path = path.split("@")[-1]
        return host_path or None
    return f"{host}{path}" or None


@dataclass
class AdapterError(Exception):
    code: ErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def to_envelope(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, "details": dict(self.details)}


def error_details(*, endpoint: str | None = None, **details: Any) -> dict[str, Any]:
    clean = {k: v for k, v in details.items() if v is not None and k not in {"body", "response_body"}}
    scrubbed = scrub_endpoint(endpoint)
    if scrubbed:
        clean["endpoint"] = scrubbed
    return clean


def classify_http_status(status_code: int) -> ErrorCode:
    if status_code == 429:
        return ErrorCode.ADAPTER_RATE_LIMITED
    if status_code >= 500:
        return ErrorCode.EXTERNAL_API_ERROR
    return ErrorCode.ADAPTER_PROTOCOL_ERROR


def structured_response_log(status_code: int, latency_ms: int) -> dict[str, int]:
    """Safe log payload: status + latency only; never include response bodies."""

    return {"status_code": int(status_code), "latency_ms": int(latency_ms)}
