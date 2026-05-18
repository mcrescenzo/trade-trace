"""Outbox drain semantics per trade-trace-b2r.

The drain consumes pending/failed outbox rows, writes one JSONL file per
event under `$TRADE_TRACE_HOME/export/jsonl/YYYY/MM/DD/`, and flips outbox
state to `exported`. Re-running on an already-drained outbox is a no-op
(idempotent). File content is byte-deterministic so a re-drain after a
restore writes byte-identical bytes.

Covers acceptance criteria:
- "JSONL exporter writes one event per file at path …"
- "Atomic write: `.jsonl.tmp` written first, then renamed …"
- "Exporter idempotent: replaying same outbox row produces same JSONL file
  content (compared by SHA-256)."
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_trace.events import EventWriter
from trade_trace.exporter import (
    FINAL_SUFFIX,
    TMP_SUFFIX,
    drain_outbox,
    iter_jsonl_files,
    sha256_of_file,
)
from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path


def _journal(tmp_path: Path):
    home = tmp_path / "home"
    db = open_database(db_path(home))
    apply_pending_migrations(db.connection)
    writer = EventWriter(db.connection)
    writer.set_outbox_jsonl_enabled()
    return home, db, writer


def _decision_payload(**overrides):
    base = {
        "instrument_id": "i_1",
        "type": "skip",
        "reason": "spread too wide",
        "tags": ["liquidity-ignored"],
    }
    base.update(overrides)
    return base


def test_drain_writes_one_file_per_outbox_row(tmp_path: Path):
    home, db, writer = _journal(tmp_path)
    try:
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(),
            actor_id="agent:default",
            idempotency_key="k1",
        )
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_2",
            payload=_decision_payload(reason="position size too small"),
            actor_id="agent:default",
            idempotency_key="k2",
        )
        result = drain_outbox(db.connection, home)
    finally:
        db.close()

    assert len(result.exported_files) == 2
    files = iter_jsonl_files(home)
    assert len(files) == 2
    # No leftover `.tmp` debris from a clean drain.
    assert all(not p.name.endswith(TMP_SUFFIX) for p in files)
    assert all(p.name.endswith(FINAL_SUFFIX) for p in files)


def test_drain_updates_outbox_state_to_exported(tmp_path: Path):
    home, db, writer = _journal(tmp_path)
    try:
        record = writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(),
            actor_id="agent:default",
            idempotency_key="k1",
        )
        drain_outbox(db.connection, home)
        row = db.connection.execute(
            "SELECT state, exported_at, error_text, attempt_count "
            "FROM outbox WHERE event_id = ?",
            (record.id,),
        ).fetchone()
        assert row is not None
        state, exported_at, error_text, attempt_count = row
        assert state == "exported"
        assert exported_at is not None
        assert error_text is None
        assert attempt_count >= 1
    finally:
        db.close()


def test_drain_is_idempotent_byte_for_byte(tmp_path: Path):
    """Re-running drain produces the same bytes — acceptance criterion
    requires SHA-256 equality after a second drain."""

    home, db, writer = _journal(tmp_path)
    try:
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(),
            actor_id="agent:default",
            idempotency_key="k1",
        )
        first = drain_outbox(db.connection, home)
        sha_before = {p.name: sha256_of_file(p) for p in first.exported_files}

        # The second drain has nothing new to do (state='exported' is skipped).
        second = drain_outbox(db.connection, home)
        assert second.exported_files == []

        # Force re-emit by flipping state back to pending (simulates a
        # backup restore where the outbox is rewound).
        db.connection.execute("UPDATE outbox SET state = 'pending'")
        third = drain_outbox(db.connection, home)
        sha_after = {p.name: sha256_of_file(p) for p in third.exported_files}
        assert sha_before == sha_after
    finally:
        db.close()


def test_drain_skips_already_exported_rows(tmp_path: Path):
    home, db, writer = _journal(tmp_path)
    try:
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(),
            actor_id="agent:default",
            idempotency_key="k1",
        )
        first = drain_outbox(db.connection, home)
        assert len(first.exported_files) == 1

        # Add a second event and re-drain; only the new row gets exported.
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_2",
            payload=_decision_payload(reason="other reason"),
            actor_id="agent:default",
            idempotency_key="k2",
        )
        second = drain_outbox(db.connection, home)
        assert len(second.exported_files) == 1
        # Both events now have their JSONL file on disk.
        assert len(iter_jsonl_files(home)) == 2
    finally:
        db.close()


def test_drain_recovers_failed_rows(tmp_path: Path):
    """Per operability.md §10.3, a row left in `failed` state by a crashed
    drain is retried on the next invocation."""

    home, db, writer = _journal(tmp_path)
    try:
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(),
            actor_id="agent:default",
            idempotency_key="k1",
        )
        # Simulate a previous drain that crashed mid-write.
        db.connection.execute(
            "UPDATE outbox SET state = 'failed', error_text = 'simulated', "
            "attempt_count = 1"
        )
        result = drain_outbox(db.connection, home)
        assert len(result.exported_files) == 1
        row = db.connection.execute(
            "SELECT state, error_text, attempt_count FROM outbox"
        ).fetchone()
        assert row[0] == "exported"
        assert row[1] is None
        # attempt_count keeps growing across retries (audit signal).
        assert row[2] >= 2
    finally:
        db.close()


def test_drain_writes_imports_md_superset_shape(tmp_path: Path):
    """The on-disk JSONL line matches imports.md §2.1: `{tool, args, _*}`."""

    home, db, writer = _journal(tmp_path)
    try:
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(),
            actor_id="agent:default",
            idempotency_key="k1",
        )
        result = drain_outbox(db.connection, home)
    finally:
        db.close()

    line = json.loads(result.exported_files[0].read_text())
    assert line["tool"] == "decision.add"
    assert isinstance(line["args"], dict)
    assert line["args"]["instrument_id"] == "i_1"
    assert line["args"]["type"] == "skip"
    for key in ("_event_id", "_event_type", "_actor_id", "_created_at", "_contract_version"):
        assert key in line
    assert line["_event_type"] == "decision.created"
    assert line["_actor_id"] == "agent:default"
    assert line["_contract_version"] == "1.0"


def test_drain_cleans_orphan_tmp_files(tmp_path: Path):
    """The drain runs the orphan cleanup as a side effect (per operability.md
    §9.1 the cleanup runs on every drain invocation)."""

    import os
    import time

    home, db, _writer = _journal(tmp_path)
    try:
        base = home / "export" / "jsonl" / "2026" / "05" / "18"
        base.mkdir(parents=True)
        orphan = base / "decision.created-99.jsonl.tmp"
        orphan.write_text("{}")
        # Backdate two hours so it's older than the 1h cutoff.
        old = time.time() - 2 * 3600
        os.utime(orphan, (old, old))
        result = drain_outbox(db.connection, home)
    finally:
        db.close()

    assert orphan in result.orphans_cleaned
    assert not orphan.exists()
