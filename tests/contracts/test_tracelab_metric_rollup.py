"""Contract tests for TraceLab metric-rollup sidecar."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.tracelab.metric_rollup import ACTOR_ID, build_metric_rollup
from tools.tracelab.run_config import (
    RUN_CONFIG_PATH,
    include_late_recorded_default,
    load_run_config,
)
from trade_trace.mcp_server import mcp_call


def _env(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "data": data, "meta": {"tool": "fake", "actor_id": ACTOR_ID, "request_id": "r"}}


def test_metric_rollup_uses_embedded_calibration_integrity_and_run_config_policy() -> None:
    calls: list[tuple[str, dict[str, Any], str]] = []

    def fake_call(tool: str, args: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        calls.append((tool, args, actor_id))
        payloads = {
            "report.calibration": {
                "summary": {
                    "metrics": {"brier": 0.12, "late_recorded_excluded": 3},
                    "late_recorded_excluded": 3,
                    "integrity_probe": "must-not-be-used",
                },
                "integrity_diagnostics": {"summary": {"metrics": {"denominator_coverage_pct": 99.0}}},
            },
            "report.pnl": {"summary": {"metrics": {"closed_position_count": 0, "open_position_count": 2}}},
            "report.coach": {"summary": {}, "integrity_diagnostics": {"from_coach": True}},
            "report.recall_receipts": {"summary": {"sample_size": 1}, "recall_receipts": []},
        }
        return _env(payloads[tool])

    rollup = build_metric_rollup("/tmp/tracelab-home", call=fake_call)

    tool_names = [tool for tool, _args, _actor in calls]
    assert tool_names == [
        "report.calibration",
        "report.pnl",
        "report.coach",
        "report.recall_receipts",
    ]
    assert all(actor == ACTOR_ID for _tool, _args, actor in calls)
    assert "memory.recall" not in tool_names
    assert calls[0][1]["filter"]["outcome"]["include_late_recorded"] is False
    assert rollup["late_recorded_policy"] == {
        "include_late_recorded": False,
        "source": "docs/tracelab/run-config.json",
        "excluded_late_scored_forecasts": 3,
    }
    assert rollup["reports"]["calibration"]["summary"]["integrity_probe"] == "must-not-be-used"
    assert rollup["reports"]["calibration_integrity"]["summary"]["metrics"] == {"denominator_coverage_pct": 99.0}
    assert rollup["reports"]["coach"]["integrity_diagnostics"] == {"from_coach": True}
    assert rollup["pnl_annotation"]["zero_close_interpretation"] == "expected-given-resolution-only-close"
    assert rollup["recall_evidence_source"] == "report.recall_receipts"


def test_metric_rollup_override_includes_late_recorded_and_reports_zero_excluded() -> None:
    seen_filter: dict[str, Any] | None = None

    def fake_call(tool: str, args: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        nonlocal seen_filter
        if tool == "report.calibration":
            seen_filter = args["filter"]
            return _env({"summary": {"metrics": {"late_recorded_excluded": 7}, "late_recorded_excluded": 7}})
        if tool == "report.pnl":
            return _env({"summary": {"metrics": {"closed_position_count": 1, "open_position_count": 0}}})
        return _env({"summary": {}})

    rollup = build_metric_rollup("/tmp/tracelab-home", include_late_recorded=True, call=fake_call)

    assert seen_filter == {"outcome": {"include_late_recorded": True}}
    assert rollup["late_recorded_policy"] == {
        "include_late_recorded": True,
        "source": "argument",
        "excluded_late_scored_forecasts": 0,
    }
    assert rollup["pnl_annotation"]["zero_close_interpretation"] == "closed-positions-present"


def test_run_config_machine_readable_late_recorded_policy() -> None:
    config = load_run_config(RUN_CONFIG_PATH)
    policy = config["scorecard"]["late_recorded_policy"]
    assert policy["operator_override_key"] == "include_late_recorded"
    assert include_late_recorded_default(config) is False


def test_metric_rollup_dispatch_trace_uses_recall_receipts_not_memory_recall(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    trace_path = tmp_path / "dispatch.jsonl"
    assert mcp_call("journal.init", {"home": str(home)}, actor_id="agent:init").ok
    monkeypatch.setenv("TRADE_TRACE_DISPATCH_TRACE", "1")
    monkeypatch.setenv("TRADE_TRACE_DISPATCH_TRACE_PATH", str(trace_path))

    rollup = build_metric_rollup(home)

    assert rollup["reports"]["recall_receipts"]["summary"]["sample_size"] == 0
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    tools = [record["tool"] for record in records]
    assert "report.recall_receipts" in tools
    assert "memory.recall" not in tools
    assert "report.calibration" in tools
    assert "report.calibration_integrity" not in tools
    assert "report.coach" in tools
    assert all(record["actor_id"] == ACTOR_ID for record in records)
