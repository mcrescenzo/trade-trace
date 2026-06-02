from __future__ import annotations

import sqlite3
from pathlib import Path

from tools.tracelab.scorecard import (
    ScorecardInputs,
    build_scorecard,
    count_resolved_auto_scored_forecasts,
)


def _inputs(final_n: int = 21) -> ScorecardInputs:
    return ScorecardInputs(
        substrate={
            "overall_status": "PASS",
            "throughput_scored": False,
            "invariants": [
                {"name": "storage_errors_recovery_in_1_retry", "status": "PASS", "reason": "ok", "evidence": {"paired": 1}},
                {"name": "rebuild_positions_reproduces_rows", "status": "FAIL", "reason": "synthetic failure", "evidence": {}},
            ],
        },
        metric_rollup={"reports": {"calibration": {"summary": {"metrics": {"sample_size": final_n}}}}},
        skill_metrics={
            "skill_metrics": {
                "agent:a": {
                    "calibration": {"sample_size": 2, "mean_brier_score": 0.12},
                    "process_quality": {"sample_size": 1, "direction_consistency_rate": 1.0},
                }
            },
            "read_rail_adoption": {
                "caveat": "Observational per-actor call counts from the live B1 dispatch trace only; not a causal precedence/looked-before-leaped claim and not replay-reproducible.",
                "totals": {"bootstrap": 1, "work_queue": 2},
                "per_actor": {"agent:a": {"bootstrap": 1, "work_queue": 2, "total": 3}},
            },
            "write_rail_adoption": {
                "totals": {"lock_count": 1, "independence_proven_count": 1},
                "per_actor": {"agent:a": {"lock_count": 1, "independence_proven_count": 1}},
            },
        },
        reconcile={"trace_count": 4, "buckets": {"request_id_events": 3, "expected_validation_error_pattern": 1}},
        health={
            "counts": {"resolved_but_unfed": 2, "resolved_but_no_forecast": 1},
            "canary": {"enabled": True, "ok": False, "error": "Gamma canary schema drift: missing bid"},
            "alarms": [{"code": "GAMMA_SCHEMA_CANARY", "message": "missing bid"}],
        },
        run_config={
            "scorecard": {"late_recorded_policy": {"statement": "Scorecards exclude late-recorded records by default."}},
            "replay_caveat": {"statement": "Read-rail adoption findings must be captured from live B1 dispatch trace."},
        },
    )


def test_scorecard_renders_three_result_classes_findings_and_b22_citation():
    markdown = build_scorecard(_inputs())

    assert "## Substrate invariants" in markdown
    assert "storage_errors_recovery_in_1_retry" in markdown
    assert "**FAIL**" in markdown
    assert "## Agent skill metrics" in markdown
    assert "mean_brier_score" in markdown
    assert "## Rail adoption" in markdown
    assert "bootstrap" in markdown
    assert "## FINDINGS" in markdown
    assert "paper_exit / resolution-does-not-close-position" in markdown
    assert "tests/integration/test_manual_ledger_flow.py::test_resolved_final_does_not_close_open_paper_position" in markdown
    assert "expected finding, not a bug" in markdown


def test_scorecard_states_final_n_threshold_pass_and_extend_abort():
    passing = build_scorecard(_inputs(final_n=20))
    failing = build_scorecard(_inputs(final_n=19))

    assert "Final N (resolved auto-scored forecasts): **20**" in passing
    assert "outcome: **PASS**" in passing
    assert "final N=20; N>=20 met" in passing
    assert "Final N (resolved auto-scored forecasts): **19**" in failing
    assert "outcome: **EXTEND_OR_ABORT**" in failing
    assert "extend/abort rule fired" in failing


def test_scorecard_preserves_read_rail_trace_only_caveat_and_expected_validation_errors():
    markdown = build_scorecard(_inputs())

    assert "Observational per-actor call counts from the live B1 dispatch trace only" in markdown
    assert "not a causal precedence" in markdown
    assert "not replay-reproducible" in markdown
    assert "Secret-scanner VALIDATION_ERROR handling" in markdown
    assert "expected_validation_error_pattern` count=1" in markdown


def test_scorecard_renders_lag_and_gamma_findings():
    markdown = build_scorecard(_inputs())

    assert "Resolved-but-unfed lag**: 2" in markdown
    assert "Resolved-but-no-forecast lag**: 1" in markdown
    assert "Gamma schema drift status" in markdown
    assert "schema drift/alarm observed" in markdown


def test_count_resolved_auto_scored_forecasts_uses_read_only_db(tmp_path: Path):
    db = tmp_path / "journal.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE forecasts (id TEXT PRIMARY KEY);
            CREATE TABLE outcomes (id TEXT PRIMARY KEY, status TEXT);
            CREATE TABLE forecast_scores (id TEXT PRIMARY KEY, forecast_id TEXT, outcome_id TEXT);
            INSERT INTO forecasts VALUES ('f1'), ('f2'), ('f3');
            INSERT INTO outcomes VALUES ('o1', 'resolved_final'), ('o2', 'open'), ('o3', 'resolved_provisional');
            INSERT INTO forecast_scores VALUES ('s1', 'f1', 'o1'), ('s2', 'f1', 'o1'), ('s3', 'f2', 'o2'), ('s4', 'f3', 'o3');
            """
        )

    assert count_resolved_auto_scored_forecasts(db) == 2
