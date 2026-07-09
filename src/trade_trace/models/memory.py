"""Memory layer models (trade-trace-w251 / M3 constraint pass).

The M0 stub used ``extra='allow'`` purely for import-path stabilization. The M3
pass tightens it:

- ``extra='forbid'`` rejects unknown top-level fields (required-field-matrix
  enforcement). Arbitrary structured payloads still live in the explicit
  ``meta_json`` dict.
- Bi-temporal validity: where both are present, ``valid_to`` MUST NOT precede
  ``valid_from`` per PRD §314 and operability.md §2.
- Enum exhaustion: ``node_type`` is a ``StrEnum`` field, so Pydantic rejects any
  value outside {observation, reflection, playbook_rule} at validation time.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trade_trace.models._shared import check_bitemporal


class NodeType(StrEnum):
    OBSERVATION = "observation"
    REFLECTION = "reflection"
    PLAYBOOK_RULE = "playbook_rule"


class MemoryNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    node_type: NodeType
    version: int = 1
    parent_node_id: str | None = None
    title: str | None = None
    body: str
    meta_json: dict[str, Any] = Field(default_factory=dict)
    confidence_base: float = 1.0
    decay_rate_per_day: float | None = None
    importance: int = 5
    created_at: datetime | None = None
    actor_id: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    invalidated_at: datetime | None = None
    invalidated_by: str | None = None

    @model_validator(mode="after")
    def _validate_bitemporal(self) -> Self:
        check_bitemporal(self.valid_from, self.valid_to)
        return self
