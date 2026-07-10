"""Lazy opt-in Polymarket client foundation.

`httpx` is imported only in this adapter module; retries use a hand-rolled
stdlib backoff (`random` + `time.sleep`), not a third-party retry library.
Constructing the client performs no network I/O; methods fail closed before any
outbound call if adapter config is disabled or required endpoint config is missing.
"""

from __future__ import annotations

import random
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from trade_trace.adapters.polymarket.config import USER_AGENT, PolymarketConfig
from trade_trace.adapters.polymarket.errors import AdapterError, classify_http_status, error_details
from trade_trace.adapters.polymarket.retry import (
    RETRY_MAX_SECONDS,
    RETRY_MULTIPLIER_SECONDS,
    RETRY_STOP_AFTER_ATTEMPT,
    is_retryable_http_status,
    is_retryable_json_rpc_error,
    retry_after_delay,
)
from trade_trace.contracts.errors import ErrorCode
from trade_trace.logging import get_logger

_ALLOWED_GAMMA_HOSTS = {"gamma-api.polymarket.com"}
_ALLOWED_POLYGON_RPC_HOST_SUFFIXES = (".polygon-rpc.com", ".alchemy.com", ".infura.io", ".ankr.com", ".quicknode.pro")
_ALLOWED_POLYGON_RPC_HOSTS = {"polygon-rpc.com", "rpc.ankr.com"}


def _host_allowed(host: str, *, gamma: bool) -> bool:
    host = host.lower().rstrip(".")
    if gamma:
        return host in _ALLOWED_GAMMA_HOSTS
    return host in _ALLOWED_POLYGON_RPC_HOSTS or any(host.endswith(suffix) for suffix in _ALLOWED_POLYGON_RPC_HOST_SUFFIXES)


