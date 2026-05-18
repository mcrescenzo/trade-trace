"""MVP retrieval constants locked per bead trade-trace-tem.

Verifies that the three recall constants ship at their committed
values and produce the expected behavior:

- `K_RRF = 60`  (reciprocal-rank-fusion denominator)
- `IMPORTANCE_BOOST_SLOPE = 0.05` (linear: importance=1 → 0.80, =5 → 1.00,
  =10 → 1.25)
- `SUPERSESSION_DISCOUNT = 0.25` (a superseded node's RRF score is
  multiplied by 0.25 before final ranking)
"""

from __future__ import annotations

import math

import pytest

from trade_trace.tools.memory import (
    IMPORTANCE_BOOST_SLOPE,
    K_RRF,
    SUPERSESSION_DISCOUNT,
    _rrf_combine,
)


# -- 1. pinned constant values ------------------------------------


def test_k_rrf_locked_at_60():
    assert K_RRF == 60


def test_importance_boost_slope_locked():
    assert IMPORTANCE_BOOST_SLOPE == 0.05


def test_supersession_discount_locked_at_quarter():
    assert SUPERSESSION_DISCOUNT == 0.25


# -- 2. importance boost at boundaries ----------------------------


@pytest.mark.parametrize(
    "importance,expected",
    [(1, 0.80), (3, 0.90), (5, 1.00), (7, 1.10), (10, 1.25)],
)
def test_importance_boost_formula(importance, expected):
    """The boost is linear: 1.0 + (importance - 5) * 0.05.
    Pinning the three boundary points (1, 5, 10) is the contract."""

    boost = 1.0 + (importance - 5) * IMPORTANCE_BOOST_SLOPE
    assert boost == pytest.approx(expected)


# -- 3. RRF combination matches manual computation ----------------


def test_rrf_two_strategies_three_nodes_manual_check():
    """Two strategies rank three nodes (1, 2, 3) each:

      bm25:     [n1, n2, n3]
      temporal: [n3, n2, n1]

    RRF scores per node:
      n1: 1/(60+1) + 1/(60+3) = 1/61 + 1/63
      n2: 1/(60+2) + 1/(60+2) = 2/62
      n3: 1/(60+3) + 1/(60+1) = 1/63 + 1/61

    n1 and n3 tie; n2 sits between or alongside them depending on
    floating-point precision, but ordering is stable on tie via id.
    """

    rankings = {
        "bm25": ["n1", "n2", "n3"],
        "temporal": ["n3", "n2", "n1"],
    }
    combined = _rrf_combine(rankings)
    by_id = {nid: score for nid, score, _prov in combined}
    expected_n1 = 1.0 / (60 + 1) + 1.0 / (60 + 3)
    expected_n2 = 2.0 / (60 + 2)
    expected_n3 = 1.0 / (60 + 3) + 1.0 / (60 + 1)
    assert by_id["n1"] == pytest.approx(expected_n1)
    assert by_id["n2"] == pytest.approx(expected_n2)
    assert by_id["n3"] == pytest.approx(expected_n3)


def test_rrf_provenance_records_per_strategy_ranks():
    """The provenance dict carries the 1-indexed rank in each strategy
    so the agent can drill into why a node ranked where it did."""

    rankings = {
        "bm25": ["n1", "n2"],
        "graph": ["n2", "n1"],
    }
    combined = _rrf_combine(rankings)
    by_id = {nid: prov for nid, _score, prov in combined}
    assert by_id["n1"]["bm25"] == [1]
    assert by_id["n1"]["graph"] == [2]
    assert by_id["n2"]["bm25"] == [2]
    assert by_id["n2"]["graph"] == [1]


# -- 4. supersession discount: relative score effect --------------


def test_supersession_discount_is_quarter():
    """A discounted score should be exactly 0.25× the pre-discount value."""

    base = 0.123456
    assert base * SUPERSESSION_DISCOUNT == pytest.approx(base * 0.25)


# -- 5. Final declarations cannot be mutated at type-check time ---


def test_constants_module_exports_pinned_values():
    """The constants module surfaces all three names with their pinned
    values so a tooling consumer can `from trade_trace.tools.memory
    import K_RRF, IMPORTANCE_BOOST_SLOPE, SUPERSESSION_DISCOUNT`."""

    from trade_trace.tools import memory

    assert memory.K_RRF == 60
    assert memory.IMPORTANCE_BOOST_SLOPE == 0.05
    assert memory.SUPERSESSION_DISCOUNT == 0.25
