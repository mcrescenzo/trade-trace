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


def auto_score_block_reason(*, status: str, confidence: Any, outcome_label: str) -> str | None:
    """Explain why an outcome is NOT auto-scoreable, or None when it is.

    Surfaced on the `outcome.add` / `resolution.add` result so a caller that
    records a `resolved_final` outcome but omits `confidence` (which the
    advertised tool schema does not list — only `example_rich` mentions it)
    gets a point-of-failure hint instead of a silent `auto_scoreable:false`
    and no forecast score. Without this, the missing-`confidence` trap is
    invisible: the write succeeds, nothing scores, and no error is raised.
    """

    if is_auto_scoreable_final(
        status=status, confidence=confidence, outcome_label=outcome_label
    ):
        return None
    reasons: list[str] = []
    if status != "resolved_final":
        reasons.append(
            f"status={status!r} is not 'resolved_final' "
            "(only resolved_final outcomes auto-score)"
        )
    else:
        conf = confidence_value(confidence)
        if conf is None:
            reasons.append(
                "confidence is missing — auto-scoring requires confidence>=0.9 "
                "(pass it explicitly; the advertised schema omits this field)"
            )
        elif conf < 0.9:
            reasons.append(
                f"confidence={conf} is below the 0.9 auto-score threshold"
            )
        if outcome_label.strip().lower() not in _BINARY_RESOLUTION_LABELS:
            reasons.append(
                f"outcome_label={outcome_label!r} is not one of the binary "
                f"labels {sorted(_BINARY_RESOLUTION_LABELS)}"
            )
    return "; ".join(reasons) or None
