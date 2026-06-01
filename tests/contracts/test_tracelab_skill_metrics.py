from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tools.tracelab.skill_metrics import (
    build_skill_metrics,
    count_read_rail_calls,
    derive_write_rail_adoption,
)


def _write_trace(path: Path) -> None:
    records = [
        {"tool": "report.bootstrap", "actor_id": "agent:a", "ok": True},
        {"tool": "report.work_queue", "actor_id": "agent:a", "ok": True},
        {"tool": "report.work_queue", "actor_id": "agent:a", "ok": False},
        {"tool": "report.coach", "actor_id": "agent:b", "ok": True},
        {"tool": "report.mistake_tripwire", "actor_id": "agent:b", "ok": True},
        {"tool": "report.calibration_advisory", "actor_id": "agent:b", "ok": True},
        {"tool": "forecast.commit", "actor_id": "agent:a", "ok": True},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE events (id TEXT PRIMARY KEY);
            CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE forecasts (id TEXT PRIMARY KEY, probability REAL, actor_id TEXT NOT NULL);
            CREATE TABLE forecast_scores (id TEXT PRIMARY KEY, forecast_id TEXT, score REAL, actor_id TEXT NOT NULL);
            CREATE TABLE decisions (
                id TEXT PRIMARY KEY, forecast_id TEXT, side TEXT, quantity REAL, price REAL,
                type TEXT, actor_id TEXT NOT NULL
            );
            CREATE TABLE resolution_interpretations (id TEXT PRIMARY KEY, forecast_id TEXT, actor_id TEXT NOT NULL);
            CREATE TABLE positions (
                id TEXT PRIMARY KEY, status TEXT, realized_pnl REAL, unrealized_pnl REAL, actor_id TEXT NOT NULL
            );
            CREATE TABLE forecast_independence_locks (
                id TEXT PRIMARY KEY, forecast_id TEXT, snapshot_id TEXT,
                blind_commit_seq INTEGER NOT NULL, reveal_seq INTEGER NOT NULL,
                independence_proven INTEGER NOT NULL, actor_id TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO forecasts VALUES (?, ?, ?)",
            [("f-a1", 0.7, "agent:a"), ("f-b1", 0.3, "agent:b")],
        )
        conn.executemany(
            "INSERT INTO forecast_scores VALUES (?, ?, ?, ?)",
            [("s-a1", "f-a1", 0.09, "agent:a"), ("s-b1", "f-b1", 0.16, "agent:b")],
        )
        conn.executemany(
            "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
            [("d-a1", "f-a1", "yes", 10, 0.55, "paper_enter", "agent:a")],
        )
        conn.execute("INSERT INTO resolution_interpretations VALUES ('ri-a1', 'f-a1', 'agent:a')")
        conn.execute("INSERT INTO positions VALUES ('p-a1', 'closed', 1.25, NULL, 'agent:a')")
        conn.executemany(
            "INSERT INTO forecast_independence_locks VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("l-a1", "f-a1", "snap-a", 10, 11, 1, "agent:a"),
                ("l-b1", "f-b1", "snap-b", 20, 20, 0, "agent:b"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_trace_fixture_counts_read_rail_calls_per_actor_and_tool(tmp_path: Path):
    trace = tmp_path / "dispatch.jsonl"
    _write_trace(trace)

    result = count_read_rail_calls(trace)

    assert result["kind"] == "observational_call_counts"
    assert result["per_actor"]["agent:a"]["bootstrap"] == 1
    assert result["per_actor"]["agent:a"]["work_queue"] == 2
    assert result["per_actor"]["agent:a"]["total"] == 3
    assert result["per_actor"]["agent:b"]["coach"] == 1
    assert result["per_actor"]["agent:b"]["mistake_tripwire"] == 1
    assert result["per_actor"]["agent:b"]["calibration_advisory"] == 1


def test_output_labels_read_rail_counts_observational_trace_only_not_replay(tmp_path: Path):
    db = tmp_path / "journal.sqlite"
    trace = tmp_path / "dispatch.jsonl"
    _seed_db(db)
    _write_trace(trace)

    output = build_skill_metrics(db, trace)
    read = output["read_rail_adoption"]

    assert read["trace_only"] is True
    assert read["not_replay_reproducible"] is True
    assert read["not_causal_precedence_claim"] is True
    caveat = read["caveat"].lower()
    assert "observational" in caveat
    assert "not a causal" in caveat
    assert "not reproducible" in caveat


def test_write_rail_adoption_derives_from_forecast_independence_locks(tmp_path: Path):
    db = tmp_path / "journal.sqlite"
    _seed_db(db)
    conn = sqlite3.connect(db)
    try:
        result = derive_write_rail_adoption(conn)
    finally:
        conn.close()

    agent_a = result["per_actor"]["agent:a"]
    assert agent_a["lock_count"] == 1
    assert agent_a["independence_proven_count"] == 1
    assert agent_a["locks"][0]["blind_commit_seq"] == 10
    assert agent_a["locks"][0]["reveal_seq"] == 11
    assert agent_a["locks"][0]["independence_proven"] is True
    assert result["per_actor"]["agent:b"]["independence_proven_count"] == 0


def test_per_actor_skill_metric_buckets_are_produced(tmp_path: Path):
    db = tmp_path / "journal.sqlite"
    trace = tmp_path / "dispatch.jsonl"
    _seed_db(db)
    _write_trace(trace)

    output = build_skill_metrics(db, trace)
    agent_a = output["skill_metrics"]["agent:a"]

    assert set(agent_a) == {"calibration", "process_quality", "resolution_misreads", "pnl"}
    assert agent_a["calibration"]["sample_size"] == 1
    assert agent_a["calibration"]["mean_brier_score"] == 0.09
    assert agent_a["process_quality"]["sample_size"] == 1
    assert agent_a["process_quality"]["direction_consistency_rate"] == 1.0
    assert agent_a["resolution_misreads"]["sample_size"] == 1
    assert agent_a["pnl"]["realized_pnl"] == 1.25
