"""Polymarket adapter foundation.

This package intentionally exposes only opt-in configuration/client primitives.
No module-level network client is created and no live call is made on import.
"""

from __future__ import annotations

from trade_trace.adapters.polymarket.config import (
    ACTOR_ID,
    PolymarketConfig,
    adapter_state_from_config,
    load_config,
)
from trade_trace.adapters.polymarket.errors import AdapterError

__all__ = [
    "ACTOR_ID",
    "AdapterError",
    "PolymarketConfig",
    "adapter_state_from_config",
    "load_config",
]
