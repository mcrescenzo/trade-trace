"""Contract tests for TraceLab capture hygiene run-config and replay caveat."""

from __future__ import annotations

from pathlib import Path

from tools.tracelab.run_config import (
    RUN_CONFIG_PATH,
    dispatch_trace_rotation_env,
    exporter_drain_enabled_during_run,
    load_run_config,
)

ROOT = Path(__file__).resolve().parents[2]
TRACELAB_DESIGN = ROOT / "docs" / "tracelab-design.md"
SKILL_METRICS = ROOT / "tools" / "tracelab" / "skill_metrics.py"
SCORECARD = ROOT / "docs" / "architecture" / "agent-continuity-scorecard.md"


def test_tracelab_run_config_bounds_capture_growth() -> None:
    config = load_run_config(RUN_CONFIG_PATH)
    hygiene = config["capture_hygiene"]

    assert exporter_drain_enabled_during_run(config) is False
    assert "Do not schedule or invoke export.drain" in hygiene["exporter_jsonl_drain"][
        "operator_instruction"
    ]
    assert hygiene["transcripts"]["retention_days"] == 14
    assert hygiene["transcripts"]["max_files_per_agent"] == 20
    assert dispatch_trace_rotation_env(config) == {
        "TRADE_TRACE_DISPATCH_TRACE": "1",
        "TRADE_TRACE_DISPATCH_TRACE_MAX_BYTES": "10485760",
        "TRADE_TRACE_DISPATCH_TRACE_MAX_FILES": "5",
    }


def test_tracelab_docs_and_b15_output_pin_replay_caveat() -> None:
    config = load_run_config(RUN_CONFIG_PATH)
    caveat = config["replay_caveat"]
    assert caveat["rail_adoption_source"] == "live_b1_dispatch_trace_only"
    assert caveat["not_replay_reproducible"] is True
    assert set(caveat["dropped_replay_signals"]) == {"signal.emitted", "memory_node.invalidated"}

    design = TRACELAB_DESIGN.read_text(encoding="utf-8")
    b15 = SKILL_METRICS.read_text(encoding="utf-8")
    scorecard = SCORECARD.read_text(encoding="utf-8")
    for text in (design, b15, scorecard):
        assert "live B1 dispatch trace" in text
        assert "signal.emitted" in text
        assert "memory_node.invalidated" in text
        assert "not replay-reproducible" in text
