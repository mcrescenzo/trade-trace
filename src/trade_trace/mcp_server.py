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

from trade_trace.contracts.envelope import ErrorEnvelope, Meta, SuccessEnvelope, error_envelope
from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.schema_validation import (
    MCP_STDIO_FULL_SCHEMA,
    reportable_schema_validation_error,
)
from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.core import default_registry, dispatch, new_request_id

DEFAULT_MCP_ACTOR_ID = "agent:mcp-default"


from trade_trace.security.credential_keys import (  # noqa: E402
    SECRET_TRANSPORT_HINT_KEYS,
)


def stdio_actor_id(env: Mapping[str, str] | None = None) -> str:
    """Resolve the actor id for the future stdio transport.

    The stdio server will not infer identity from network/session metadata. It
    may accept an explicit MCP_ACTOR_ID environment override, otherwise it uses
    a deterministic local default. Grammar validation is still performed by the
    shared dispatcher on every call.
    """

    env = env or {}
    return env.get("MCP_ACTOR_ID") or DEFAULT_MCP_ACTOR_ID


def mcp_tool_specs(
    registry: ToolRegistry | None = None,
    *,
    include_admin: bool = False,
    include_legacy: bool = False,
) -> list[dict[str, Any]]:
    """Return the MCP tool catalog from the explicit/default registry only.

    This is intentionally a tiny seam for the later stdio implementation: no
    plugin discovery, entry-point loading, dynamic import, eval, or exec belongs
    on the transport boundary. The returned dictionaries are schema/listing
    data only; handler callables and transport/auth/secret hints are never
    exposed.
    """

    reg = registry if registry is not None else default_registry()
    specs: list[dict[str, Any]] = []
    for registration in reg.public_registrations(
        include_admin=include_admin,
        include_legacy=include_legacy,
    ):
        metadata = registration.metadata()
        description = registration.description
        if metadata.get("usage_summary"):
            description = f"{description} Usage: {metadata['usage_summary']}" if description else metadata["usage_summary"]
        if metadata.get("examples"):
            description = f"{description} Example: {metadata['examples'][0]}" if description else f"Example: {metadata['examples'][0]}"
        spec = {
            "name": registration.name,
            "description": description,
            "input_schema": registration.json_schema or {},
            "is_write": registration.is_write,
            "metadata": metadata,
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


def _stdio_validation_error(
    tool_name: str,
    message: str,
    *,
    actor_id: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a Trade Trace envelope for stdio boundary validation failures."""

    meta = Meta(tool=tool_name, actor_id=actor_id, request_id=new_request_id())
    meta.mcp_transport_hints = {}
    envelope = error_envelope(
        meta,
        ErrorCode.VALIDATION_ERROR,
        message,
        details or {"tool": tool_name},
    )
    return envelope.model_dump(mode="json", exclude_none=True)


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
    include_admin = os.environ.get("MCP_INCLUDE_ADMIN") == "1"
    server = Server("trade-trace")

    @server.list_tools()
    async def _list_tools() -> list[Any]:
        return [
            types.Tool(
                name=spec["name"],
                description=spec["description"],
                inputSchema=spec["input_schema"] or {"type": "object", "properties": {}},
            )
            for spec in mcp_tool_specs(reg, include_admin=include_admin)
        ]

    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        actor_id = stdio_actor_id(os.environ)
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _stdio_validation_error(
                name,
                "MCP tool arguments must be a JSON object",
                actor_id=actor_id,
                details={
                    "tool": name,
                    "field": "arguments",
                    "expected": "object",
                    "actual": type(arguments).__name__,
                },
            )

        registration = reg.get(name) if name in reg.names() else None
        schema = registration.json_schema if registration is not None else None
        if schema:
            validation_error = reportable_schema_validation_error(
                tool=name,
                instance=arguments,
                schema=schema,
                policy=MCP_STDIO_FULL_SCHEMA,
            )
            if validation_error is not None:
                return _stdio_validation_error(
                    name,
                    validation_error.message,
                    actor_id=actor_id,
                    details=validation_error.details,
                )

        envelope = mcp_call(
            name,
            arguments,
            actor_id=actor_id,
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
