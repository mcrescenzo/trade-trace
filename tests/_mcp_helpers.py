"""Shared helpers for exact duplicate MCP test call shapes.

Keep this module small: only mechanical, behavior-preserving helpers whose
bodies were repeated verbatim across tests belong here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from trade_trace.mcp_server import mcp_call


def mcp_default(home: Path, tool: str, args: dict[str, Any] | None = None):
    """Call an MCP tool with the repeated agent:default actor shape."""

    payload = {"home": str(home), **(args or {})}
    return mcp_call(tool, payload, actor_id="agent:default")


def envelope_default(home: Path, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool and return the repeated JSON envelope shape."""

    payload = {"home": str(home), **args}
    return mcp_call(tool, payload, actor_id="agent:default").model_dump(
        mode="json", exclude_none=True
    )
