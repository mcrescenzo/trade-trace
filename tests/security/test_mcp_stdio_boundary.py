"""Security-boundary contracts for the future MCP stdio server.

These tests intentionally land before the real stdio transport. They pin the
safe seam that trade-trace-46p must use: stdio-only by default, catalog exposure
from default_registry only, no dynamic import/exec/plugin discovery, no secret
transport hints, and a deterministic MCP actor default.
"""

from __future__ import annotations

import asyncio
import builtins
import importlib
import json
import socket
from typing import Any

import pytest
from mcp import types

import trade_trace.mcp_server as mcp_server
from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.mcp_server import (
    SECRET_TRANSPORT_HINT_KEYS,
    _build_stdio_server,
    mcp_call,
    mcp_tool_specs,
    serve_stdio,
    stdio_actor_id,
)
from trade_trace.security.credential_keys import PROJECT_CREDENTIAL_KEYS  # noqa: E402


def _noop_handler(args: dict[str, Any], ctx: Any) -> dict[str, Any]:  # noqa: ARG001
    return {"ok": True}


def test_serve_stdio_opens_no_tcp_listener_by_default(monkeypatch):
    """The MCP transport is stdio-only and must not bind/listen/connect.

    The future MCP transport is stdio-only. This test does not open sockets; it
    replaces bind/listen/connect with fail-fast sentinels and then exercises the
    current stub path.
    """

    def _fail_socket(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        raise AssertionError("MCP stdio boundary must not open TCP sockets by default")

    monkeypatch.setattr(socket.socket, "bind", _fail_socket, raising=True)
    monkeypatch.setattr(socket.socket, "listen", _fail_socket, raising=True)
    monkeypatch.setattr(socket.socket, "connect", _fail_socket, raising=True)

    async def _stop_after_boundary_check(registry=None):  # noqa: ANN001, ARG001
        return None

    monkeypatch.setattr(mcp_server, "_serve_stdio_async", _stop_after_boundary_check)

    try:
        serve_stdio()
    except AssertionError:
        raise


def test_mcp_tool_specs_are_derived_from_supplied_registry_only():
    """A registry argument is authoritative; no global/plugin discovery is mixed in."""

    registry = ToolRegistry()
    registry.register(
        "boundary.echo",
        _noop_handler,
        description="test-only MCP boundary tool",
        json_schema={"type": "object", "properties": {"message": {"type": "string"}}},
    )
    registry.validate()

    specs = mcp_tool_specs(registry)

    assert [spec["name"] for spec in specs] == ["boundary.echo"]
    assert specs[0]["input_schema"]["properties"]["message"]["type"] == "string"
    assert "handler" not in specs[0]


def test_mcp_tool_specs_default_registry_matches_dispatch_known_tools():
    """Default exposure is exactly the process default_registry tool surface."""

    specs = mcp_tool_specs()
    exposed = {spec["name"] for spec in specs}

    missing = mcp_call("definitely.not_registered", {}).model_dump(mode="json")["error"][
        "details"
    ]["known_tools"]
    assert exposed == set(missing)
    assert "tool.schema" in exposed


def test_mcp_tool_specs_do_not_use_dynamic_import_exec_or_eval():
    """Tool listing must not import plugins or execute dynamic code at boundary time."""

    registry = ToolRegistry()
    registry.register("boundary.static", _noop_handler)
    registry.validate()

    original_import = builtins.__import__
    original_import_module = importlib.import_module
    original_eval = builtins.eval
    original_exec = builtins.exec

    def _forbid(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        raise AssertionError("dynamic import/exec/eval is outside the MCP boundary")

    # Restore immediately inside the test; leaving these patched until pytest
    # teardown breaks pytest's own reporting/import machinery.
    builtins.__import__ = _forbid
    importlib.import_module = _forbid
    builtins.eval = _forbid
    builtins.exec = _forbid
    try:
        assert mcp_tool_specs(registry)[0]["name"] == "boundary.static"
    finally:
        builtins.__import__ = original_import
        importlib.import_module = original_import_module
        builtins.eval = original_eval
        builtins.exec = original_exec


def test_mcp_tool_specs_expose_no_secret_or_transport_hint_keys():
    """Schema/list output must not leak auth/secret/transport hint affordances."""

    rendered = json.dumps(mcp_tool_specs(), sort_keys=True).lower()
    forbidden_fragments = sorted(
        PROJECT_CREDENTIAL_KEYS
        | {
            "access_key",
            "credential",
            "credentials",
            "secret",
            "token",
        }
    ) + [
        "transport_hint",
        "mcp_transport_hints",
    ]

    assert not [fragment for fragment in forbidden_fragments if fragment in rendered]


def test_mcp_secret_transport_hint_keys_cover_project_credential_vocabulary():
    """MCP boundary guard stays aligned with the broader no-credential audit."""

    assert PROJECT_CREDENTIAL_KEYS <= SECRET_TRANSPORT_HINT_KEYS


@pytest.mark.parametrize(
    "credential_key",
    [
        "refresh_token",
        "oauth_token",
        "passphrase",
        "broker_token",
        "trading_password",
        "signing_key",
    ],
)
def test_mcp_tool_specs_fail_closed_on_secret_shaped_schema_key(credential_key: str):
    registry = ToolRegistry()
    registry.register(
        "boundary.bad_schema",
        _noop_handler,
        json_schema={"type": "object", "properties": {credential_key: {"type": "string"}}},
    )
    registry.validate()

    with pytest.raises(AssertionError, match=credential_key):
        mcp_tool_specs(registry)


def test_stdio_actor_id_defaults_to_valid_agent_actor_and_accepts_explicit_env_override():
    assert stdio_actor_id({}) == "agent:mcp-default"
    assert stdio_actor_id({"MCP_ACTOR_ID": "agent:alice"}) == "agent:alice"


def test_mcp_call_existing_default_actor_remains_unchanged_until_stdio_46p():
    """The in-process shim is not the stdio server; 46p will wire stdio_actor_id."""

    env = mcp_call("journal.status", {})
    assert env.meta.actor_id == "agent:default"


def _stdio_call_result(server, name: str, arguments: Any):  # noqa: ANN001
    request = types.CallToolRequest.model_construct(
        params=types.CallToolRequestParams.model_construct(name=name, arguments=arguments)
    )
    return server.request_handlers[types.CallToolRequest](request)


def test_stdio_schema_validation_failure_returns_trade_trace_error_envelope(monkeypatch):
    monkeypatch.setenv("MCP_ACTOR_ID", "agent:stdio-boundary")
    registry = ToolRegistry()
    registry.register(
        "boundary.echo",
        _noop_handler,
        json_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    )
    registry.validate()

    result = asyncio.run(_stdio_call_result(_build_stdio_server(registry), "boundary.echo", {}))
    structured = result.root.structuredContent
    assert structured is not None

    assert structured["ok"] is False
    assert structured["error"]["code"] == "VALIDATION_ERROR"
    assert structured["error"]["details"]["tool"] == "boundary.echo"
    assert structured["error"]["details"]["validator"] == "required"
    assert structured["meta"]["tool"] == "boundary.echo"
    assert structured["meta"]["actor_id"] == "agent:stdio-boundary"
    assert structured["meta"]["request_id"]
    assert structured["meta"]["contract_version"]
    assert structured["meta"]["mcp_transport_hints"] == {}


def test_stdio_wrong_type_arguments_return_trade_trace_error_envelope(monkeypatch):
    monkeypatch.setenv("MCP_ACTOR_ID", "agent:stdio-boundary")
    registry = ToolRegistry()
    registry.register("boundary.echo", _noop_handler)
    registry.validate()

    result = asyncio.run(
        _stdio_call_result(_build_stdio_server(registry), "boundary.echo", ["not", "an", "object"])
    )
    structured = result.root.structuredContent
    assert structured is not None

    assert structured["ok"] is False
    assert structured["error"]["code"] == "VALIDATION_ERROR"
    assert structured["error"]["details"] == {
        "tool": "boundary.echo",
        "field": "arguments",
        "expected": "object",
        "actual": "list",
    }
    assert structured["meta"]["tool"] == "boundary.echo"
    assert structured["meta"]["actor_id"] == "agent:stdio-boundary"
    assert structured["meta"]["request_id"]
    assert structured["meta"]["contract_version"]
