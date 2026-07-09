"""MCP server adapter.

The stdio transport is intentionally narrow: it exposes only the explicit tool
registry, performs no network listening or dynamic discovery, and dispatches
all tool calls through the same in-process MCP shim used by parity tests. The
`mcp` SDK is a base runtime dependency; imports remain localized so any future
packaging incompatibility surfaces as a clean MCP-boundary error.
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
from trade_trace.security.credential_keys import SECRET_TRANSPORT_HINT_KEYS

DEFAULT_MCP_ACTOR_ID = "agent:mcp-default"
TOP_LEVEL_JSON_SCHEMA_COMBINATORS = ("anyOf", "oneOf", "allOf")


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
    include_experimental: bool = False,
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
        include_experimental=include_experimental,
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
            "input_schema": claude_compatible_mcp_input_schema(registration.json_schema or {}),
            "is_write": registration.is_write,
            "metadata": metadata,
        }
        _assert_no_secret_transport_hints(spec)
        specs.append(spec)
    return specs


def claude_compatible_mcp_input_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return an MCP-advertised schema accepted by Claude Code.

    Claude Code 2.1.150 rejects MCP tool catalogs whose ``input_schema`` has a
    top-level JSON Schema combinator (``anyOf``/``oneOf``/``allOf``). Keep the
    registry schema canonical for runtime validation, but advertise an object
    schema without those top-level keys at the transport boundary.

    The normalized schema remains descriptive: object properties, base required
    fields, and nested constraints are preserved. Only top-level combinators are
    removed, because that is the compatibility rule currently enforced by the
    client and runtime validation below still uses ``registration.json_schema``.
    """

    if not schema:
        return {"type": "object", "properties": {}}
    if not any(key in schema for key in TOP_LEVEL_JSON_SCHEMA_COMBINATORS):
        return dict(schema)

    advertised = {key: value for key, value in schema.items() if key not in TOP_LEVEL_JSON_SCHEMA_COMBINATORS}
    advertised["type"] = "object"
    advertised.setdefault("properties", {})

    note = (
        "MCP compatibility note: top-level JSON Schema combinators from the "
        "canonical runtime schema are omitted from this advertised schema; the "
        "dispatcher still validates calls against the full canonical schema."
    )
    description = advertised.get("description")
    advertised["description"] = f"{description} {note}" if description else note
    advertised["x-trade-trace-mcp-schema-note"] = "top-level combinators omitted for Claude Code compatibility"
    return advertised


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


async def _dispatch_stdio_tool_call(
    name: str,
    arguments: dict[str, Any],
    *,
    actor_id: str,
    registry: ToolRegistry,
) -> dict[str, Any]:
    envelope = await asyncio.to_thread(
        mcp_call,
        name,
        arguments,
        actor_id=actor_id,
        registry=registry,
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
    include_experimental = os.environ.get("MCP_INCLUDE_EXPERIMENTAL") == "1"
    server = Server("trade-trace")

    # Precompute the tool list once at server-build time (bead
    # trade-trace-yt45). The registry, include_admin, and
    # include_experimental inputs are all fixed for the life of this
    # server, so mcp_tool_specs() — which re-runs the recursive
    # _assert_no_secret_transport_hints scan over every spec — produced
    # byte-identical output on every list_tools request. Hoisting it out
    # of the handler turns a per-request O(tools * schema-depth) scan into
    # a one-time cost; the immutable Tool list is simply returned.
    _tool_list: list[Any] = [
        types.Tool(
            name=spec["name"],
            description=spec["description"],
            inputSchema=spec["input_schema"] or {"type": "object", "properties": {}},
        )
        for spec in mcp_tool_specs(
            reg,
            include_admin=include_admin,
            include_experimental=include_experimental,
        )
    ]

    @server.list_tools()
    async def _list_tools() -> list[Any]:
        return _tool_list

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

        registration = reg.by_name.get(name)
        schema = registration.json_schema if registration is not None else None
        if schema:
            validation_error = reportable_schema_validation_error(
                tool=name,
                instance=arguments,
                schema=schema,
                policy=MCP_STDIO_FULL_SCHEMA,
                validator=registration.compiled_validator
                if registration is not None
                else None,
            )
            if validation_error is not None:
                return _stdio_validation_error(
                    name,
                    validation_error.message,
                    actor_id=actor_id,
                    details=validation_error.details,
                )

        return await _dispatch_stdio_tool_call(
            name,
            arguments,
            actor_id=actor_id,
            registry=reg,
        )

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
