"""Success/error envelopes per docs/architecture/contracts.md §3-§4."""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from trade_trace.contracts.errors import ErrorCode
from trade_trace.version import CONTRACT_VERSION

REPORT_STANDARD_META_KEYS: Final[tuple[str, ...]] = (
    "bin_policy",
    "cli_human_hint",
    "mcp_transport_hints",
    "truncated",
    "next_cursor",
    "sample_warning",
)
"""The `report.*` envelope meta surface that contracts.md §3.2 requires to
be explicitly emitted (as JSON `null` when unset). Write-only fields
(`event_id`, `idempotent_replay`) are NOT in this set — read tools omit
them entirely so an agent can distinguish "no event written" from "an
event was written and we forgot to surface its id".
"""


class Meta(BaseModel):
    """Envelope metadata. `tool`, `actor_id`, `request_id`, and `contract_version`
    are always set on success and error envelopes."""

    model_config = ConfigDict(extra="allow")

    tool: str
    actor_id: str
    request_id: str
    contract_version: str = CONTRACT_VERSION
    event_id: int | None = None
    idempotent_replay: bool | None = None
    idempotency_disabled: bool | None = None
    bin_policy: str | None = None
    budget_applied: bool | None = None
    sample_warning: str | None = None
    truncated: bool | None = None
    next_cursor: str | None = None
    cli_human_hint: str | None = None
    mcp_transport_hints: dict[str, Any] | None = None
    dry_run: bool | None = None
    preview_only: bool | None = None
    generated_at: str | None = None
    schema_version: int | None = None
    package_version: str | None = None
    normalized_filter: dict[str, Any] | None = None
    retrieval_strategy_metadata: dict[str, Any] | None = None


class SuccessEnvelope(BaseModel):
    """{"ok": true, "data": {...}, "meta": {...}}."""

    ok: Literal[True] = True
    data: dict[str, Any] = Field(default_factory=dict)
    meta: Meta


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    """{"ok": false, "error": {...}, "meta": {...}}."""

    ok: Literal[False] = False
    error: ErrorBody
    meta: Meta


def dump_envelope(env: SuccessEnvelope | ErrorEnvelope) -> dict[str, Any]:
    """Serialize an envelope to a JSON-ready dict.

    For tools whose name starts with `report.`, the standard report meta
    surface (per contracts.md §3.2 / bead trade-trace-u5s) is forced into
    the output as JSON `null` when unset, so agents see a stable set of
    keys on every report envelope and can branch on presence vs. value
    without re-reading the docs.

    Non-report envelopes use the historical `exclude_none=True` shape so
    write-tool envelopes don't carry irrelevant `bin_policy`/`sample_warning`
    nulls.
    """

    body = env.model_dump(mode="json", exclude_none=True)
    tool = body.get("meta", {}).get("tool", "")
    if isinstance(tool, str) and tool.startswith("report."):
        for key in REPORT_STANDARD_META_KEYS:
            body["meta"].setdefault(key, None)
    return body
