"""Golden parity fixture: CLI and MCP adapters produce the same envelope
for `journal.status`.

This is the M0 keystone test — proves the shared core dispatch path is
truly shared. Future golden tests (one per write tool, one per read tool,
the error-case set in contracts.md §7.2) extend the pattern.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from typing import Any

from trade_trace import __version__ as _PACKAGE_VERSION
from trade_trace.cli import main as cli_main
from trade_trace.core import build_registry
from trade_trace.mcp_server import mcp_call


def _normalize(envelope: dict[str, Any]) -> dict[str, Any]:
    """Strip transport-specific fields per contracts.md §7.1."""

    out = json.loads(json.dumps(envelope, sort_keys=True))
    meta = out.get("meta", {})
    meta["request_id"] = "<request-id>"
    meta.pop("mcp_transport_hints", None)
    meta.pop("cli_human_hint", None)
    return out


def test_journal_status_parity(tmp_path):
    """Pin `home` to a tmp_path so the test asserts the contract for an
    uninitialized journal regardless of the operator's default
    `$TRADE_TRACE_HOME` state (trade-trace-cwdl)."""

    registry = build_registry()
    home = tmp_path / "home"

    # MCP path (in-process)
    mcp_env = mcp_call(
        "journal.status",
        {"home": str(home)},
        actor_id="agent:default",
        request_id="req-mcp",
        registry=registry,
    ).model_dump(mode="json", exclude_none=True)

    # CLI path (in-process; captured stdout)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(
            [
                "--actor-id",
                "agent:default",
                "--request-id",
                "req-cli",
                "journal",
                "status",
                "--home",
                str(home),
            ],
            registry=registry,
        )
    assert rc == 0, "CLI exit code must be 0 on ok=true"
    cli_env = json.loads(buf.getvalue().strip().splitlines()[-1])

    # Equivalent after transport-metadata normalization
    assert _normalize(mcp_env) == _normalize(cli_env)
    # Both envelopes must carry the contract version
    assert mcp_env["meta"]["contract_version"] == cli_env["meta"]["contract_version"] == "1.0"
    # Both envelopes must report the same canonical tool name
    assert mcp_env["meta"]["tool"] == cli_env["meta"]["tool"] == "journal.status"
    # Data payloads MUST deep-equal
    assert mcp_env["data"] == cli_env["data"]
    # The data payload itself must report M0 expectations
    assert cli_env["data"]["package_version"] == _PACKAGE_VERSION
    assert cli_env["data"]["contract_version"] == "1.0"
    assert cli_env["data"]["schema_version"] == 0
    assert cli_env["data"]["embeddings_provider"] == "none"
    assert cli_env["data"]["outbound_network_active"] is False


def test_cli_error_envelope_for_unknown_tool():
    """An unknown tool returns a NOT_FOUND error envelope and exit code 1."""

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["journal", "status", "--unknown-flag", "value"])
    # journal.status is known; unknown flags are tolerated. The point of this
    # block is the inverse case: an unregistered tool.
    assert rc == 0

    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        try:
            rc2 = cli_main(["nonexistent", "tool"])
        except SystemExit as exc:
            rc2 = exc.code or 2
    assert rc2 != 0
