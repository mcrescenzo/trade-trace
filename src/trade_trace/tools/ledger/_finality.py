"""Shared conservative finality predicates for Polymarket resolution evidence."""

from __future__ import annotations

from typing import Any

_FINALITY_UNCERTAIN_STATUSES = {
    "resolved_provisional",
    "proposed",
    "provisional",
    "disputed",
    "ambiguous",
    "void",
    "cancelled",
    "imported_redeemed",
    "imported_settled",
}

_BINARY_RESOLUTION_LABELS = {"yes", "no", "true", "false"}


def confidence_value(value: Any) -> float | None:
    """Return a strict Python-parsed confidence value, or None if invalid."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_auto_scoreable_final(*, status: str, confidence: Any, outcome_label: str) -> bool:
    """True only for safe final rows eligible for automatic binary scoring."""

    if status != "resolved_final":
        return False
    conf = confidence_value(confidence)
    if conf is None or conf < 0.9:
        return False
    return outcome_label.strip().lower() in _BINARY_RESOLUTION_LABELS


def finality_uncertain_for_outcome(*, status: str, confidence: Any, outcome_label: str) -> bool:
    return status in _FINALITY_UNCERTAIN_STATUSES or not is_auto_scoreable_final(
        status=status,
        confidence=confidence,
        outcome_label=outcome_label,
    )
