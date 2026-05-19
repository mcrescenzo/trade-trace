"""Event log, outbox, and idempotency per docs/architecture/persistence.md."""

from trade_trace.events.log import (
    EventRecord,
    EventWriter,
    IdempotencyConflictError,
)
from trade_trace.events.semantic_keys import (
    SEMANTIC_KEYS,
    SemanticKeySpec,
    canonicalize_payload,
    payloads_equivalent,
)
from trade_trace.events.unit_of_work import UnitOfWork

__all__ = [
    "EventRecord",
    "EventWriter",
    "IdempotencyConflictError",
    "SEMANTIC_KEYS",
    "SemanticKeySpec",
    "UnitOfWork",
    "canonicalize_payload",
    "payloads_equivalent",
]
