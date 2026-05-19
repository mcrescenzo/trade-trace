"""Deterministic bucketing constants per docs/architecture/reports.md §6.

MVP locks these thresholds in code so report filters and aggregates are
bit-stable across calls. Configurable overrides (`config.bucketing.<name>`)
are deferred to P2.

Boundary convention (PRD/spec): each band uses `<` on the upper edge except
the topmost band, which uses `>=`. So `spread / price == 0.005` is `medium`
(not `tight`); `volume == 1000` is `medium` (not `thin`/`low`). The unit
tests in `tests/integration/test_bucket_constants.py` pin these edges.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

SPREAD_BUCKET_THRESHOLDS: Final[Mapping[str, float]] = MappingProxyType({
    "tight_max_exclusive": 0.005,   # ratio: spread / price
    "medium_max_exclusive": 0.02,
})
"""`tight: ratio < 0.005`; `medium: < 0.02`; `wide: >= 0.02`."""


LIQUIDITY_BUCKET_THRESHOLDS: Final[Mapping[str, float]] = MappingProxyType({
    "thin_max_exclusive": 1000.0,
    "medium_max_exclusive": 100000.0,
})
"""`thin: volume < 1_000`; `medium: < 100_000`; `deep: >= 100_000`."""


VOLUME_BUCKET_THRESHOLDS: Final[Mapping[str, float]] = MappingProxyType({
    "low_max_exclusive": 1000.0,
    "medium_max_exclusive": 1_000_000.0,
})
"""`low: volume < 1_000`; `medium: < 1_000_000`; `high: >= 1_000_000`."""


CONFIDENCE_LABELS: Final[tuple[str, ...]] = (
    "very_low", "low", "medium", "high", "very_high",
)
"""Identity mapping over `theses.confidence_label`; no thresholds."""


SPREAD_BUCKET_VALUES: Final[tuple[str, ...]] = ("tight", "medium", "wide")
LIQUIDITY_BUCKET_VALUES: Final[tuple[str, ...]] = ("thin", "medium", "deep")
VOLUME_BUCKET_VALUES: Final[tuple[str, ...]] = ("low", "medium", "high")


def spread_bucket(spread: float, price: float) -> str:
    """Return the spread bucket for `spread / price`.

    Raises ZeroDivisionError when `price == 0`; callers must guard upstream.
    """

    ratio = spread / price
    if ratio < SPREAD_BUCKET_THRESHOLDS["tight_max_exclusive"]:
        return "tight"
    if ratio < SPREAD_BUCKET_THRESHOLDS["medium_max_exclusive"]:
        return "medium"
    return "wide"


def liquidity_bucket(volume: float) -> str:
    if volume < LIQUIDITY_BUCKET_THRESHOLDS["thin_max_exclusive"]:
        return "thin"
    if volume < LIQUIDITY_BUCKET_THRESHOLDS["medium_max_exclusive"]:
        return "medium"
    return "deep"


def volume_bucket(volume: float) -> str:
    if volume < VOLUME_BUCKET_THRESHOLDS["low_max_exclusive"]:
        return "low"
    if volume < VOLUME_BUCKET_THRESHOLDS["medium_max_exclusive"]:
        return "medium"
    return "high"


def confidence_bucket(label: str) -> str:
    """Identity on `theses.confidence_label` with grammar guard. Unknown
    labels raise ValueError so a typo cannot silently rebucket."""

    if label not in CONFIDENCE_LABELS:
        raise ValueError(
            f"confidence_bucket: unknown label {label!r}; "
            f"expected one of {CONFIDENCE_LABELS}"
        )
    return label


__all__ = [
    "CONFIDENCE_LABELS",
    "LIQUIDITY_BUCKET_THRESHOLDS",
    "LIQUIDITY_BUCKET_VALUES",
    "SPREAD_BUCKET_THRESHOLDS",
    "SPREAD_BUCKET_VALUES",
    "VOLUME_BUCKET_THRESHOLDS",
    "VOLUME_BUCKET_VALUES",
    "confidence_bucket",
    "liquidity_bucket",
    "spread_bucket",
    "volume_bucket",
]
