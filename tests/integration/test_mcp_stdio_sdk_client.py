from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tests.security.test_mvp_boundary_audit import SHIPPED_PUBLIC_TOOLS, SHIPPED_REPORTS

ACTOR_ID = "agent:stdio-sdk-test"


def _structured(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    assert isinstance(structured, dict), result
    return structured


def _assert_trade_trace_envelope(
    envelope: dict[str, Any],
    *,
    tool: str,
    ok: bool = True,
) -> dict[str, Any]:
    assert envelope["ok"] is ok, envelope
    assert "meta" in envelope
    assert isinstance(envelope["meta"], dict), envelope
    assert isinstance(envelope["meta"].get("request_id"), str), envelope
    assert envelope["meta"]["request_id"], envelope
    if ok:
        assert "data" in envelope
        assert "error" not in envelope
    else:
        assert "error" in envelope
        assert "data" not in envelope
    assert envelope["meta"]["tool"] == tool
    assert envelope["meta"]["actor_id"] == ACTOR_ID
    assert envelope["meta"]["contract_version"] == "1.0"
    return envelope["data"] if ok else envelope["error"]


async def _sdk_smoke(tmp_path: Path) -> None:
    home = tmp_path / "trade-trace-home"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    env["TRADE_TRACE_HOME"] = str(home)
    env["MCP_ACTOR_ID"] = ACTOR_ID

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "trade_trace.mcp_server"],
        cwd=Path.cwd(),
        env=env,
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            init = await session.initialize()
            assert init.serverInfo.name == "trade-trace"
            assert init.capabilities.tools is not None

            listed = await session.list_tools()
            tool_names = {tool.name for tool in listed.tools}
            assert tool_names == SHIPPED_PUBLIC_TOOLS | SHIPPED_REPORTS
            assert "venue.add" not in tool_names
            assert "instrument.add" not in tool_names
            assert "thesis.add" not in tool_names

            schema_tool = next(tool for tool in listed.tools if tool.name == "forecast.add")
            schema = schema_tool.inputSchema
            for field in (
                "thesis_id",
                "market_id",
                "instrument_id",
                "rationale_body",
                "snapshot_id",
                "_anchor_to_latest_snapshot",
                "idempotency_key",
            ):
                assert field in schema["properties"]
            assert "anyOf" in schema

            init_env = _structured(await session.call_tool("journal.init", {"home": str(home)}))
            _assert_trade_trace_envelope(init_env, tool="journal.init")

            market_env = _structured(await session.call_tool(
                "market.bind",
                {
                    "home": str(home),
                    "source": "manual",
                    "external_id": "sdk-smoke-market",
                    "title": "SDK smoke market resolves YES",
                    "question": "Will the SDK smoke market resolve YES?",
                    "state": "open",
                    "mechanism": "clob",
                    "bound_via": "manual",
                    "idempotency_key": "sdk-smoke-market",
                },
            ))
            market = _assert_trade_trace_envelope(market_env, tool="market.bind")
            assert market["id"]

            error_env = _structured(await session.call_tool(
                "market.bind",
                {
                    "home": str(home),
                    "source": "manual",
                    "external_id": "sdk-smoke-market-error",
                    "state": "not-open",
                    "mechanism": "clob",
                    "idempotency_key": "sdk-smoke-market-error",
                },
            ))
            error = _assert_trade_trace_envelope(error_env, tool="market.bind", ok=False)
            assert error["code"] == "VALIDATION_ERROR"

            snapshot_env = _structured(await session.call_tool(
                "snapshot.add",
                {
                    "home": str(home),
                    "instrument_id": market["instrument_id"],
                    "captured_at": "2026-05-22T14:30:00.000Z",
                    "price": 0.62,
                    "source": "manual",
                    "implied_probability": 0.62,
                    "idempotency_key": "sdk-smoke-snapshot",
                },
            ))
            snapshot = _assert_trade_trace_envelope(snapshot_env, tool="snapshot.add")
            assert snapshot["instrument_id"] == market["instrument_id"]

            forecast_env = _structured(await session.call_tool(
                "forecast.add",
                {
                    "home": str(home),
                    "market_id": market["market_id"],
                    "instrument_id": market["instrument_id"],
                    "rationale_body": "SDK smoke setup thesis.",
                    "kind": "binary",
                    "yes_label": "YES",
                    "snapshot_id": snapshot["id"],
                    "outcomes": [
                        {"outcome_label": "YES", "probability": 0.61},
                        {"outcome_label": "NO", "probability": 0.39},
                    ],
                    "idempotency_key": "sdk-smoke-forecast",
                },
            ))
            forecast = _assert_trade_trace_envelope(forecast_env, tool="forecast.add")
            assert forecast["thesis_id"]
            assert forecast["snapshot_anchor"]["snapshot_id"] == snapshot["id"]

            error_env = _structured(await session.call_tool(
                "forecast.add",
                {
                    "home": str(home),
                    "market_id": market["market_id"],
                    "instrument_id": market["instrument_id"],
                    "rationale_body": "SDK smoke setup thesis for invalid sum.",
                    "kind": "binary",
                    "yes_label": "YES",
                    "outcomes": [
                        {"outcome_label": "YES", "probability": 0.61},
                        {"outcome_label": "NO", "probability": 0.10},
                    ],
                    "idempotency_key": "sdk-smoke-forecast-error",
                },
            ))
            error = _assert_trade_trace_envelope(error_env, tool="forecast.add", ok=False)
            assert error["code"] == "INVARIANT_VIOLATION"

            decision_env = _structured(await session.call_tool(
                "decision.add",
                {
                    "home": str(home),
                    "type": "skip",
                    "instrument_id": market["instrument_id"],
                    "forecast_id": forecast["id"],
                    "reason": "SDK smoke non-action record.",
                    "idempotency_key": "sdk-smoke-decision",
                },
            ))
            decision = _assert_trade_trace_envelope(decision_env, tool="decision.add")
            assert decision["instrument_id"] == market["instrument_id"]
            assert decision["id"]

            recall_env = _structured(await session.call_tool(
                "memory.recall",
                {
                    "query": "SDK smoke non-action record",
                    "context": {"instrument_id": market["instrument_id"]},
                    "k": 5,
                },
            ))
            recall = _assert_trade_trace_envelope(recall_env, tool="memory.recall")
            assert isinstance(recall, dict)


def test_official_mcp_sdk_stdio_client_initialize_list_call_smoke(tmp_path: Path):
    anyio.run(_sdk_smoke, tmp_path)
