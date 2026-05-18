"""Memory layer model stubs.

The M3 milestone (per PRD §8) lights these up with real validation and
edge-endpoint checks. M0 ships the type surface so import-paths stabilize
and `from trade_trace.models import MemoryNode` succeeds.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NodeType(str, Enum):
    OBSERVATION = "observation"
    REFLECTION = "reflection"
    PLAYBOOK_RULE = "playbook_rule"


class MemoryNode(BaseModel):
    model_config = ConfigDict(extra="allow")

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
