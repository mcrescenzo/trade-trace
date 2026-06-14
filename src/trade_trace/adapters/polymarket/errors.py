"""Polymarket adapter error envelope helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from trade_trace.contracts.errors import ErrorCode

# RPC providers that embed the API key/secret as a URL *path* segment:
#   Alchemy   https://polygon-mainnet.g.alchemy.com/v2/<KEY>
#   Infura    https://polygon-mainnet.infura.io/v3/<KEY>
#   Ankr      https://rpc.ankr.com/polygon/<KEY>
#   QuickNode https://<subdomain>.quicknode.pro/<TOKEN>/
# For these hosts the path itself is credential material, so scrub_endpoint
# drops the path entirely and keeps only host[:port]. Keyless hosts (e.g.
# polygon-rpc.com, gamma-api.polymarket.com) keep their path for debuggability
# — they carry no secret in the path (keys, if any, ride the query string,
# which is always stripped). Keep in sync with the allowlist in client.py.
_PATH_KEYED_RPC_HOST_SUFFIXES = (".alchemy.com", ".infura.io", ".ankr.com", ".quicknode.pro")


def scrub_endpoint(url: str | None) -> str | None:
    """Return host[:port], plus path only for hosts that don't key on the path.

    Strips scheme, credentials, query, and fragment. For known RPC providers
    that embed the API key in the URL path (Alchemy/Infura/Ankr/QuickNode) the
    path is dropped too, so no key material reaches logs, error details, or the
    DB (outcomes.metadata_json).
    """

    if not url:
        return None
    raw = str(url).strip()
    parts = urlsplit(raw if "://" in raw else f"//{raw}")
    host = parts.hostname or ""
    path = parts.path or ""
    if not host and path:
        # Last-resort for malformed values: still drop query/fragment and creds.
        host_path = path.split("@")[-1]
        return host_path or None
    if host and any(host.endswith(suffix) for suffix in _PATH_KEYED_RPC_HOST_SUFFIXES):
        # Path segments on these providers are credential material — drop them.
        path = ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return f"{host}{path}" or None


@dataclass
class AdapterError(Exception):
    code: ErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


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
