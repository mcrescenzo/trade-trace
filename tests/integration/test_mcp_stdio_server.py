from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HAS_MCP = importlib.util.find_spec("mcp") is not None
pytestmark = pytest.mark.skipif(not HAS_MCP, reason="mcp SDK optional extra is not installed")

from trade_trace.mcp_server import mcp_call, mcp_tool_specs


def _encode(message: dict[str, Any]) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode() + b"\n"


def _read_message(stream) -> dict[str, Any]:
    line = stream.readline()
    assert line, "server closed stdout before a complete MCP message"
    return json.loads(line)


class McpProcess:
    def __init__(self, tmp_path: Path, actor_id: str = "agent:stdio-test") -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src")
        env["MCP_ACTOR_ID"] = actor_id
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "trade_trace.mcp_server"],
            cwd=Path.cwd(),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._next_id = 1

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.proc.stdin is not None
        request_id = self._next_id
        self._next_id += 1
        self.proc.stdin.write(_encode({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}))
        self.proc.stdin.flush()
        assert self.proc.stdout is not None
        response = _read_message(self.proc.stdout)
        assert response["id"] == request_id
        assert "error" not in response, response
        return response["result"]

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(_encode({"jsonrpc": "2.0", "method": method, "params": params or {}}))
        self.proc.stdin.flush()

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)


def _initialized_server(tmp_path: Path, actor_id: str = "agent:stdio-test") -> McpProcess:
    server = McpProcess(tmp_path, actor_id=actor_id)
    result = server.request(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "trade-trace-tests", "version": "0"},
        },
    )
    assert result["serverInfo"]["name"] == "trade-trace"
    assert result["serverInfo"].get("version")
    assert isinstance(result["capabilities"], dict)
    assert "tools" in result["capabilities"]
    server.notify("notifications/initialized")
    return server


def test_stdio_initialize_handshake_returns_trade_trace_server_info(tmp_path: Path):
    server = _initialized_server(tmp_path)
    try:
        result = server.request("tools/list")
        assert "tools" in result
    finally:
        server.close()


def test_stdio_list_tools_exposes_all_registered_tools_with_input_schema(tmp_path: Path):
    server = _initialized_server(tmp_path)
    try:
        result = server.request("tools/list")
        tools = result["tools"]
        assert {tool["name"] for tool in tools} == {spec["name"] for spec in mcp_tool_specs()}
        assert len(tools) >= 30
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert isinstance(tool["inputSchema"], dict)
            assert tool["inputSchema"].get("type") == "object"
    finally:
        server.close()


def test_stdio_tools_call_report_filter_schema_matches_in_process_mcp_call(tmp_path: Path):
    expected = mcp_call(
        "report.filter_schema",
        {},
        actor_id="agent:stdio-test",
    ).model_dump(mode="json", exclude_none=True)

    server = _initialized_server(tmp_path, actor_id="agent:stdio-test")
    try:
        result = server.request(
            "tools/call",
            {"name": "report.filter_schema", "arguments": {}},
        )
        assert result["structuredContent"]["data"] == expected["data"]
        assert result["structuredContent"]["ok"] == expected["ok"]
        assert result["structuredContent"]["meta"]["actor_id"] == "agent:stdio-test"
    finally:
        server.close()


def test_stdio_tools_call_venue_add_dry_run_returns_success_without_persisting(tmp_path: Path):
    home = tmp_path / "home"
    init = mcp_call("journal.init", {"home": str(home)}, actor_id="agent:stdio-test")
    assert init.ok

    venue_id = "ven_stdio_dry_run"
    db_path = home / "trade-trace.sqlite"

    server = _initialized_server(tmp_path, actor_id="agent:stdio-test")
    try:
        result = server.request(
            "tools/call",
            {
                "name": "venue.add",
                "arguments": {
                    "home": str(home),
                    "id": venue_id,
                    "name": "Stdio Dry Run Venue",
                    "kind": "exchange",
                    "idempotency_key": "stdio-dry-run-venue-add",
                    "_dry_run": True,
                },
            },
        )
        structured = result["structuredContent"]
        assert structured["ok"] is True
        assert structured["data"]["id"] == venue_id
        assert structured["meta"]["dry_run"] is True
        assert structured["meta"]["actor_id"] == "agent:stdio-test"
    finally:
        server.close()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT id FROM venues WHERE id = ?", (venue_id,)).fetchone()
    assert row is None
