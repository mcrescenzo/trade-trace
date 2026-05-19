"""CLI/MCP parity for the M1 ledger tools per docs/architecture/contracts.md §7.

For each tool, we exercise both transports against the same DB fixture and
assert the envelopes are deep-equal after normalization (request_id and
transport-metadata stripped).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from trade_trace.cli import main as cli_main
from trade_trace.mcp_server import mcp_call


def _normalize(envelope: dict) -> dict:
    out = json.loads(json.dumps(envelope, sort_keys=True))
    meta = out.get("meta", {})
    meta["request_id"] = "<rid>"
    meta.pop("mcp_transport_hints", None)
    meta.pop("cli_human_hint", None)
    if "data" in out and isinstance(out["data"], dict):
        # Normalize generated IDs to a placeholder so the deep-equal compare
        # only checks the contract surface.
        for key in list(out["data"]):
            if key == "id" and isinstance(out["data"][key], str):
                out["data"][key] = "<id>"
            if key == "created_at":
                out["data"][key] = "<ts>"
    return out


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    mcp_call("journal.init", {"home": str(h)})
    return h


def _cli(home: Path, tokens: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    args = [
        "--actor-id", "agent:default",
        "--request-id", "rid-cli",
        *tokens,
        "--home", str(home),
    ]
    with redirect_stdout(buf):
        rc = cli_main(args)
    line = buf.getvalue().strip().splitlines()[-1]
    body = json.loads(line)
    return rc, body


def _mcp(home: Path, tool: str, args: dict) -> dict:
    env = mcp_call(
        tool,
        {**args, "home": str(home)},
        actor_id="agent:default",
        request_id="rid-mcp",
    )
    return env.model_dump(mode="json", exclude_none=True)


def test_parity_venue_add(home):
    mcp = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    rc, cli = _cli(home, ["venue", "add", "--name", "PM", "--kind", "prediction_market"])
    assert rc == 0
    assert _normalize(mcp)["data"] == _normalize(cli)["data"]
    assert mcp["meta"]["tool"] == cli["meta"]["tool"] == "venue.add"


def test_parity_journal_schema(home):
    mcp = _mcp(home, "journal.schema", {"tool": "Decision"})
    rc, cli = _cli(home, ["journal", "schema", "--tool", "Decision"])
    assert rc == 0
    assert mcp["data"]["schemas"]["Decision"] == cli["data"]["schemas"]["Decision"]


def test_parity_validation_error_decision_skip_missing_reason(home):
    """A VALIDATION_ERROR must surface identically on both transports."""

    # Set up minimum state.
    venue = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    instrument_id = inst["data"]["id"]

    mcp = _mcp(home, "decision.add", {"instrument_id": instrument_id, "type": "skip"})
    rc, cli = _cli(home, [
        "decision", "add",
        "--instrument-id", instrument_id,
        "--type", "skip",
    ])
    # Exit code 2 for VALIDATION_ERROR per trade-trace-5tf CLI mapping.
    assert rc == 2
    assert mcp["ok"] is False
    assert cli["ok"] is False
    assert mcp["error"]["code"] == cli["error"]["code"] == "VALIDATION_ERROR"
    assert mcp["error"]["details"]["field"] == cli["error"]["details"]["field"] == "reason"


def test_parity_invariant_violation_binary_forecast(home):
    venue = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "...",
    })
    bad_args = {
        "thesis_id": thesis["data"]["id"],
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.4},  # sum 0.9
        ],
    }
    mcp = _mcp(home, "forecast.add", bad_args)
    rc, cli = _cli(home, [
        "forecast", "add",
        "--thesis-id", thesis["data"]["id"],
        "--kind", "binary",
        "--outcomes-json", json.dumps(bad_args["outcomes"]),
    ])
    # Exit code 3 for INVARIANT_VIOLATION per trade-trace-5tf CLI mapping.
    assert rc == 3
    assert mcp["error"]["code"] == cli["error"]["code"] == "INVARIANT_VIOLATION"
