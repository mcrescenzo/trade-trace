"""`import.validate` / `import.commit` contract stubs per PRD §4.7 +
docs/architecture/imports.md.

M1 ships the contract surface; the implementation lands in P1. The MVP
commitment is that every core write tool from §4.0–§4.6 is callable from
the same JSONL handler the importer will use — and that commitment holds
today: every registered write tool dispatches through the same
`trade_trace.core.dispatch`, so the P1 importer can layer over the
existing surface without bespoke per-tool glue.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.tools.errors import ToolError


class ImportJSONLLine(BaseModel):
    """The canonical line shape per imports.md §2.1.

    Importer-produced files use `{tool, args}` per line. The exporter
    additionally injects `_event_id`, `_event_type`, `_actor_id`,
    `_created_at`, `_contract_version` as transport metadata; the importer
    ignores underscore-prefixed keys so exporter output is directly
    replayable.
    """

    model_config = ConfigDict(extra="allow")

    tool: str = Field(description="MCP tool name; same as in-process dispatch")
    args: dict[str, Any] = Field(default_factory=dict)


class ImportValidateOutput(BaseModel):
    """Output of `import.validate` per imports.md §3.1."""

    model_config = ConfigDict(extra="allow")

    validated: int = 0
    would_create: int = 0
    would_replay: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    id_strategy: str = "server_assigned"  # or "caller_assigned"


class ImportCommitOutput(BaseModel):
    """Output of `import.commit` per imports.md §3.1."""

    model_config = ConfigDict(extra="allow")

    validated: int = 0
    would_create: int = 0
    would_replay: int = 0
    committed_count: int = 0
    committed_event_ids: list[int] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


def _import_validate(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    raise ToolError(
        ErrorCode.UNSUPPORTED_CAPABILITY,
        "import.validate: implementation deferred to P1; the JSONL line "
        "shape and validation semantics are documented in imports.md §2-§3.",
        details={
            "reason": "implementation_deferred_p1",
            "schema_doc": "docs/architecture/imports.md#3-cli-and-mcp-surface",
            "import_ready_writers": [
                "venue.add", "instrument.add", "snapshot.add",
                "thesis.add", "forecast.add", "forecast.supersede",
                "decision.add", "outcome.add", "resolve.record",
                "source.add",
                "source.attach_to_thesis", "source.attach_to_decision",
                "source.attach_to_forecast",
            ],
        },
    )


def _import_commit(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    raise ToolError(
        ErrorCode.UNSUPPORTED_CAPABILITY,
        "import.commit: implementation deferred to P1; every write tool "
        "in the MVP surface accepts the same JSONL line shape, so the P1 "
        "importer can layer over the existing dispatch without bespoke glue.",
        details={
            "reason": "implementation_deferred_p1",
            "schema_doc": "docs/architecture/imports.md#3-cli-and-mcp-surface",
        },
    )


def register_import_stubs(registry: ToolRegistry) -> None:
    registry.register(
        "import.validate",
        _import_validate,
        description=(
            "[P1 contract; M1 stub] Dry-run validate a JSONL file/directory. "
            "Returns UNSUPPORTED_CAPABILITY at M1; line shape per imports.md §2."
        ),
    )
    registry.register(
        "import.commit",
        _import_commit,
        description=(
            "[P1 contract; M1 stub] Replay a JSONL file/directory through the "
            "core dispatch with single-transaction or per-row mode. Returns "
            "UNSUPPORTED_CAPABILITY at M1."
        ),
    )
