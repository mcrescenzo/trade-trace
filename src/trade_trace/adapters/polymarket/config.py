"""Configuration/status helpers for the opt-in Polymarket adapter."""

from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection
from typing import Mapping

ACTOR_ID = "system:polymarket-adapter"
KEY_ENABLED = "network.polymarket.enabled"
KEY_GAMMA_BASE_URL = "network.polymarket.gamma_base_url"
KEY_POLYGON_RPC_URL = "network.polymarket.polygon_rpc_url"
KEY_TIMEOUT_SECONDS = "network.polymarket.timeout_seconds"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 60.0
USER_AGENT = "trade-trace/0.0.2 (polymarket-adapter)"


@dataclass(frozen=True)
class PolymarketConfig:
    enabled: bool = False
    gamma_base_url: str | None = None
    polygon_rpc_url: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cached_markets_count: int = 0
    last_successful_fetch_at: str | None = None

    @property
    def outbound_network_active(self) -> bool:
        return self.enabled


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _timeout(value: str | None) -> float:
    if value is None or value == "":
        return DEFAULT_TIMEOUT_SECONDS
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    if parsed <= 0:
        return DEFAULT_TIMEOUT_SECONDS
    return min(parsed, MAX_TIMEOUT_SECONDS)


def config_from_mapping(values: Mapping[str, str]) -> PolymarketConfig:
    return PolymarketConfig(
        enabled=_is_true(values.get(KEY_ENABLED)),
        gamma_base_url=values.get(KEY_GAMMA_BASE_URL) or None,
        polygon_rpc_url=values.get(KEY_POLYGON_RPC_URL) or None,
        timeout_seconds=_timeout(values.get(KEY_TIMEOUT_SECONDS)),
    )


def load_config(conn: Connection | None = None) -> PolymarketConfig:
    """Read adapter config from the existing open-namespace config table.

    Missing DB/table/keys are treated as disabled. This function performs only a
    local SQLite read and never imports the HTTP client.
    """

    if conn is None:
        return PolymarketConfig()
    try:
        rows = conn.execute(
            "SELECT key, value FROM config WHERE key IN (?, ?, ?, ?)",
            (KEY_ENABLED, KEY_GAMMA_BASE_URL, KEY_POLYGON_RPC_URL, KEY_TIMEOUT_SECONDS),
        ).fetchall()
    except Exception:
        return PolymarketConfig()
    return config_from_mapping({str(k): str(v) for k, v in rows})


def adapter_state_from_config(config: PolymarketConfig) -> dict[str, object]:
    return {
        "polymarket": {
            "enabled": config.enabled,
            "configured_endpoints": {
                "gamma_base_url": bool(config.gamma_base_url),
                "polygon_rpc_url": bool(config.polygon_rpc_url),
            },
            "cached_markets_count": config.cached_markets_count,
            "last_successful_fetch_at": config.last_successful_fetch_at,
        }
    }
