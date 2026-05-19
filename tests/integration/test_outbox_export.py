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


def _insert_raw_event_with_outbox(
    conn, *, event_type: str, payload_json: str, idempotency_key: str,
) -> int:
    """Insert an event row directly so the test can seed a corrupt
    payload_json the EventWriter would never produce. Returns the
    event_id. Required because the events table is append-only after
    migration 009; the corrupt row is a one-shot insert, not an
    update."""

    conn.execute(
        "INSERT INTO events(event_type, subject_kind, subject_id, "
        "payload_json, actor_id, idempotency_key, created_at) "
        "VALUES (?, 'decision', 'd_corrupt', ?, 'agent:default', ?, ?)",
        (event_type, payload_json, idempotency_key,
         "2026-05-19T12:00:00Z"),
    )
    event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO outbox(event_id, export_kind, state) "
        "VALUES (?, 'jsonl', 'pending')",
        (event_id,),
    )
    return event_id


def test_drain_marks_row_failed_when_payload_json_is_corrupt(tmp_path: Path):
    """Per bead trade-trace-eo4: a row whose payload_json is not valid
    JSON must be marked failed with a descriptive error_text and an
    incremented attempt_count, and the drain must continue processing
    subsequent rows rather than aborting."""

    home, db, writer = _journal(tmp_path)
    try:
        corrupt_event_id = _insert_raw_event_with_outbox(
            db.connection,
            event_type="decision.created",
            payload_json="this is not valid json",
            idempotency_key="bad-json",
        )
        # A valid row queued after the corrupt one must still drain.
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_ok",
            payload=_decision_payload(),
            actor_id="agent:default",
            idempotency_key="ok",
        )

        result = drain_outbox(db.connection, home)

        # The valid row exported, the corrupt row did not.
        assert len(result.exported_files) == 1
        assert corrupt_event_id not in result.exported_event_ids

        corrupt_state = db.connection.execute(
            "SELECT state, error_text, attempt_count FROM outbox "
            "WHERE event_id = ?",
            (corrupt_event_id,),
        ).fetchone()
        assert corrupt_state[0] == "failed"
        assert "payload_json_decode_error" in corrupt_state[1]
        assert corrupt_state[2] >= 1
    finally:
        db.close()


def test_drain_marks_row_failed_when_payload_json_is_not_an_object(tmp_path: Path):
    """JSON that decodes to a non-dict (list, string, number) is also
    treated as malformed — the JSONL exporter shape requires an object."""

    home, db, _writer = _journal(tmp_path)
    try:
        bad_event_id = _insert_raw_event_with_outbox(
            db.connection,
            event_type="decision.created",
            payload_json="[1, 2, 3]",  # valid JSON, wrong shape
            idempotency_key="bad-shape",
        )
        result = drain_outbox(db.connection, home)
        assert bad_event_id not in result.exported_event_ids
        row = db.connection.execute(
            "SELECT state, error_text FROM outbox WHERE event_id = ?",
            (bad_event_id,),
        ).fetchone()
        assert row[0] == "failed"
        assert "payload_json_not_object" in row[1]
    finally:
        db.close()


def test_secret_warning_carries_actionable_metadata(tmp_path: Path):
    """Per bead trade-trace-67sg / DEBT-037: secret_warnings entries now
    include relative path, per-pattern counts, match offsets, and an
    export_kind discriminator so the operator can locate and
    remediate the affected event without re-running an ad-hoc scan.
    Raw secret VALUES are still NOT surfaced — the warning is "did
    you mean to ship these out?", not "here are the secrets again
    in the logs"."""

    home, db, _writer = _journal(tmp_path)
    try:
        # Insert an event directly whose payload_json contains a
        # secret-shaped api_key. The EventWriter's write-time guard
        # rejects this on normal write paths, but a direct INSERT
        # simulates an upstream bug or backup-restore that bypassed
        # the guard — exactly the case this warning catches.
        secret = "s" + "k" + "-" + "FIXTUREFIXTUREFIXTUREXX1"
        db.connection.execute(
            "INSERT INTO events(event_type, subject_kind, subject_id, "
            "payload_json, actor_id, created_at) "
            "VALUES (?, 'decision', 'd_secret', ?, 'agent:default', ?)",
            (
                "decision.created",
                f'{{"instrument_id":"i_1","type":"skip","reason":"{secret}"}}',
                "2026-05-19T12:00:00Z",
            ),
        )
        event_id = db.connection.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0]
        db.connection.execute(
            "INSERT INTO outbox(event_id, export_kind, state) "
            "VALUES (?, 'jsonl', 'pending')",
            (event_id,),
        )
        result = drain_outbox(db.connection, home)
    finally:
        db.close()

    assert len(result.secret_warnings) == 1
    warning = result.secret_warnings[0]
    assert warning["event_id"] == event_id
    assert warning["event_type"] == "decision.created"
    assert "api_key" in warning["patterns"]
    assert warning["counts"]["api_key"] >= 1
    # offsets surfaced so the operator can jump to the bytes
    assert isinstance(warning["match_offsets"], list)
    assert warning["match_offsets"], "match_offsets must list at least one offset"
    # relative path stays inside the journal home so logs are usable
    assert warning["relative_path"].startswith("export/jsonl/")
    assert warning["export_kind"] == "full_local_raw"
    # The raw secret value is NOT in the warning — this is the
    # security boundary the bead pins.
    assert secret not in str(warning)


def test_jsonl_path_sanitizes_unsafe_event_type_characters(tmp_path: Path):
    """Per bead trade-trace-qc7 / DEBT-028: `event_type` may grow new
    values over time; any character outside the safe set must be
    replaced with `_` so a hostile or namespaced type can't escape
    the YYYY/MM/DD bucket directory."""

    from trade_trace.exporter import _safe_event_type_for_filename, jsonl_path

    # The safe path stays unchanged.
    assert _safe_event_type_for_filename("decision.created") == "decision.created"
    assert _safe_event_type_for_filename("memory_node.retained") == "memory_node.retained"
    assert _safe_event_type_for_filename("forecast-scored") == "forecast-scored"

    # Path separators get scrubbed; the leading "." is safe (it's
    # the namespace separator in event_type, e.g. "decision.created"),
    # but the slashes that would let the name escape the bucket
    # become "_".
    assert _safe_event_type_for_filename("../etc/passwd") == ".._etc_passwd"
    assert _safe_event_type_for_filename("foo/bar") == "foo_bar"
    assert _safe_event_type_for_filename("foo\\bar") == "foo_bar"
    assert _safe_event_type_for_filename("foo\x00bar") == "foo_bar"
    assert _safe_event_type_for_filename("") == "_"

    # And the full jsonl_path stays inside the date bucket no matter
    # what the event_type contains — slashes become underscores so
    # the bucket dir can't be escaped via path-traversal segments.
    home = tmp_path / "home"
    p = jsonl_path(home, "../bad/type", 42, "2026-05-19T12:00:00Z")
    assert p.is_relative_to(home / "export" / "jsonl" / "2026" / "05" / "19")
    assert p.name == ".._bad_type-42.jsonl"
    # The resolved absolute path stays under the date bucket too —
    # no `..` resolution can climb out.
    resolved = p.resolve()
    bucket = (home / "export" / "jsonl" / "2026" / "05" / "19").resolve()
    assert resolved.is_relative_to(bucket)


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
