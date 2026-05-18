"""Bucketing policy constants per docs/architecture/reports.md §6 / bead 5a6.

Pins the MVP banding so report filters and aggregates stay bit-stable
across calls. Configurable thresholds are P2 (open question §6).
"""

from __future__ import annotations

import pytest

from trade_trace.reports import (
    CONFIDENCE_LABELS,
    LIQUIDITY_BUCKET_THRESHOLDS,
    SPREAD_BUCKET_THRESHOLDS,
    VOLUME_BUCKET_THRESHOLDS,
    confidence_bucket,
    liquidity_bucket,
    spread_bucket,
    volume_bucket,
)


# -- spread_bucket: tight < 0.005; medium < 0.02; wide >= 0.02 --------


@pytest.mark.parametrize(
    "spread,price,expected",
    [
        # below tight cutoff
        (0.004, 1.0, "tight"),
        (0.0049, 1.0, "tight"),
        # exactly at tight cutoff → bumps to medium
        (0.005, 1.0, "medium"),
        # below medium cutoff
        (0.01, 1.0, "medium"),
        (0.0199, 1.0, "medium"),
        # exactly at medium cutoff → bumps to wide
        (0.02, 1.0, "wide"),
        (0.05, 1.0, "wide"),
        # ratio invariance (same ratio, different price/spread scale)
        (0.5, 100.0, "medium"),  # ratio 0.005 → medium
    ],
)
def test_spread_bucket_boundaries(spread, price, expected):
    assert spread_bucket(spread, price) == expected


# -- liquidity_bucket: thin < 1_000; medium < 100_000; deep >= 100_000


@pytest.mark.parametrize(
    "volume,expected",
    [
        (0, "thin"),
        (999, "thin"),
        (1000, "medium"),         # equal-threshold → upper band
        (50000, "medium"),
        (99999, "medium"),
        (100000, "deep"),
        (250000, "deep"),
    ],
)
def test_liquidity_bucket_boundaries(volume, expected):
    assert liquidity_bucket(volume) == expected


# -- volume_bucket: low < 1_000; medium < 1_000_000; high >= 1_000_000


@pytest.mark.parametrize(
    "volume,expected",
    [
        (0, "low"),
        (999, "low"),
        (1000, "medium"),
        (999_999, "medium"),
        (1_000_000, "high"),
        (5_000_000, "high"),
    ],
)
def test_volume_bucket_boundaries(volume, expected):
    assert volume_bucket(volume) == expected


# -- confidence_bucket: identity on theses.confidence_label -----------


@pytest.mark.parametrize("label", list(CONFIDENCE_LABELS))
def test_confidence_bucket_identity(label):
    assert confidence_bucket(label) == label


def test_confidence_bucket_rejects_unknown_label():
    with pytest.raises(ValueError):
        confidence_bucket("medium_high")


# -- constants are readonly (mutating raises TypeError) ---------------


def test_spread_thresholds_immutable():
    with pytest.raises(TypeError):
        SPREAD_BUCKET_THRESHOLDS["tight_max_exclusive"] = 0.01  # type: ignore[index]


def test_liquidity_thresholds_immutable():
    with pytest.raises(TypeError):
        LIQUIDITY_BUCKET_THRESHOLDS["thin_max_exclusive"] = 5000  # type: ignore[index]


def test_volume_thresholds_immutable():
    with pytest.raises(TypeError):
        VOLUME_BUCKET_THRESHOLDS["low_max_exclusive"] = 5000  # type: ignore[index]


# -- pinned exact thresholds (reports.md §6) --------------------------


def test_exact_threshold_values():
    """Pin the MVP boundary numbers so docs/architecture/reports.md §6
    cannot drift away from the implementation without a test failure."""

    assert SPREAD_BUCKET_THRESHOLDS["tight_max_exclusive"] == 0.005
    assert SPREAD_BUCKET_THRESHOLDS["medium_max_exclusive"] == 0.02
    assert LIQUIDITY_BUCKET_THRESHOLDS["thin_max_exclusive"] == 1000
    assert LIQUIDITY_BUCKET_THRESHOLDS["medium_max_exclusive"] == 100000
    assert VOLUME_BUCKET_THRESHOLDS["low_max_exclusive"] == 1000
    assert VOLUME_BUCKET_THRESHOLDS["medium_max_exclusive"] == 1_000_000
    assert CONFIDENCE_LABELS == (
        "very_low", "low", "medium", "high", "very_high",
    )
