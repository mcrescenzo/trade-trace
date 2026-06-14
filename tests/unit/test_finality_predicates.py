"""Direct unit tests for the conservative finality predicates.

The four predicates in ``trade_trace.tools.ledger._finality`` were previously
only exercised end-to-end through ``outcome.add`` (see
``tests/integration/test_polymarket_resolution_finality.py``). End-to-end
coverage can silently miss a changed branch when the seeded inputs never
trigger it. These tests pin each predicate's branch behaviour directly so a
regression in the auto-score gate fails here at the unit boundary
(bead trade-trace-mhdv).
"""

from __future__ import annotations

from typing import Any

import pytest

from trade_trace.tools.ledger._finality import (
    _BINARY_RESOLUTION_LABELS,
    _FINALITY_UNCERTAIN_STATUSES,
    auto_score_block_reason,
    confidence_value,
    finality_uncertain_for_outcome,
    is_auto_scoreable_final,
)

# --------------------------------------------------------------------------
# confidence_value: strict Python parse, None on anything non-numeric.
# --------------------------------------------------------------------------


def test_confidence_value_bool_true_is_one() -> None:
    # ``bool`` is an ``int`` subclass, so ``float(True) == 1.0`` — True passes
    # the >=0.9 gate. Pinned so a future ``isinstance(value, bool)`` reject
    # does not change behaviour silently.
    assert confidence_value(True) == 1.0


def test_confidence_value_list_is_none() -> None:
    assert confidence_value([]) is None


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("bad", None),
        ({}, None),
        (0.89, 0.89),
        (1, 1.0),
        ("0.90", 0.90),
    ],
)
def test_confidence_value_parses_or_returns_none(value: Any, expected: float | None) -> None:
    assert confidence_value(value) == expected


# --------------------------------------------------------------------------
# is_auto_scoreable_final: boundary confidence + non-numeric inputs.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "confidence, expected",
    [
        (0.9, True),  # exact threshold is inclusive (>= 0.9)
        (0.89, False),  # just below the threshold
        (None, False),  # missing confidence never auto-scores
        ("bad", False),  # unparseable confidence never auto-scores
        (True, True),  # float(True) == 1.0 >= 0.9
        (1, True),  # int 1 -> 1.0 >= 0.9
    ],
)
def test_is_auto_scoreable_final_confidence_boundary(confidence: Any, expected: bool) -> None:
    assert (
        is_auto_scoreable_final(
            status="resolved_final", confidence=confidence, outcome_label="yes"
        )
        is expected
    )


def test_is_auto_scoreable_final_requires_resolved_final_status() -> None:
    assert (
        is_auto_scoreable_final(
            status="proposed", confidence=0.99, outcome_label="yes"
        )
        is False
    )


@pytest.mark.parametrize("label", sorted(_BINARY_RESOLUTION_LABELS))
def test_is_auto_scoreable_final_accepts_each_binary_label(label: str) -> None:
    assert (
        is_auto_scoreable_final(
            status="resolved_final", confidence=0.95, outcome_label=label.upper()
        )
        is True
    )


def test_is_auto_scoreable_final_rejects_non_binary_label() -> None:
    assert (
        is_auto_scoreable_final(
            status="resolved_final", confidence=0.95, outcome_label="maybe"
        )
        is False
    )


# --------------------------------------------------------------------------
# finality_uncertain_for_outcome: every uncertain status, plus the one
# clearly-final case.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(_FINALITY_UNCERTAIN_STATUSES))
def test_finality_uncertain_for_each_uncertain_status(status: str) -> None:
    # Even with otherwise-auto-scoreable confidence and a binary label, an
    # explicitly-uncertain status is uncertain.
    assert (
        finality_uncertain_for_outcome(
            status=status, confidence=0.99, outcome_label="yes"
        )
        is True
    )


def test_finality_uncertain_false_only_for_auto_scoreable_final() -> None:
    assert (
        finality_uncertain_for_outcome(
            status="resolved_final", confidence=0.99, outcome_label="yes"
        )
        is False
    )


def test_finality_uncertain_true_when_resolved_final_but_low_confidence() -> None:
    # resolved_final is not in the uncertain set, so this exercises the
    # ``not is_auto_scoreable_final(...)`` arm of the predicate.
    assert (
        finality_uncertain_for_outcome(
            status="resolved_final", confidence=0.5, outcome_label="yes"
        )
        is True
    )


# --------------------------------------------------------------------------
# auto_score_block_reason: each individual reason, both reasons together,
# and None when the row is auto-scoreable.
# --------------------------------------------------------------------------


def test_auto_score_block_reason_none_when_auto_scoreable() -> None:
    assert (
        auto_score_block_reason(
            status="resolved_final", confidence=0.95, outcome_label="yes"
        )
        is None
    )


def test_auto_score_block_reason_missing_confidence() -> None:
    reason = auto_score_block_reason(
        status="resolved_final", confidence=None, outcome_label="yes"
    )
    assert reason is not None
    assert "confidence is missing" in reason


def test_auto_score_block_reason_low_confidence() -> None:
    reason = auto_score_block_reason(
        status="resolved_final", confidence=0.89, outcome_label="yes"
    )
    assert reason is not None
    assert "0.9 auto-score threshold" in reason


def test_auto_score_block_reason_non_binary_label() -> None:
    reason = auto_score_block_reason(
        status="resolved_final", confidence=0.95, outcome_label="maybe"
    )
    assert reason is not None
    assert "is not one of the binary" in reason


def test_auto_score_block_reason_non_resolved_final_status() -> None:
    reason = auto_score_block_reason(
        status="proposed", confidence=0.99, outcome_label="yes"
    )
    assert reason is not None
    assert "not 'resolved_final'" in reason


def test_auto_score_block_reason_reports_both_reasons() -> None:
    # Non-binary label AND sub-threshold confidence: both reasons must be
    # surfaced (joined with '; '), not just the first one encountered.
    reason = auto_score_block_reason(
        status="resolved_final", confidence=0.5, outcome_label="maybe"
    )
    assert reason is not None
    assert "0.9 auto-score threshold" in reason
    assert "is not one of the binary" in reason
    assert "; " in reason
