"""Private markets table row projection/serialization helpers."""

from __future__ import annotations

from typing import Any

MARKET_BIND_ROW_COLUMNS = (
    "id",
    "source",
    "external_id",
    "title",
    "question",
    "url",
    "state",
    "mechanism",
    "resolution_source",
    "ambiguity_kind",
    "bound_via",
    "opened_at",
    "close_at",
    "closed_for_trading_at",
    "resolving_at",
    "resolved_at",
    "voided_at",
    "ambiguous_at",
    "venue_metadata_json",
    "metadata_json",
    "created_at",
    "actor_id",
)
MARKET_BIND_ROW_SELECT = ", ".join(MARKET_BIND_ROW_COLUMNS)

ADAPTER_CACHE_HIT_ROW_COLUMNS = (
    "id",
    "source",
    "external_id",
    "title",
    "question",
    "url",
    "state",
    "mechanism",
    "resolution_source",
    "ambiguity_kind",
    "bound_via",
    "metadata_json",
    "venue_metadata_json",
    "created_at",
)
ADAPTER_CACHE_HIT_ROW_SELECT = ",".join(ADAPTER_CACHE_HIT_ROW_COLUMNS)


def market_bind_row_dict(row: Any) -> dict[str, Any]:
    """Serialize a full market.bind replay/natural-key row shape."""

    return dict(zip(MARKET_BIND_ROW_COLUMNS, row, strict=True))


def adapter_cache_hit_row_dict(row: Any) -> dict[str, Any]:
    """Serialize the narrower adapter market.refresh cache-hit row shape."""

    return dict(zip(ADAPTER_CACHE_HIT_ROW_COLUMNS, row, strict=True))
