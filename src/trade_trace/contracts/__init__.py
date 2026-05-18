"""Shared transport contract: envelopes, error codes, tool registry."""

from trade_trace.contracts.envelope import (
    REPORT_STANDARD_META_KEYS,
    ErrorBody,
    ErrorEnvelope,
    Meta,
    SuccessEnvelope,
    dump_envelope,
)
from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.grammar import (
    ACTOR_ID_HINT,
    ACTOR_ID_PATTERN,
    IDEMPOTENCY_KEY_HINT,
    IDEMPOTENCY_KEY_PATTERN,
    validate_actor_id,
    validate_idempotency_key,
)
from trade_trace.contracts.tool_registry import (
    CLINameCollisionError,
    ToolHandler,
    ToolRegistry,
    cli_invocation_for,
)

__all__ = [
    "ACTOR_ID_HINT",
    "ACTOR_ID_PATTERN",
    "CLINameCollisionError",
    "ErrorBody",
    "ErrorCode",
    "ErrorEnvelope",
    "IDEMPOTENCY_KEY_HINT",
    "IDEMPOTENCY_KEY_PATTERN",
    "Meta",
    "REPORT_STANDARD_META_KEYS",
    "SuccessEnvelope",
    "ToolHandler",
    "ToolRegistry",
    "cli_invocation_for",
    "dump_envelope",
    "validate_actor_id",
    "validate_idempotency_key",
]
