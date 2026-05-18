"""`review.bundle` contract stub per PRD §4.2 + reports.md §5.

The contract ships in MVP so external review-tool authors and agents
can introspect the surface; the bundle generation, hash computation, and
redaction passes are P1. At M1 the tool returns
`UNSUPPORTED_CAPABILITY` with `details.reason='implementation_deferred_p1'`
and a `journal.schema review.bundle` call returns the Pydantic input/output
schemas so the agent knows what to expect when the P1 implementation lands.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.tools.errors import ToolError


class ReviewBundleInput(BaseModel):
    """Input contract for review.bundle (P1 implementation).

    Documented here so journal.schema can surface it now; the handler
    refuses calls with UNSUPPORTED_CAPABILITY until P1."""

    model_config = ConfigDict(extra="allow")

    filter: dict[str, Any] = Field(default_factory=dict, description="ReportFilter (reports.md §2)")
    max_records: int = Field(default=25, ge=1, le=200)
    include_sources: bool = True
    include_reflections: bool = True
    include_playbook: bool = True
    max_examples_per_record: int = Field(default=3, ge=0, le=20)


class ReviewBundleOutput(BaseModel):
    """Output contract for review.bundle (P1 implementation)."""

    model_config = ConfigDict(extra="allow")

    filter: dict[str, Any]
    selected: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    reflections: list[dict[str, Any]] = Field(default_factory=list)
    playbook_versions: list[dict[str, Any]] = Field(default_factory=list)
    report_summaries: dict[str, Any] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)
    suggested_prompts: list[str] = Field(default_factory=list)
    bundle_hash: str


def _review_bundle_handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    raise ToolError(
        ErrorCode.UNSUPPORTED_CAPABILITY,
        "review.bundle: implementation deferred to P1; the contract is "
        "introspectable via journal.schema. See reports.md §5.",
        details={
            "reason": "implementation_deferred_p1",
            "schema_doc": "docs/architecture/reports.md#5-reviewbundle",
        },
    )


def register_review_bundle(registry: ToolRegistry) -> None:
    registry.register(
        "review.bundle",
        _review_bundle_handler,
        description=(
            "[P1 contract; M1 stub] Packages a bounded case set as deterministic "
            "JSON for an external reviewer per reports.md §5. Returns "
            "UNSUPPORTED_CAPABILITY at M1; the contract and schema are stable."
        ),
    )