class PolymarketClient:
    def __init__(self, config: PolymarketConfig) -> None:
        self.config = config
        self._logger = get_logger("trade_trace.adapters.polymarket")

    def _validate_endpoint(self, url: str, *, gamma: bool) -> None:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host:
            raise AdapterError(
                ErrorCode.CONFIG_REQUIRED,
                "Polymarket adapter endpoints must use HTTPS",
                details=error_details(endpoint=url, tls_required=True),
            )
        if not _host_allowed(host, gamma=gamma):
            raise AdapterError(
                ErrorCode.CONFIG_REQUIRED,
                "Polymarket adapter endpoint host is not allowed",
                details=error_details(endpoint=url, allowed_host=False),
            )

    def _log_response(self, *, method: str, endpoint: str, status_code: int, started_at: float) -> None:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        self._logger.info(
            "polymarket adapter response",
            extra={"tool": "adapter.polymarket", "method": method, "endpoint": error_details(endpoint=endpoint).get("endpoint"), "status_code": status_code, "latency_ms": latency_ms},
        )

    def _require_enabled(self) -> None:
        if not self.config.enabled:
            raise AdapterError(
                ErrorCode.ADAPTER_DISABLED,
                "Polymarket adapter is disabled; set network.polymarket.enabled=true to opt in",
                details={"config_key": "network.polymarket.enabled"},
            )

    def _require_polygon_rpc(self) -> str:
        self._require_enabled()
        if not self.config.polygon_rpc_url:
            raise AdapterError(
                ErrorCode.CONFIG_REQUIRED,
                "Polygon RPC URL is required for resolution/on-chain paths",
                details={"config_key": "network.polymarket.polygon_rpc_url"},
            )
        return self.config.polygon_rpc_url

    def check_resolution_available(self) -> dict[str, Any]:
        """Minimal resolution/on-chain path guard used by downstream tools/tests."""

        endpoint = self._require_polygon_rpc()
        self._validate_endpoint(endpoint, gamma=False)
        return {"available": True, "endpoint": error_details(endpoint=endpoint)["endpoint"]}

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(self.config.timeout_seconds),
            headers={"User-Agent": USER_AGENT},
            verify=True,
        )

    def _backoff_seconds(self, attempt_index: int, retry_after: str | None = None) -> float:
        computed = min(RETRY_MAX_SECONDS, RETRY_MULTIPLIER_SECONDS * (2 ** attempt_index))
        jittered = random.uniform(0.0, computed)
        return retry_after_delay(retry_after, jittered)

    def _sleep_before_retry(self, attempt_index: int, retry_after: str | None = None) -> None:
        time.sleep(self._backoff_seconds(attempt_index, retry_after))

    def _request_json(
        self,
        *,
        endpoint: str,
        method: str,
        send: Any,
        timeout_message: str,
        transport_message: str,
        http_message: str,
        invalid_json_message: str,
        retry_payload: Any | None = None,
    ) -> Any:
        """Send one HTTP/JSON request shape with shared bounded retry semantics.

        JSON-RPC payload-level errors are intentionally not handled here; callers
        that understand the parsed payload keep that retry/error behavior explicit.
        """

        last_transport_error: httpx.TransportError | None = None
        for attempt_index in range(RETRY_STOP_AFTER_ATTEMPT):
            try:
                with self._client() as client:
                    started_at = time.perf_counter()
                    response = send(client)
                    self._log_response(method=method, endpoint=endpoint, status_code=response.status_code, started_at=started_at)
            except httpx.ReadTimeout as exc:
                last_transport_error = exc
                if attempt_index < RETRY_STOP_AFTER_ATTEMPT - 1:
                    self._sleep_before_retry(attempt_index)
                    continue
                raise AdapterError(ErrorCode.ADAPTER_TIMEOUT, timeout_message, details=error_details(endpoint=endpoint)) from exc
            except httpx.TransportError as exc:
                last_transport_error = exc
                if attempt_index < RETRY_STOP_AFTER_ATTEMPT - 1:
                    self._sleep_before_retry(attempt_index)
                    continue
                raise AdapterError(ErrorCode.EXTERNAL_API_ERROR, transport_message, details=error_details(endpoint=endpoint)) from exc

            if response.status_code >= 400:
                if is_retryable_http_status(response.status_code) and attempt_index < RETRY_STOP_AFTER_ATTEMPT - 1:
                    self._sleep_before_retry(attempt_index, response.headers.get("Retry-After"))
                    continue
                raise AdapterError(classify_http_status(response.status_code), http_message, details=error_details(endpoint=endpoint, status_code=response.status_code))

            try:
                payload = response.json()
            except ValueError as exc:
                raise AdapterError(ErrorCode.ADAPTER_PROTOCOL_ERROR, invalid_json_message, details=error_details(endpoint=endpoint, status_code=response.status_code)) from exc

            if retry_payload is not None and retry_payload(payload, attempt_index):
                self._sleep_before_retry(attempt_index)
                continue
            return payload

        raise AdapterError(ErrorCode.EXTERNAL_API_ERROR, transport_message, details=error_details(endpoint=endpoint)) from last_transport_error

    def get_json(self, url: str) -> Any:
        """Fetch JSON with fail-closed status handling and bounded retries."""

        self._require_enabled()
        self._validate_endpoint(url, gamma=True)
        return self._request_json(
            endpoint=url,
            method="GET",
            send=lambda client: client.get(url),
            timeout_message="Polymarket adapter request timed out",
            transport_message="Polymarket adapter transport error",
            http_message="Polymarket adapter HTTP error",
            invalid_json_message="Polymarket adapter returned invalid JSON",
        )

    def gamma_get(self, path: str) -> Any:
        self._require_enabled()
        if not self.config.gamma_base_url:
            raise AdapterError(
                ErrorCode.CONFIG_REQUIRED,
                "Gamma API base URL is required for Polymarket market/snapshot fetches",
                details={"config_key": "network.polymarket.gamma_base_url"},
            )
        base = self.config.gamma_base_url.rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        return self.get_json(f"{base}{suffix}")

    def polygon_rpc(self, method: str, params: list[Any] | None = None) -> Any:
        endpoint = self._require_polygon_rpc()
        self._validate_endpoint(endpoint, gamma=False)

        def retry_rpc_error(payload: Any, attempt_index: int) -> bool:
            if isinstance(payload, dict) and payload.get("error"):
                err = payload.get("error") or {}
                return is_retryable_json_rpc_error(err.get("code")) and attempt_index < RETRY_STOP_AFTER_ATTEMPT - 1
            return False

        payload = self._request_json(
            endpoint=endpoint,
            method="POST",
            send=lambda client: client.post(endpoint, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}),
            timeout_message="Polygon RPC request timed out",
            transport_message="Polygon RPC transport error",
            http_message="Polygon RPC HTTP error",
            invalid_json_message="Polygon RPC returned invalid JSON",
            retry_payload=retry_rpc_error,
        )
        if isinstance(payload, dict) and payload.get("error"):
            err = payload.get("error") or {}
            raise AdapterError(classify_json_rpc_error(err.get("code")), "Polygon RPC returned an error", details={"rpc_code": err.get("code")})
        return payload


def classify_json_rpc_error(code: int | None) -> ErrorCode:
    if is_retryable_json_rpc_error(code):
        return ErrorCode.EXTERNAL_API_ERROR
    return ErrorCode.ADAPTER_PROTOCOL_ERROR
