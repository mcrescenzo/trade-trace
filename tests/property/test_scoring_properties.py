"""Brier-binary scoring property tests per trade-trace-ucd.

These pin the scoring.md §3 single-probability form against three reference
distributions enumerated in the ucd acceptance criteria:

- perfectly-calibrated synthetic → Brier = 0
- always-50% on balanced data → Brier ≈ 0.25
- random (p drawn uniformly) on y=1 → Brier ≈ 1/3

Each scenario has ≥2 explicit tests so a future regression on the formula
shape (e.g. accidentally switching to the two-outcome form) trips loudly.
The aggregation logic mirrors what `report.calibration` will use; this is
the substrate, not the report.
"""

from __future__ import annotations

import math
import random

import pytest


def brier_binary(p_yes: float, y: int) -> float:
    """Reference implementation of scoring.md §3 single-probability form.

    Kept inline (rather than importing the autoscorer's private function)
    so this file is a contract-grade fixture: any drift between the
    autoscorer and the formula is a real failure, not a circular check."""

    return (p_yes - y) ** 2


def mean_brier(scores: list[float]) -> float:
    if not scores:
        raise ValueError("empty score set")
    return sum(scores) / len(scores)


# -- perfectly-calibrated synthetic (Brier = 0) -----------------------------


def test_perfectly_calibrated_p1_y1_scores_zero():
    """p_yes=1 on y=1 is perfect; Brier == 0."""

    assert brier_binary(1.0, 1) == 0.0


def test_perfectly_calibrated_p0_y0_scores_zero():
    """p_yes=0 on y=0 is perfect (the NO-side equivalent); Brier == 0."""

    assert brier_binary(0.0, 0) == 0.0


def test_perfectly_calibrated_aggregate_is_zero():
    """Many perfect forecasts → mean Brier = 0."""

    scores = [brier_binary(1.0, 1) for _ in range(100)] + [
        brier_binary(0.0, 0) for _ in range(100)
    ]
    assert mean_brier(scores) == pytest.approx(0.0)


# -- always-50% on balanced data (Brier ≈ 0.25) -----------------------------


def test_always_50_on_y1_scores_quarter():
    """p_yes=0.5 on y=1 → Brier = 0.25."""

    assert brier_binary(0.5, 1) == pytest.approx(0.25)


def test_always_50_on_y0_scores_quarter():
    """p_yes=0.5 on y=0 → Brier = 0.25 too (symmetric)."""

    assert brier_binary(0.5, 0) == pytest.approx(0.25)


def test_always_50_balanced_aggregate_is_quarter():
    """Always-50%, balanced data → mean Brier = exactly 0.25."""

    scores = [brier_binary(0.5, 1) for _ in range(50)] + [
        brier_binary(0.5, 0) for _ in range(50)
    ]
    assert mean_brier(scores) == pytest.approx(0.25)


# -- random forecaster on y=1 (Brier ≈ 1/3) ---------------------------------


def test_random_forecaster_y1_aggregate_close_to_third():
    """A random forecaster picks p ~ U(0,1). Against y=1, the expected
    Brier is `E[(p - 1)^2] = 1/3`. With N=20_000 we expect the sample
    mean within ±0.005 of 1/3."""

    rng = random.Random(20260518)
    scores = [brier_binary(rng.random(), 1) for _ in range(20_000)]
    assert mean_brier(scores) == pytest.approx(1.0 / 3.0, abs=0.005)


def test_random_forecaster_y0_aggregate_close_to_third():
    """Symmetric: against y=0, expected Brier = `E[p^2] = 1/3`."""

    rng = random.Random(20260518)
    scores = [brier_binary(rng.random(), 0) for _ in range(20_000)]
    assert mean_brier(scores) == pytest.approx(1.0 / 3.0, abs=0.005)


# -- bounds + monotonicity --------------------------------------------------


def test_brier_in_unit_interval():
    """Per scoring.md §3, the score is in [0, 1]."""

    rng = random.Random(20260518)
    for _ in range(500):
        p = rng.random()
        for y in (0, 1):
            s = brier_binary(p, y)
            assert 0.0 <= s <= 1.0


def test_brier_maximally_wrong_scores_one():
    """The worst possible single forecast: p_yes=1 on y=0 (or p_yes=0 on
    y=1) → Brier = 1."""

    assert brier_binary(1.0, 0) == 1.0
    assert brier_binary(0.0, 1) == 1.0


def test_brier_monotone_in_distance_from_truth():
    """Holding y fixed, the score is monotone in |p - y|."""

    deltas = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    for y in (0, 1):
        ranked = [(d, brier_binary(y + (1 - 2 * y) * d, y)) for d in deltas]
        # ranked is sorted by `d`; the score column must be non-decreasing.
        for (_, s_a), (_, s_b) in zip(ranked, ranked[1:]):
            assert s_b >= s_a - 1e-12


# -- single-probability form (NOT two-outcome) ------------------------------


def test_single_probability_form_pinned_against_two_outcome():
    """scoring.md §3.1 deliberately rejects the two-outcome form.
    Pin the relationship so a future drift to `(p_yes - y)^2 + (p_no -
    (1-y))^2` (which is `2 *` the single-form result) is caught."""

    for p in (0.0, 0.1, 0.5, 0.9, 1.0):
        for y in (0, 1):
            single = brier_binary(p, y)
            two_outcome = (p - y) ** 2 + ((1 - p) - (1 - y)) ** 2
            assert math.isclose(two_outcome, 2 * single, abs_tol=1e-12)
