"""Stable error code enum per docs/architecture/contracts.md §5."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """The closed enum of MVP error codes.

    Adding a new value is a contract change requiring a minor version bump
    (additive extension only). Removing or renaming is a major version bump.
    """

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    STORAGE_ERROR = "STORAGE_ERROR"
    SCORING_UNSUPPORTED = "SCORING_UNSUPPORTED"
    SCORING_NOT_READY = "SCORING_NOT_READY"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    MARKET_NOT_RESOLVED = "MARKET_NOT_RESOLVED"
    MARKET_AMBIGUOUS = "MARKET_AMBIGUOUS"
