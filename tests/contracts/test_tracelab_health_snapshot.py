from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.tracelab.health_snapshot import (
    CanaryConfig,
    HealthSnapshotConfig,
    Thresholds,
    collect_db_counts,
    run_gamma_canary,
    take_snapshot,
)
from trade_trace.mcp_server import mcp_call
from trade_trace.storage.database import open_database_readonly
from trade_trace.storage.paths import db_path


def _init_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(home)})
    assert env.ok, env
    return home


def _seed_health_rows(home: Path) -> None:
    conn = sqlite3.connect(db_path(home), isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO events(event_type, subject_kind, subject_id, payload_json, actor_id, created_at) VALUES (?,?,?,?,?,?)",
            ("test", "health", "1", "{}", "tester", "2026-01-01T00:00:00Z"),
        )
        event_id = conn.execute("SELECT max(id) FROM events").fetchone()[0]
        conn.executemany(
            "INSERT INTO outbox(event_id, export_kind, state) VALUES (?, 'jsonl', ?)",
            [(event_id, "pending"), (event_id, "failed"), (event_id, "exported")],
        )
        conn.execute(
            "INSERT INTO venues(id, name, kind, created_at, actor_id) VALUES (?,?,?,?,?)",
            ("venue-1", "Venue", "prediction_market", "2026-01-01T00:00:00Z", "tester"),
        )
        conn.execute(
            "INSERT INTO instruments(id, venue_id, symbol, title, asset_class, created_at, actor_id) VALUES (?,?,?,?,?,?,?)",
            ("instr-1", "venue-1", "PM", "Prediction Market", "prediction_market", "2026-01-01T00:00:00Z", "tester"),
        )
        conn.execute(
            "INSERT INTO theses(id, instrument_id, side, body, created_at, actor_id) VALUES (?,?,?,?,?,?)",
            ("thesis-1", "instr-1", "yes", "statement", "2026-01-01T00:00:00Z", "tester"),
        )
        conn.executemany(
            """
            INSERT INTO forecasts(id, thesis_id, kind, yes_label, scoring_state, created_at, actor_id)
            VALUES (?, 'thesis-1', 'binary', 'Yes', ?, '2026-01-01T00:00:00Z', 'tester')
            """,
            [("forecast-open", "pending"), ("forecast-scored", "scored")],
        )
        conn.execute(
            """
            INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, status, created_at, actor_id)
            VALUES ('outcome-1', 'instr-1', '2026-01-02T00:00:00Z', 'Yes', 'resolved_final', '2026-01-02T00:00:00Z', 'tester')
            """
        )
        conn.execute(
            """
            INSERT INTO forecast_scores(id, forecast_id, outcome_id, metric, score, scored_at, actor_id)
            VALUES ('score-1', 'forecast-scored', 'outcome-1', 'brier', 0.1, '2026-01-02T00:00:00Z', 'tester')
            """
        )
        conn.executemany(
            """
            INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, closed_at, updated_at)
            VALUES (?, 'instr-1', 'paper', 'yes', ?, '2026-01-01T00:00:00Z', ?, '2026-01-02T00:00:00Z')
            """,
            [("pos-open", "open", None), ("pos-partial", "partial", None), ("pos-closed", "closed", "2026-01-02T00:00:00Z")],
        )
    finally:
        conn.close()


@dataclass
class FakeDiskUsage:
    total: int
    used: int
    free: int


@dataclass
class FakeVfs:
    f_favail: int


class FakeEnv:
    ok = True

    def __init__(self, data: dict):
        self.data = data


def test_snapshotter_opens_readonly_and_query_only_rejects_write(tmp_path: Path):
    home = _init_home(tmp_path)
    db = open_database_readonly(db_path(home))
    try:
        assert db.connection.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.connection.execute(
                "INSERT INTO events(event_type, subject_kind, subject_id, payload_json, actor_id, created_at) VALUES ('x','x','x','{}','x','x')"
            )
    finally:
        db.close()


