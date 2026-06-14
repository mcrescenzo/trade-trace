"""Shared helpers for exact duplicate MCP test call shapes.

Keep this module small: only mechanical, behavior-preserving helpers whose
bodies were repeated verbatim across tests belong here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from trade_trace.events.semantic_keys import TOOL_PRIMARY_EVENT_TYPE
from trade_trace.mcp_server import mcp_call

_LEGACY_EXPLICIT_KEY_WRITE_TOOLS = {
    "forecast.anchor_to_snapshot",
    "import.commit",
    "import.csv_fills",
    "journal.backup",
    "journal.config_set",
    "journal.restore",
    "market.refresh",
    "market.scan.promote",
    "memory.link",
    "memory.reflect",
    "memory.reindex",
    "model.import",
    "outcome.fetch",
    "playbook.upsert",
    "snapshot.fetch",
    "snapshot.fetch_series",
    "source.attach_to_decision",
    "source.attach_to_forecast",
    "source.attach_to_memory_node",
    "source.attach_to_thesis",
    "strategy.upsert",
}


def with_legacy_idempotency_key(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Return args with a deterministic explicit key for non-auto write tools.

    This is an opt-in test helper, not a dispatch monkeypatch: production
    auto-derivation remains exercised for TOOL_PRIMARY_EVENT_TYPE tools, while
    legacy tests for admin/edge/import tools can focus on their domain behavior.
    """

    if (
        tool in _LEGACY_EXPLICIT_KEY_WRITE_TOOLS
        and tool not in TOOL_PRIMARY_EVENT_TYPE
        and not args.get("idempotency_key")
        and args.get("_allow_no_idempotency") is not True
    ):
        structural = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(f"{tool}:{structural}".encode()).hexdigest()[:24]
        return {**args, "idempotency_key": f"test-legacy:{tool}:{digest}"}
    return args


def mcp_default(home: Path, tool: str, args: dict[str, Any] | None = None):
    """Call an MCP tool with the repeated agent:default actor shape."""

    payload = {"home": str(home), **with_legacy_idempotency_key(tool, args or {})}
    return mcp_call(tool, payload, actor_id="agent:default")


def envelope_default(home: Path, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool and return the repeated JSON envelope shape."""

    payload = {"home": str(home), **with_legacy_idempotency_key(tool, args)}
    return mcp_call(tool, payload, actor_id="agent:default").model_dump(
        mode="json", exclude_none=True
    )
