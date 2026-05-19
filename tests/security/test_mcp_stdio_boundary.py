"""Security-boundary contracts for the future MCP stdio server.

These tests intentionally land before the real stdio transport. They pin the
safe seam that trade-trace-46p must use: stdio-only by default, catalog exposure
from default_registry only, no dynamic import/exec/plugin discovery, no secret
transport hints, and a deterministic MCP actor default.
"""

from __future__ import annotations

import builtins
import importlib
import json
import socket
from typing import Any

import pytest

import trade_trace.mcp_server as mcp_server
from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.mcp_server import (
    SECRET_TRANSPORT_HINT_KEYS,
    mcp_call,
    mcp_tool_specs,
    serve_stdio,
    stdio_actor_id,
)

PROJECT_CREDENTIAL_KEYS = {
    "api_key",
    "access_token",
    "refresh_token",
    "auth_token",
    "bearer_token",
    "secret_key",
    "client_secret",
    "password",
    "passphrase",
    "wallet_seed",
    "wallet_seed_phrase",
    "seed_phrase",
    "mnemonic",
    "private_key",
    "signing_key",
    "signing_secret",
    "broker_token",
    "trading_password",
    "session_token",
    "oauth_token",
}


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
