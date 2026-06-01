"""Deterministic concurrency contract validation for trade-trace-7jqb.

These tests assert the documented contract, not parallel-write support:
operability.md §3 says SQLite WAL permits concurrent readers but serializes
writers, with second-writer failures surfaced as STORAGE_ERROR
single_writer_lock; persistence.md §2 says SQLite at $TRADE_TRACE_HOME is the
WAL-mode source of truth.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from textwrap import dedent

from tests._mcp_helpers import envelope_default as _envelope
from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.dispatch_trace import ENABLE_ENV, PATH_ENV
from trade_trace.storage.database import BUSY_TIMEOUT_MS, open_database
from trade_trace.storage.paths import db_path


def _seed_writable_journal(home: Path) -> str:
    _mcp(home, "journal.init", {})
    venue_env = _mcp(
        home,
        "venue.add",
        {"name": "PM", "kind": "prediction_market", "idempotency_key": "cc-venue"},
    )
    assert venue_env.ok is True
    venue = venue_env.data["id"]
    instrument_env = _mcp(
        home,
        "instrument.add",
        {
            "venue_id": venue,
            "asset_class": "prediction_market",
            "title": "Concurrency contract market",
            "idempotency_key": "cc-instrument",
        },
    )
    assert instrument_env.ok is True
    instrument = instrument_env.data["id"]
    return str(instrument)


def _wait_for_file(path: Path, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path}")


def _start_sqlite_writer(db_file: Path, ready_file: Path, *, hold_seconds: float = 8.0) -> subprocess.Popen[str]:
    subject_id = f"held-write-{ready_file.name}"
    idempotency_key = f"cc-held-write-{ready_file.name}"
    code = dedent(
        f"""
        import sqlite3, time
        from pathlib import Path
        conn = sqlite3.connect({str(db_file)!r}, isolation_level=None)
        conn.execute('PRAGMA journal_mode = WAL')
        conn.execute('BEGIN IMMEDIATE')
        try:
            conn.execute('''INSERT INTO events(event_type, subject_kind, subject_id, payload_json, actor_id, idempotency_key, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)''',
                         ('concurrency.hold', 'test', {subject_id!r}, '{{}}', 'agent:default', {idempotency_key!r}, '2026-05-26T00:00:00Z'))
            Path({str(ready_file)!r}).write_text('inserted')
            time.sleep({hold_seconds!r})
        finally:
            conn.execute('ROLLBACK')
            conn.close()
        """
    )
    return subprocess.Popen([sys.executable, "-c", code], text=True)


def test_second_writer_contention_emits_single_writer_lock_with_retry_hint(tmp_path: Path, monkeypatch) -> None:
    """Second writer lock errors are retried in-process and recover under the
    same request lineage before the caller sees the envelope.
    """
    home = tmp_path / "home"
    trace_path = tmp_path / "dispatch-trace.jsonl"
    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.setenv(PATH_ENV, str(trace_path))
    instrument_id = _seed_writable_journal(home)
    ready = tmp_path / "writer-ready"
    holder = _start_sqlite_writer(db_path(home), ready, hold_seconds=6.5)
    try:
        _wait_for_file(ready)
        start = time.monotonic()
        first = _envelope(
            home,
            "decision.add",
            {
                "instrument_id": instrument_id,
                "type": "skip",
                "reason": "contended writer one",
                "idempotency_key": "cc-contention-1",
            },
        )
        elapsed = time.monotonic() - start
        assert elapsed >= (BUSY_TIMEOUT_MS / 1000) * 0.80
        assert elapsed < (BUSY_TIMEOUT_MS / 1000) + 4.0
        assert first["ok"] is True
        records = [json.loads(line) for line in trace_path.read_text().splitlines()]
        lock_records = [record for record in records if record.get("details", {}).get("reason") == "single_writer_lock"]
        assert lock_records
        for lock_record in lock_records:
            request_id = lock_record["request_id"]
            assert any(
                record.get("ok") is True
                and record.get("request_id") == request_id
                and record.get("retry_of") == request_id
                and record.get("attempt") == lock_record.get("attempt", 0) + 1
                for record in records
            )
    finally:
        if holder.poll() is None:
            holder.terminate()
            try:
                holder.wait(timeout=2)
            except subprocess.TimeoutExpired:
                holder.kill()
                holder.wait(timeout=2)

    follow_up = _envelope(
        home,
        "decision.add",
        {
            "instrument_id": instrument_id,
            "type": "skip",
            "reason": "lock released writer succeeds",
            "idempotency_key": "cc-contention-follow-up",
        },
    )
    assert follow_up["ok"] is True


def test_wal_reader_observes_snapshot_while_writer_transaction_is_open(tmp_path: Path) -> None:
    """operability.md §3.1/§3.2 and persistence.md §2: WAL writers must not
    block readers; a read during an uncommitted write returns the committed
    snapshot and never single_writer_lock.
    """
    home = tmp_path / "home"
    _seed_writable_journal(home)
    db_file = db_path(home)
    db = open_database(db_file, create_parent=False)
    try:
        before = db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        db.close()

    ready = tmp_path / "wal-writer-ready"
    holder = _start_sqlite_writer(db_file, ready, hold_seconds=4.0)
    try:
        _wait_for_file(ready)
        start = time.monotonic()
        reader = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True, isolation_level=None)
        try:
            reader.execute("PRAGMA query_only = 1")
            count = reader.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            reader.close()
        elapsed = time.monotonic() - start
    finally:
        if holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=2)

    assert count == before
    assert elapsed < 1.0


def test_kill_mid_write_rolls_back_partial_event_and_follow_up_writer_succeeds(tmp_path: Path) -> None:
    """operability.md §10.1 and persistence.md §2/§3: killing a writer after
    INSERT but before COMMIT leaves no partial event row; the next writer can
    acquire the WAL single-writer lock and commit cleanly.
    """
    home = tmp_path / "home"
    instrument_id = _seed_writable_journal(home)
    db_file = db_path(home)
    ready = tmp_path / "mid-write-ready"
    subject_id = "kill-mid-write-subject"
    code = dedent(
        f"""
        import sqlite3, time
        from pathlib import Path
        conn = sqlite3.connect({str(db_file)!r}, isolation_level=None)
        conn.execute('PRAGMA journal_mode = WAL')
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('''INSERT INTO events(event_type, subject_kind, subject_id, payload_json, actor_id, idempotency_key, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                     ('decision.created', 'decision', {subject_id!r}, '{{}}', 'agent:default', 'cc-killed', '2026-05-26T00:00:00Z'))
        Path({str(ready)!r}).write_text('inserted')
        time.sleep(60)
        conn.execute('COMMIT')
        """
    )
    proc = subprocess.Popen([sys.executable, "-c", code], text=True)
    _wait_for_file(ready)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=5)
    assert proc.returncode == -signal.SIGKILL

    db = open_database(db_file, create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE subject_id = ?", (subject_id,)
        ).fetchone()
    finally:
        db.close()
    assert row[0] == 0

    follow_up = _envelope(
        home,
        "decision.add",
        {
            "instrument_id": instrument_id,
            "type": "skip",
            "reason": "post-kill recovery writer",
            "idempotency_key": "cc-post-kill-follow-up",
        },
    )
    assert follow_up["ok"] is True
