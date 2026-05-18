"""M1 ledger model stubs.

These models capture the M1 schema surface from PRD §3.1 enough for the M0
import contract; constraint enforcement (required-field matrix, idempotency,
bi-temporal validity) lands with M1 implementation beads. Free-text fields are
deliberately not capped here — operability.md §8 blob caps are enforced at the
write-tool boundary, not at model load.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DecisionType(str, Enum):
    WATCH = "watch"
    SKIP = "skip"
    PAPER_ENTER = "paper_enter"
    PAPER_EXIT = "paper_exit"
    ACTUAL_ENTER = "actual_enter"
    ACTUAL_EXIT = "actual_exit"
    ADD = "add"
    REDUCE = "reduce"
    HOLD = "hold"
    INVALIDATE_THESIS = "invalidate_thesis"
    UPDATE_THESIS = "update_thesis"
    RESOLVED = "resolved"
    REVIEW = "review"


class OutcomeStatus(str, Enum):
    RESOLVED_FINAL = "resolved_final"
    RESOLVED_PROVISIONAL = "resolved_provisional"
    AMBIGUOUS = "ambiguous"
    DISPUTED = "disputed"
    VOID = "void"
    CANCELLED = "cancelled"


class _Row(BaseModel):
    """Common metadata across ledger rows. See PRD §2 common metadata block."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    created_at: datetime | None = None
    actor_id: str | None = None
    idempotency_key: str | None = None
    agent_id: str | None = None
    model_id: str | None = None
    environment: str | None = None
    run_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class Snapshot(_Row):
    instrument_id: str
    captured_at: datetime
    source: str | None = None
    source_url: str | None = None
    price: float | None = None
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    spread: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    implied_probability: float | None = None
    liquidity_depth_json: dict[str, Any] = Field(default_factory=dict)


class Thesis(_Row):
    instrument_id: str
    version: int = 1
    parent_thesis_id: str | None = None
    side: str
    time_horizon_at: datetime | None = None
    confidence_label: str | None = None
    body: str
    falsification_criteria: str | None = None
    exit_triggers: str | None = None
    risk_notes: str | None = None
    strategy_id: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    invalidated_at: datetime | None = None
    invalidated_by: str | None = None


class ForecastOutcome(BaseModel):
    """A single row of the `forecast_outcomes` table.

    Binary forecasts MUST have exactly two rows with distinct case-insensitive
    labels whose probabilities sum to 1.0 within 1e-6 (PRD §3.1, scoring.md §2).
    """

    model_config = ConfigDict(extra="allow")

    outcome_label: str
    probability: float
    lower_bound: float | None = None
    upper_bound: float | None = None


class Forecast(_Row):
    thesis_id: str
    kind: str = "binary"
    resolution_at: datetime | None = None
    yes_label: str | None = None
    resolution_rule_text: str | None = None
    scoring_support: str = "supported"
    scoring_state: str = "pending"
    outcomes: list[ForecastOutcome] = Field(default_factory=list)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    invalidated_at: datetime | None = None
    invalidated_by: str | None = None


class Decision(_Row):
    instrument_id: str
    type: DecisionType
    thesis_id: str | None = None
    forecast_id: str | None = None
    snapshot_id: str | None = None
    side: str | None = None
    quantity: float | None = None
    price: float | None = None
    fees: float | None = None
    slippage: float | None = None
    reason: str | None = None
    playbook_version_id: str | None = None
    review_by: datetime | None = None
    strategy_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class Outcome(_Row):
    instrument_id: str
    resolved_at: datetime
    outcome_label: str
    outcome_value: float | None = None
    status: OutcomeStatus
    source: str | None = None
    confidence: float | None = None


class Source(_Row):
    kind: str
    ref: str | None = None
    title: str | None = None
    note: str | None = None
    stance: str = "neutral"
    freshness_at: datetime | None = None
    content_hash: str | None = None
    captured_at: datetime | None = None
    uri: str | None = None
    media_type: str | None = None
    storage_kind: str = "inline_text"
    retrieved_at: datetime | None = None
    source_author: str | None = None
    publisher: str | None = None
    excerpt: str | None = None
    extracted_text: str | None = None
    summary: str | None = None
    hash_algorithm: str | None = None
    redaction_status: str = "none"
    license_or_terms_note: str | None = None


class Strategy(_Row):
    name: str
    slug: str
    description: str | None = None
    hypothesis: str | None = None
    status: str = "active"
    updated_at: datetime | None = None
