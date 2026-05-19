"""NDJSON streaming + CLI exit code mapping per docs/architecture/contracts.md §1.2
(trade-trace-5tf)."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from trade_trace.cli import main as cli_main
from trade_trace.mcp_server import mcp_call


def _init_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    mcp_call("journal.init", {"home": str(home)})
    return home


def _cli_lines(args: list[str]) -> tuple[int, list[str]]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(args)
    return rc, buf.getvalue().strip().splitlines()


# -- NDJSON shape for list tools ----------------------------------------


def test_resolve_pending_empty_ndjson_summary_only(tmp_path: Path):
    """An empty list result still emits a summary envelope as the only line."""

    home = _init_home(tmp_path)
    rc, lines = _cli_lines([
        "--actor-id", "agent:default",
        "resolve", "pending",
        "--home", str(home),
    ])
    assert rc == 0
    # Every line must parse as JSON.
    parsed = [json.loads(line) for line in lines]
    # Single summary line.
    assert len(parsed) == 1
    summary = parsed[-1]
    assert summary["ok"] is True
    assert summary["data"]["items"] == []
    assert summary["data"]["count"] == 0
    assert summary["data"]["truncated"] is False


def test_resolve_pending_streaming_multi_line(tmp_path: Path):
    """Multiple pending forecasts emit one envelope per item plus a summary."""

    home = _init_home(tmp_path)
    venue = mcp_call("venue.add", {"home": str(home), "name": "PM",
                                    "kind": "prediction_market"},
                     actor_id="agent:default").model_dump(mode="json")
    inst = mcp_call("instrument.add", {"home": str(home),
                                        "venue_id": venue["data"]["id"],
                                        "asset_class": "prediction_market",
                                        "title": "Test"},
                    actor_id="agent:default").model_dump(mode="json")
    thesis = mcp_call("thesis.add", {"home": str(home),
                                      "instrument_id": inst["data"]["id"],
                                      "side": "yes", "body": "..."},
                       actor_id="agent:default").model_dump(mode="json")
    # Create 3 forecasts.
    for i in range(3):
        mcp_call("forecast.add", {
            "home": str(home),
            "thesis_id": thesis["data"]["id"],
            "kind": "binary",
            "resolution_at": f"2026-06-{30 - i:02d}T00:00:00Z",
            "outcomes": [
                {"outcome_label": "YES", "probability": 0.5},
                {"outcome_label": "NO", "probability": 0.5},
            ],
        }, actor_id="agent:default")

    rc, lines = _cli_lines([
        "--actor-id", "agent:default",
        "resolve", "pending",
        "--home", str(home),
    ])
    assert rc == 0
    parsed = [json.loads(line) for line in lines]
    # 3 record lines + 1 summary line
    assert len(parsed) == 4
    # Records first (each carries the single forecast in data, not items).
    for record in parsed[:-1]:
        assert record["ok"] is True
        assert "forecast_id" in record["data"]
        assert record["meta"]["tool"] == "resolve.pending"
    summary = parsed[-1]
    assert summary["data"]["count"] == 3
    assert summary["data"]["items"] == []
    assert summary["data"]["truncated"] is False


def test_non_list_tool_does_not_stream(tmp_path: Path):
    """Non-list tools emit a single envelope, not NDJSON."""

    home = _init_home(tmp_path)
    rc, lines = _cli_lines([
        "--actor-id", "agent:default",
        "journal", "status",
        "--home", str(home),
    ])
    assert rc == 0
    assert len(lines) == 1
    body = json.loads(lines[0])
    assert "items" not in body["data"]


# -- Exit code mapping --------------------------------------------------


def test_exit_code_zero_on_success(tmp_path: Path):
    home = _init_home(tmp_path)
    rc, _ = _cli_lines(["journal", "status", "--home", str(home)])
    assert rc == 0


def test_exit_code_two_on_validation_error(tmp_path: Path):
    home = _init_home(tmp_path)
    rc, _ = _cli_lines([
        "venue", "add",
        # Missing --name → VALIDATION_ERROR
        "--kind", "manual",
        "--home", str(home),
    ])
    assert rc == 2


def test_exit_code_three_on_invariant_violation(tmp_path: Path):
    home = _init_home(tmp_path)
    venue = mcp_call("venue.add", {"home": str(home), "name": "PM",
                                    "kind": "prediction_market"},
                     actor_id="agent:default").model_dump(mode="json")
    inst = mcp_call("instrument.add", {"home": str(home),
                                        "venue_id": venue["data"]["id"],
                                        "asset_class": "prediction_market",
                                        "title": "Test"},
                    actor_id="agent:default").model_dump(mode="json")
    thesis = mcp_call("thesis.add", {"home": str(home),
                                      "instrument_id": inst["data"]["id"],
                                      "side": "yes", "body": "..."},
                       actor_id="agent:default").model_dump(mode="json")
    rc, _ = _cli_lines([
        "forecast", "add",
        "--home", str(home),
        "--thesis-id", thesis["data"]["id"],
        "--kind", "binary",
        "--outcomes-json", json.dumps([
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.4},  # sum 0.9 — invariant
        ]),
    ])
    assert rc == 3


def test_exit_code_one_on_other_error(tmp_path: Path):
    """A NOT_FOUND or STORAGE_ERROR maps to exit code 1 (everything that
    is not VALIDATION_ERROR / INVARIANT_VIOLATION).

    The original test asserted `review bundle` was UNSUPPORTED_CAPABILITY,
    but review.bundle is now a shipped report (trade-trace-da6t). Use
    `forecast.supersede` with a nonexistent prior_forecast_id instead —
    a fresh journal returns NOT_FOUND with the canonical exit-1 mapping.
    """

    home = _init_home(tmp_path)
    rc, _ = _cli_lines([
        "forecast", "supersede",
        "--home", str(home),
        "--prior-forecast-id", "fc_does_not_exist",
        "--kind", "binary",
        "--outcomes-json", json.dumps([
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.5},
        ]),
        "--idempotency-key", "da6t-exit-one",
    ])
    assert rc == 1


# -- Summary line invariants --------------------------------------------


def test_summary_line_carries_count_and_truncated_keys(tmp_path: Path):
    home = _init_home(tmp_path)
    rc, lines = _cli_lines([
        "resolve", "pending",
        "--home", str(home),
    ])
    assert rc == 0
    summary = json.loads(lines[-1])
    assert "count" in summary["data"]
    assert "truncated" in summary["data"]
    assert summary["data"]["items"] == []
