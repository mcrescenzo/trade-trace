"""MCP server adapter (shell).

The full MCP transport (stdio framing, JSON-RPC, streaming primitives) is
wired up by a follow-up bead. This module exposes a function-shaped adapter
that the parity test uses to verify CLI and MCP land on the same core
dispatch path — which is the M0 deliverable. The actual `mcp` SDK is an
optional install extra; the import here is lazy so the package itself
doesn't require it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from trade_trace.contracts.envelope import ErrorEnvelope, SuccessEnvelope
from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.core import default_registry, dispatch

DEFAULT_MCP_ACTOR_ID = "mcp:default"


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
