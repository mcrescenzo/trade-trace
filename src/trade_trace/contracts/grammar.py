"""Grammar validators for `actor_id` and `idempotency_key` per PRD §2.

These are the boundary validators that turn malformed input into a
structured `VALIDATION_ERROR` envelope. The regexes are pinned here so
they cannot drift between the CLI, MCP, and importer surfaces.
"""

from __future__ import annotations

import re
from typing import Final

from trade_trace.contracts.errors import ErrorCode
from trade_trace.tools.errors import ToolError


ACTOR_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(agent|cli|import|system):[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
)
ACTOR_ID_HINT: Final[str] = (
    "actor_id must match `(agent|cli|import|system):<name>` where <name> is "
    "1–64 chars from [A-Za-z0-9._-] and starts with [A-Za-z0-9]."
)


IDEMPOTENCY_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
IDEMPOTENCY_KEY_HINT: Final[str] = (
    "idempotency_key must be 1–128 chars from [A-Za-z0-9._:-] after trimming "
    "leading/trailing whitespace; comparison is case-sensitive."
)


def validate_actor_id(value: str) -> str:
    """Validate and return the canonical actor_id. Raises ToolError on
    failure with the structured details PRD §2 specifies."""

    if not isinstance(value, str):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "actor_id must be a string",
            details={"field": "actor_id", "expected_format": ACTOR_ID_HINT},
        )
    if not ACTOR_ID_PATTERN.match(value):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"actor_id {value!r} does not match required grammar",
            details={
                "field": "actor_id",
                "expected_format": ACTOR_ID_HINT,
                "value": value,
            },
        )
    return value


def validate_idempotency_key(value: str | None) -> str | None:
    """Validate and return the trimmed idempotency_key, or None if the
    caller didn't supply one. Whitespace is stripped before validation;
    a key that becomes empty after trim is rejected (not None — the
    distinction is preserved so callers can pass --allow-no-idempotency)."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "idempotency_key must be a string when supplied",
            details={"field": "idempotency_key", "expected_format": IDEMPOTENCY_KEY_HINT},
        )
    trimmed = value.strip()
    if not IDEMPOTENCY_KEY_PATTERN.match(trimmed):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"idempotency_key {value!r} does not match required grammar",
            details={
                "field": "idempotency_key",
                "expected_format": IDEMPOTENCY_KEY_HINT,
                "value": value,
            },
        )
    return trimmed
