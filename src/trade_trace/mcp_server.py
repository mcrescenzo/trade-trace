"""MCP server adapter.

The stdio transport is intentionally narrow: it exposes only the explicit tool
registry, performs no network listening or dynamic discovery, and dispatches
all tool calls through the same in-process MCP shim used by parity tests. The
`mcp` SDK remains an optional install extra; imports are lazy so the base
package can be installed without MCP server support.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import Any

from trade_trace.contracts.envelope import ErrorEnvelope, SuccessEnvelope
from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.core import default_registry, dispatch

DEFAULT_MCP_ACTOR_ID = "agent:mcp-default"


SECRET_TRANSPORT_HINT_KEYS = {
    "api_key",
    "access_key",
    "access_token",
    "auth_token",
    "bearer_token",
    "broker_token",
    "client_secret",
    "credential",
    "credentials",
    "mnemonic",
    "oauth_token",
    "password",
    "passphrase",
    "private_key",
    "refresh_token",
    "secret",
    "secret_key",
    "seed_phrase",
    "session_token",
    "signing" + "_key",
    "signing_secret",
    "token",
    "trading_password",
    "wallet_seed",
    "wallet_seed_phrase",
}


def stdio_actor_id(env: Mapping[str, str] | None = None) -> str:
    """Resolve the actor id for the future stdio transport.

    The stdio server will not infer identity from network/session metadata. It
    may accept an explicit MCP_ACTOR_ID environment override, otherwise it uses
    a deterministic local default. Grammar validation is still performed by the
    shared dispatcher on every call.
    """

    env = env or {}
    return env.get("MCP_ACTOR_ID") or DEFAULT_MCP_ACTOR_ID


def mcp_tool_specs(registry: ToolRegistry | None = None) -> list[dict[str, Any]]:
    """Return the MCP tool catalog from the explicit/default registry only.

    This is intentionally a tiny seam for the later stdio implementation: no
    plugin discovery, entry-point loading, dynamic import, eval, or exec belongs
    on the transport boundary. The returned dictionaries are schema/listing
    data only; handler callables and transport/auth/secret hints are never
    exposed.
    """

    reg = registry if registry is not None else default_registry()
    specs: list[dict[str, Any]] = []
    for name in reg.names():
        registration = reg.get(name)
        spec = {
            "name": registration.name,
            "description": registration.description,
            "input_schema": registration.json_schema or {},
            "is_write": registration.is_write,
        }
        _assert_no_secret_transport_hints(spec)
        specs.append(spec)
    return specs


def _assert_no_secret_transport_hints(value: Any, path: tuple[str, ...] = ()) -> None:
    """Fail closed if MCP list/schema metadata grows credential-shaped keys."""

    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).lower()
            if key_text in SECRET_TRANSPORT_HINT_KEYS or "transport_hint" in key_text:
                dotted = ".".join((*path, str(key)))
                raise AssertionError(f"secret/transport hint key exposed in MCP tool spec: {dotted}")
            _assert_no_secret_transport_hints(nested, (*path, str(key)))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_no_secret_transport_hints(nested, (*path, str(index)))


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


def _build_stdio_server(registry: ToolRegistry | None = None):
    """Build the low-level MCP SDK server without starting a transport."""

    # MCP is a required base dependency now (trade-trace-o8j5); the
    # narrow try/except remains so any future repackaging that pins
    # against an incompatible MCP SDK surfaces a clean error.
    try:
        from mcp import types
        from mcp.server import Server
    except ImportError as exc:  # pragma: no cover - base dep should always be present
        raise RuntimeError(
            "MCP runtime failed to import even though it is declared as a "
            "base dependency in pyproject.toml. Reinstall trade-trace "
            "(`pip install -e .`) or report this as a packaging bug."
        ) from exc

    reg = registry if registry is not None else default_registry()
    server = Server("trade-trace")

    @server.list_tools()
    async def _list_tools() -> list[Any]:
        return [
            types.Tool(
                name=spec["name"],
                description=spec["description"],
                inputSchema=spec["input_schema"] or {"type": "object", "properties": {}},
            )
            for spec in mcp_tool_specs(reg)
        ]

    @server.call_tool(validate_input=True)
    async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        envelope = mcp_call(
            name,
            arguments,
            actor_id=stdio_actor_id(os.environ),
            registry=reg,
        )
        return envelope.model_dump(mode="json", exclude_none=True)

    return server


async def _serve_stdio_async(registry: ToolRegistry | None = None) -> None:
    from mcp.server.stdio import stdio_server

    server = _build_stdio_server(registry)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def serve_stdio(registry: ToolRegistry | None = None) -> None:  # pragma: no cover
    """Run the trade-trace MCP server on stdio only.

    Actor identity is resolved once per call from ``MCP_ACTOR_ID`` via
    :func:`stdio_actor_id`; if unset, the deterministic default is
    ``agent:mcp-default``. Protocol output is written only by the MCP SDK to stdout;
    callers should send diagnostics to stderr to avoid corrupting JSON-RPC.
    """

    asyncio.run(_serve_stdio_async(registry))


def serve_stdio_main() -> None:  # pragma: no cover
    """Console-script entry point for ``trade-trace-mcp``."""

    serve_stdio()


if __name__ == "__main__":  # pragma: no cover
    serve_stdio_main()