def test_health_snapshot_reports_required_counts_and_appends_jsonl(tmp_path: Path):
    home = _init_home(tmp_path)
    _seed_health_rows(home)
    out = tmp_path / "health.jsonl"

    snap = take_snapshot(
        HealthSnapshotConfig(home=home, output_path=out),
        now=lambda: datetime(2026, 1, 3, tzinfo=UTC),
        disk_usage=lambda path: FakeDiskUsage(total=100, used=40, free=60),
        statvfs=lambda path: FakeVfs(f_favail=7),
    )

    assert snap["counts"] == {
        "events": 1,
        "forecast_scores": 1,
        "positions_open": 2,
        "positions_closed": 1,
        "outbox_backlog": 2,
        "resolved_but_unclosed_forecasts": 1,
    }
    assert snap["filesystem"] == {"free_disk_bytes": 60, "free_inodes": 7}
    assert json.loads(out.read_text(encoding="utf-8"))["counts"] == snap["counts"]


def test_free_inode_threshold_alarm_is_reported(tmp_path: Path):
    home = _init_home(tmp_path)
    snap = take_snapshot(
        HealthSnapshotConfig(home=home, output_path=tmp_path / "health.jsonl", thresholds=Thresholds(min_free_inodes=10)),
        disk_usage=lambda path: FakeDiskUsage(total=100, used=40, free=60),
        statvfs=lambda path: FakeVfs(f_favail=9),
    )
    assert {alarm["code"] for alarm in snap["alarms"]} == {"LOW_FREE_INODES"}


def test_readonly_snapshot_does_not_block_live_writer(tmp_path: Path):
    home = _init_home(tmp_path)
    writer = sqlite3.connect(db_path(home), isolation_level=None, check_same_thread=False)
    ready = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def write_transaction() -> None:
        try:
            writer.execute("BEGIN IMMEDIATE")
            ready.set()
            release.wait(timeout=5)
            writer.execute(
                "INSERT INTO events(event_type, subject_kind, subject_id, payload_json, actor_id, created_at) VALUES ('writer','x','x','{}','x','2026-01-01T00:00:00Z')"
            )
            writer.commit()
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    thread = threading.Thread(target=write_transaction)
    thread.start()
    assert ready.wait(timeout=5)
    try:
        counts = collect_db_counts(db_path(home))
        assert counts["events"] == 0
    finally:
        release.set()
        thread.join(timeout=5)
        writer.close()
    assert not errors
    assert not thread.is_alive()
    assert collect_db_counts(db_path(home))["events"] == 1


def test_gamma_canary_accepts_valid_binary_snapshot_and_alarms_on_schema_drift(tmp_path: Path):
    calls: list[tuple[str, dict]] = []

    def ok_call(tool: str, args: dict) -> FakeEnv:
        calls.append((tool, args))
        return FakeEnv({"instrument_id": "mkt-1", "bid": 0.4, "ask": 0.6, "implied_probability": 0.5, "outcomes": ["Yes", "No"]})

    result = run_gamma_canary(CanaryConfig(home=str(tmp_path), market_id="mkt-1", mcp_call=ok_call))
    assert result == {"enabled": True, "ok": True, "market_id": "mkt-1"}
    assert calls == [("snapshot.fetch", {"home": str(tmp_path), "market_id": "mkt-1", "at": "now"})]

    def drift_call(tool: str, args: dict) -> FakeEnv:
        return FakeEnv({"instrument_id": "mkt-1", "bid": 0.4, "ask": 0.6, "outcomes": ["Yes", "No"]})

    snap = take_snapshot(
        HealthSnapshotConfig(
            home=_init_home(tmp_path / "drift"),
            output_path=tmp_path / "drift-health.jsonl",
            canary=CanaryConfig(home=str(tmp_path), market_id="mkt-1", mcp_call=drift_call),
        ),
        disk_usage=lambda path: FakeDiskUsage(total=100, used=40, free=60),
        statvfs=lambda path: FakeVfs(f_favail=99),
    )
    assert snap["canary"]["ok"] is False
    assert {alarm["code"] for alarm in snap["alarms"]} == {"GAMMA_SCHEMA_CANARY"}


def test_journal_status_output_unchanged_by_sidecar(tmp_path: Path):
    home = _init_home(tmp_path)
    before = mcp_call("journal.status", {"home": str(home)})
    assert before.ok, before
    take_snapshot(
        HealthSnapshotConfig(home=home, output_path=tmp_path / "health.jsonl"),
        disk_usage=lambda path: FakeDiskUsage(total=100, used=40, free=60),
        statvfs=lambda path: FakeVfs(f_favail=99),
    )
    after = mcp_call("journal.status", {"home": str(home)})
    assert after.ok, after
    assert after.data == before.data
