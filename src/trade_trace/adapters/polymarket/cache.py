"""Cache policy constants for the Polymarket adapter foundation."""

from __future__ import annotations

SNAPSHOTS_CACHE_TTL_SECONDS = 0
RESOLVED_FINAL_CACHE_TTL_SECONDS = None  # forever
MARKET_CACHE_TTL_SECONDS = {
    "resolved": 24 * 60 * 60,
    "open": 60 * 60,
    "resolving": 5 * 60,
    "ambiguous": 0,
    "voided": 0,
}
STALE_WHILE_REVALIDATE_SECONDS = 0
