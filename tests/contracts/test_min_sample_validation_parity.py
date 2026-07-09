"""CLI ↔ MCP-stdio parity for negative `min_sample` on the
report.calibration family per bead trade-trace-cms2.

Before this contract was pinned:
- The CLI dispatched straight into `dispatch` and skipped the
  schema-derived `minimum: 1` constraint that the MCP stdio boundary
  enforced, so `tt report calibration --min-sample -1` returned
  `EXIT 0, ok:true` while the same MCP call was rejected.
The CLI now validates against the property-constraint half of each
tool's schema (required-field enforcement stays on the dispatcher /
handler so the friendlier cpz2 idempotency-key message wins).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from mcp import types

from trade_trace.cli import main as cli_main
from trade_trace.mcp_server import _build_stdio_server


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    rc = cli_main(["journal", "init", "--home", str(h)])
    assert rc == 0
    return h


def _stdio_invoke(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Drive the MCP stdio server's CallToolRequest handler in-process so
    schema validation runs exactly like a real MCP client would see it."""

    server = _build_stdio_server()
    request = types.CallToolRequest.model_construct(
        params=types.CallToolRequestParams.model_construct(
            name=name, arguments=arguments,
        )
    )
    result = asyncio.run(server.request_handlers[types.CallToolRequest](request))
    return result.root.structuredContent


@pytest.mark.parametrize(
    "tool",
    [
        "report.calibration",
        "report.forecast_diagnostics",
    ],
)
def test_mcp_stdio_rejects_negative_min_sample(home, tool):
    body = _stdio_invoke(tool, {"home": str(home), "min_sample": -1})
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["field"] == "min_sample"
    assert body["error"]["details"]["validator"] == "minimum"


@pytest.mark.parametrize(
    "cli_command",
    [
        ["report", "calibration"],
        ["report", "forecast_diagnostics"],
    ],
)
def test_cli_rejects_negative_min_sample(home, cli_command, capsys):
    rc = cli_main([
        "--actor-id", "agent:default",
        *cli_command,
        "--home", str(home),
        "--min-sample", "-1",
    ])
    assert rc == 2  # VALIDATION_ERROR maps to exit 2
    out = capsys.readouterr().out.strip().splitlines()[-1]
    body = json.loads(out)
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["field"] == "min_sample"
    assert body["error"]["details"]["validator"] == "minimum"


def test_cli_still_accepts_clean_min_sample(home, capsys):
    """Sanity check: a valid min_sample passes the new CLI validator
    and reaches the handler."""

    rc = cli_main([
        "--actor-id", "agent:default",
        "report", "calibration",
        "--home", str(home),
        "--min-sample", "5",
    ])
    out = capsys.readouterr().out.strip().splitlines()[-1]
    body = json.loads(out)
    assert rc == 0
    assert body["ok"] is True
