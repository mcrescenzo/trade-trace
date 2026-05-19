"""ReportFilter Pydantic schema per docs/architecture/reports.md §2 (trade-trace-fo7).

Shared input shape for every read/report tool. The shape is pinned in this
module so a future report addition cannot drift from the contract: every
field is Pydantic-validated, unknown fields are rejected with VALIDATION_ERROR,
and `report.filter_schema` returns the canonical JSON Schema for runtime
introspection.

Sentinel semantics for `strategy.strategy_id` (reports.md §2.1 + §2.12):
- omitted / `null` → no strategy filter applied
- `"__none__"`     → select rows where strategy_id IS NULL
- any other string → single strategy id (UUID-shaped) or slug, resolved server-side
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

STRATEGY_NONE_SENTINEL = "__none__"


_STRICT = ConfigDict(extra="forbid")


class TimeWindowFilter(BaseModel):
    model_config = _STRICT

    created_at_gte: str | None = Field(default=None, description="ISO 8601 UTC")
    created_at_lt: str | None = None
    decision_at_gte: str | None = Field(
        default=None, description="decisions.created_at lower bound"
    )
    decision_at_lt: str | None = None
    resolved_at_gte: str | None = Field(
        default=None, description="outcomes.resolved_at lower bound"
    )
    resolved_at_lt: str | None = None


class ActorsFilter(BaseModel):
    model_config = _STRICT

    actor_id: list[str] = Field(default_factory=list)
    agent_id: list[str] = Field(default_factory=list)
    model_id: list[str] = Field(default_factory=list)
    environment: list[str] = Field(
        default_factory=list,
        description="paper|actual_recorded|simulation|backtest_import|manual_review",
    )
    run_id: list[str] = Field(default_factory=list)


class StrategyFilter(BaseModel):
    model_config = _STRICT

    strategy_id: str | None = Field(
        default=None,
        description="Single id, slug, '__none__', or null (no filter).",
    )
    playbook_id: list[str] = Field(default_factory=list)
    playbook_version_id: list[str] = Field(default_factory=list)


class InstrumentFilter(BaseModel):
    model_config = _STRICT

    venue_id: list[str] = Field(default_factory=list)
    venue_kind: list[str] = Field(default_factory=list)
    instrument_id: list[str] = Field(default_factory=list)
    asset_class: list[str] = Field(default_factory=list)
    symbol: list[str] = Field(default_factory=list)


class DecisionFilter(BaseModel):
    model_config = _STRICT

    decision_type: list[str] = Field(
        default_factory=list, description="Any of decisions.type (13 values)."
    )
    side: list[str] = Field(default_factory=list)
    tags_any: list[str] = Field(default_factory=list, description="OR over tag set.")
    tags_all: list[str] = Field(default_factory=list, description="AND over tag set.")
    has_thesis: bool | None = None
    has_forecast: bool | None = None
    has_reflection: bool | None = None
    has_playbook_adherence: bool | None = None


class MarketContextFilter(BaseModel):
    model_config = _STRICT

    spread_bucket: list[str] = Field(
        default_factory=list, description="tight|medium|wide"
    )
    liquidity_bucket: list[str] = Field(
        default_factory=list, description="thin|medium|deep"
    )
    volume_bucket: list[str] = Field(
        default_factory=list, description="low|medium|high"
    )
    market_regime_tag: list[str] = Field(default_factory=list)


class OutcomeFilter(BaseModel):
    model_config = _STRICT

    resolution_status: list[str] = Field(default_factory=list)
    scoring_state: list[str] = Field(default_factory=list)
    score_gte: float | None = Field(
        default=None, description="brier_binary lower bound"
    )
    score_lt: float | None = None
    include_late_recorded: bool = Field(
        default=False,
        description=(
            "dogfood-protocol.md §2.2: false (default) excludes late-recorded "
            "forecasts from calibration aggregates; true includes them with caveat."
        ),
    )


class SourceFilter(BaseModel):
    model_config = _STRICT

    source_kind: list[str] = Field(default_factory=list)
    source_stance: list[str] = Field(
        default_factory=list, description="supports|contradicts|neutral"
    )
    source_freshness_before_decision: bool | None = Field(
        default=None,
        description="bool: was source.freshness_at <= decision.created_at?",
    )


class ReportFilter(BaseModel):
    """Canonical filter shape consumed by every read/report tool.

    Empty arrays mean "no filter on this field"; `null` means unset.
    `extra="forbid"` ensures unknown fields surface as VALIDATION_ERROR
    rather than silently broaden the filter.
    """

    model_config = _STRICT

    time_window: TimeWindowFilter = Field(default_factory=TimeWindowFilter)
    actors: ActorsFilter = Field(default_factory=ActorsFilter)
    strategy: StrategyFilter = Field(default_factory=StrategyFilter)
    instrument: InstrumentFilter = Field(default_factory=InstrumentFilter)
    decision: DecisionFilter = Field(default_factory=DecisionFilter)
    market_context: MarketContextFilter = Field(default_factory=MarketContextFilter)
    outcome: OutcomeFilter = Field(default_factory=OutcomeFilter)
    source: SourceFilter = Field(default_factory=SourceFilter)

    def strategy_filter_mode(self) -> str:
        """Return one of `none`, `is_null`, `match` per the sentinel rules.

        - `none`: omitted / `null` → no strategy filter applied
        - `is_null`: `"__none__"` → select rows where strategy_id IS NULL
        - `match`: any other string → single id/slug (server resolves)
        """

        value = self.strategy.strategy_id
        if value is None:
            return "none"
        if value == STRATEGY_NONE_SENTINEL:
            return "is_null"
        return "match"
