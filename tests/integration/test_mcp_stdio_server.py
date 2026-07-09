from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

# mcp is a base runtime dependency now (trade-trace-o8j5); no longer
# guarded as an optional skip.
from trade_trace.mcp_server import mcp_call, mcp_tool_specs  # noqa: E402


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

    # bead trade-trace-8e3b: context-manager support so a test that
    # raises between McpProcess() construction and the `try:` block
    # cannot leak the subprocess + its three pipe file descriptors.
    def __enter__(self) -> McpProcess:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

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
            try:
                self.proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        # bead trade-trace-8e3b: explicitly close stdout/stderr so the
        # GC schedule cannot leave file descriptors open between tests.
        # subprocess.wait() reaps the child but does not close the
        # parent-side pipe handles.
        for stream in (self.proc.stdout, self.proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def _initialized_server(tmp_path: Path, actor_id: str = "agent:stdio-test") -> McpProcess:
    server = McpProcess(tmp_path, actor_id=actor_id)
    # bead trade-trace-8e3b: a handshake assertion failure must not
    # leak the just-spawned subprocess. Catch all here so the caller
    # never inherits an orphaned McpProcess on setup failure.
    try:
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
    except BaseException:
        server.close()
        raise
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


def test_stdio_tools_call_journal_schema_matches_in_process_mcp_call(tmp_path: Path):
    expected = mcp_call(
        "journal.schema",
        {},
        actor_id="agent:stdio-test",
    ).model_dump(mode="json", exclude_none=True)

    server = _initialized_server(tmp_path, actor_id="agent:stdio-test")
    try:
        result = server.request(
            "tools/call",
            {"name": "journal.schema", "arguments": {}},
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


# -- decision.add schema parity per trade-trace-hsnz ---------------------


def test_stdio_decision_add_watch_succeeds_without_quantity(tmp_path: Path):
    """Per trade-trace-hsnz: the decision.add MCP schema must not reject
    watch decisions for missing quantity/price. The runtime decision matrix
    forbids quantity for watch — the schema must not require it either."""

    home = tmp_path / "home"
    init = mcp_call("journal.init", {"home": str(home)}, actor_id="agent:stdio-test")
    assert init.ok

    venue = mcp_call("venue.add", {
        "home": str(home),
        "name": "PM",
        "kind": "prediction_market",
        "idempotency_key": "hsnz-venue",
    }, actor_id="agent:stdio-test")
    assert venue.ok
    inst = mcp_call("instrument.add", {
        "home": str(home),
        "venue_id": venue.data["id"],
        "asset_class": "prediction_market",
        "title": "Watchlist Candidate",
        "idempotency_key": "hsnz-inst",
    }, actor_id="agent:stdio-test")
    assert inst.ok

    server = _initialized_server(tmp_path, actor_id="agent:stdio-test")
    try:
        result = server.request(
            "tools/call",
            {
                "name": "decision.add",
                "arguments": {
                    "home": str(home),
                    "type": "watch",
                    "instrument_id": inst.data["id"],
                    "reason": "wait for liquidity",
                    "idempotency_key": "hsnz-watch-decision",
                },
            },
        )
        structured = result["structuredContent"]
        assert structured["ok"] is True, structured
        assert structured["data"]["type"] == "watch"
    finally:
        server.close()


def test_stdio_decision_add_skip_succeeds_without_quantity(tmp_path: Path):
    """A skip decision must succeed via stdio with just `type`, `instrument_id`,
    `reason`, and `idempotency_key` — no quantity/price."""

    home = tmp_path / "home"
    mcp_call("journal.init", {"home": str(home)}, actor_id="agent:stdio-test")
    venue = mcp_call("venue.add", {
        "home": str(home), "name": "PM", "kind": "prediction_market",
        "idempotency_key": "hsnz2-venue",
    }, actor_id="agent:stdio-test")
    inst = mcp_call("instrument.add", {
        "home": str(home), "venue_id": venue.data["id"],
        "asset_class": "prediction_market", "title": "Skip Target",
        "idempotency_key": "hsnz2-inst",
    }, actor_id="agent:stdio-test")

    server = _initialized_server(tmp_path, actor_id="agent:stdio-test")
    try:
        result = server.request(
            "tools/call",
            {
                "name": "decision.add",
                "arguments": {
                    "home": str(home),
                    "type": "skip",
                    "instrument_id": inst.data["id"],
                    "reason": "spread too wide",
                    "idempotency_key": "hsnz2-skip-decision",
                },
            },
        )
        structured = result["structuredContent"]
        assert structured["ok"] is True, structured
        assert structured["data"]["type"] == "skip"
    finally:
        server.close()


def test_decision_add_json_schema_does_not_require_quantity_or_price():
    """The published JSON schema for decision.add must not force quantity/price
    as required (those are matrix-X for watch/skip). Required set must be the
    subset that the runtime decision matrix marks R for every decision type."""

    from trade_trace.core import default_registry

    reg = default_registry().get("decision.add")
    schema = reg.json_schema or {}
    required = set(schema.get("required", []))
    assert "quantity" not in required
    assert "price" not in required
    # At minimum, type and instrument_id must be required (every matrix row
    # marks instrument_id R; type discriminates the matrix row).
    assert "type" in required
    assert "instrument_id" in required
