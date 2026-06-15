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


# trade-trace-l6ot: parity coverage for the new strategy/report surfaces.
# The parity helpers above normalize generated IDs, request_id, and
# transport hints so the only thing being asserted is contract surface.


def test_parity_strategy_upsert(home):
    mcp = _mcp(home, "strategy.upsert", {
        "name": "Parity Strategy",
        "slug": "parity-strategy",
        "idempotency_key": "00000000-0000-4000-8000-strat-par-mcp1",
    })
    rc, cli = _cli(home, [
        "strategy", "upsert",
        "--name", "Parity Strategy CLI",
        "--slug", "parity-strategy-cli",
        "--idempotency-key", "00000000-0000-4000-8000-strat-par-cli1",
    ])
    assert rc == 0
    assert mcp["meta"]["tool"] == cli["meta"]["tool"] == "strategy.upsert"
    # Different slugs because strategy.upsert is uniqueness-constrained, but the
    # envelope shape must match: same data keys and meta tool.
    assert set(mcp["data"]) == set(cli["data"])


def test_parity_strategy_list_empty(home):
    mcp = _mcp(home, "strategy.list", {})
    rc, cli = _cli(home, ["strategy", "list"])
    assert rc == 0
    assert mcp["data"]["items"] == cli["data"]["items"]
    assert mcp["meta"]["tool"] == cli["meta"]["tool"] == "strategy.list"


def test_parity_strategy_show_not_found(home):
    mcp = _mcp(home, "strategy.show", {"strategy_id": "strat-missing"})
    rc, cli = _cli(home, [
        "strategy", "show",
        "--strategy-id", "strat-missing",
    ])
    # NOT_FOUND falls through the CLI exit-code mapping to the generic
    # non-zero fallback (1); the contract carries the typed code in the
    # envelope.
    assert rc == 1
    assert mcp["error"]["code"] == cli["error"]["code"] == "NOT_FOUND"


def test_parity_strategy_list_invalid_status(home):
    mcp = _mcp(home, "strategy.list", {"status": "banana"})
    rc, cli = _cli(home, ["strategy", "list", "--status", "banana"])
    assert rc == 2
    assert mcp["error"]["code"] == cli["error"]["code"] == "VALIDATION_ERROR"
    assert mcp["error"]["details"]["field"] == cli["error"]["details"]["field"] == "status"


def test_parity_report_forecast_diagnostics_empty_db(home):
    mcp = _mcp(home, "report.forecast_diagnostics", {})
    rc, cli = _cli(home, ["report", "forecast_diagnostics"])
    assert rc == 0
    assert mcp["data"]["summary"]["sample_size"] == cli["data"]["summary"]["sample_size"] == 0
    assert mcp["meta"]["tool"] == cli["meta"]["tool"] == "report.forecast_diagnostics"


def test_parity_report_strategy_health_empty_db(home):
    mcp = _mcp(home, "report.strategy_health", {})
    rc, cli = _cli(home, ["report", "strategy_health"])
    assert rc == 0
    assert mcp["data"]["summary"]["sample_size"] == cli["data"]["summary"]["sample_size"] == 0


def test_parity_report_strategy_health_invalid_status(home):
    mcp = _mcp(home, "report.strategy_health", {"status": "banana"})
    rc, cli = _cli(home, ["report", "strategy_health", "--status", "banana"])
    assert rc == 2
    assert mcp["error"]["code"] == cli["error"]["code"] == "VALIDATION_ERROR"
    assert mcp["error"]["details"]["field"] == cli["error"]["details"]["field"] == "status"


def test_parity_report_bootstrap_empty_db(home):
    mcp = _mcp(home, "report.bootstrap", {"as_of": "2026-01-20T00:00:00Z"})
    rc, cli = _cli(home, [
        "report", "bootstrap",
        "--as-of", "2026-01-20T00:00:00Z",
    ])
    assert rc == 0, cli
    assert mcp["data"]["kind"] == cli["data"]["kind"] == "agent.bootstrap"
    assert mcp["meta"]["tool"] == cli["meta"]["tool"] == "report.bootstrap"


def test_parity_report_bootstrap_unsupported_filter_validation(home):
    bad = {
        "as_of": "2026-01-20T00:00:00Z",
        "filter": {"symbols": ["ABC"]},
    }
    mcp = _mcp(home, "report.bootstrap", bad)
    rc, cli = _cli(home, [
        "report", "bootstrap",
        "--as-of", bad["as_of"],
        "--filter-json", json.dumps(bad["filter"]),
    ])
    assert rc == 2
    assert mcp["error"]["code"] == cli["error"]["code"] == "VALIDATION_ERROR"
