"""MCP server adapter (shell).

The full MCP transport (stdio framing, JSON-RPC, streaming primitives) is
wired up by a follow-up bead. This module exposes a function-shaped adapter
that the parity test uses to verify CLI and MCP land on the same core
dispatch path — which is the M0 deliverable. The actual `mcp` SDK is an
optional install extra; the import here is lazy so the package itself
doesn't require it.
"""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.envelope import ErrorEnvelope, SuccessEnvelope
from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.core import dispatch


def mcp_call(
    tool_name: str,
    args: dict[str, Any] | None = None,
    *,
    actor_id: str = "agent:default",
    request_id: str | None = None,
    registry: ToolRegistry | None = None,
) -> SuccessEnvelope | ErrorEnvelope:
    """In-process MCP-style invocation. Returns the same envelope shape as
    the CLI adapter (parity test asserts deep-equality after normalization).

    Per contracts.md §3.2, every MCP envelope carries `mcp_transport_hints`
    as a (possibly empty) dict identifying transport-level framing/streaming
    capabilities. The in-process shim populates an empty hint dict so the
    structure is consistent across stdio and in-process callers. The shim
    leaves `cli_human_hint` null because prose is a CLI-only affordance.
    """

    envelope = dispatch(
        tool_name,
        args or {},
        actor_id=actor_id,
        request_id=request_id,
        registry=registry,
    )
    envelope.meta.mcp_transport_hints = {}
    return envelope


def serve_stdio() -> None:  # pragma: no cover
    """Placeholder for the real stdio MCP server.

    Wiring the `mcp` SDK happens in a follow-up bead (the package's optional
    `[mcp]` install extra ships the dependency). When implemented, this
    function will:

    1. Construct the default registry (which re-validates CLI name uniqueness).
    2. Register every tool in the registry as an MCP tool with the same
       schema the CLI exposes via `--*-json` arguments.
    3. Dispatch incoming calls through `mcp_call` so the parity contract is
       preserved transport-by-transport.
    """

    raise NotImplementedError(
        "stdio MCP server is wired up in a follow-up bead; the in-process "
        "adapter `mcp_call` already shares core semantics with the CLI."
    )
