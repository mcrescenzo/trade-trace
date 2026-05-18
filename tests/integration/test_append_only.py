"""Append-only invariants per persistence.md §8.

The M1 migration installs BEFORE UPDATE / BEFORE DELETE triggers on every
append-only table that raise sqlite3.IntegrityError with an explicit
"append-only invariant" message.

Correction path for any append-only row is a `supersedes` edge from the new
row to the old, per PRD §3.1.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path


APPEND_ONLY_TABLES = [
    "snapshots",
    "theses",
    "forecasts",
    "forecast_outcomes",
    "forecast_scores",
    "decisions",
    "decision_tags",
    "outcomes",
    "sources",
    "edges",
    "position_events",
    "signals",
]


def _db(tmp_path: Path):
    db = open_database(db_path(tmp_path / "home"))
    apply_pending_migrations(db.connection)
    return db


def _seed_minimal(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        INSERT INTO venues(id, name, kind, created_at, actor_id)
            VALUES ('v_1', 'manual', 'manual', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
            VALUES ('i_1', 'v_1', 'Test', 'prediction_market', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO theses(id, instrument_id, side, body, created_at, actor_id)
            VALUES ('t_1', 'i_1', 'yes', '...', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO forecasts(id, thesis_id, kind, created_at, actor_id)
            VALUES ('f_1', 't_1', 'binary', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO forecast_outcomes(id, forecast_id, outcome_label, probability)
            VALUES ('fo_1', 'f_1', 'YES', 0.6);
        INSERT INTO snapshots(id, instrument_id, captured_at, created_at, actor_id)
            VALUES ('snap_1', 'i_1', '2026-05-18T14:00:00Z', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO decisions(id, instrument_id, type, created_at, actor_id)
            VALUES ('d_1', 'i_1', 'skip', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO decision_tags(decision_id, tag) VALUES ('d_1', 'liquidity-ignored');
        INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, status, created_at, actor_id)
            VALUES ('o_1', 'i_1', '2026-05-18T14:00:00Z', 'YES', 'resolved_final',
                    '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO sources(id, kind, created_at, actor_id)
            VALUES ('s_1', 'note', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, edge_type, created_at, actor_id)
            VALUES ('e_1', 'source', 's_1', 'thesis', 't_1', 'about', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO position_events(id, position_id, instrument_id, event_type, created_at, actor_id)
            VALUES ('pe_1', 'p_1', 'i_1', 'open', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO forecast_scores(id, forecast_id, outcome_id, metric, score, scored_at, actor_id)
            VALUES ('fs_1', 'f_1', 'o_1', 'brier_binary', 0.16, '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO signals(id, kind, severity, created_at, actor_id)
            VALUES ('sig_1', 'sample_size_warning', 'warn',
                    '2026-05-18T14:00:00Z', 'system:report.coach');
        """
    )


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_update_forbidden(tmp_path: Path, table: str):
    """Every append-only table's BEFORE UPDATE trigger raises with an
    append-only-invariant message."""

    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        # Find a sample row.
        cur = db.connection.execute(f"SELECT * FROM {table} LIMIT 1")
        row = cur.fetchone()
        assert row is not None, f"seeded {table} but found no row"

        # Get the primary key column. For tables with a single 'id' column
        # we use that; for decision_tags we have a composite key, but UPDATE
        # on any column still fires the trigger.
        cur = db.connection.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        # Pick the first non-FK-ish column to try to UPDATE.
        target_col = next((c for c in cols if c not in ("decision_id",)), cols[0])
        with pytest.raises(sqlite3.IntegrityError) as exc:
            db.connection.execute(f"UPDATE {table} SET {target_col} = {target_col}")
        assert "append-only invariant" in str(exc.value)
    finally:
        db.close()


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_delete_forbidden(tmp_path: Path, table: str):
    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        with pytest.raises(sqlite3.IntegrityError) as exc:
            db.connection.execute(f"DELETE FROM {table}")
        assert "append-only invariant" in str(exc.value)
    finally:
        db.close()


def test_supersedes_edge_is_correction_path(tmp_path: Path):
    """Per PRD §3.1 outcomes: corrections produce a NEW outcomes row
    connected to the prior via a `supersedes` edge. No mutation needed."""

    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)

        # Append a corrected outcome row (NOT updating the original).
        db.connection.execute(
            "INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, "
            "status, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("o_2", "i_1", "2026-05-18T14:00:00Z", "NO", "resolved_final",
             "2026-05-19T14:00:00Z", "agent:default"),
        )
        # And the supersedes edge from new → prior.
        db.connection.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
            "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("e_2", "outcome", "o_2", "outcome", "o_1", "supersedes",
             "2026-05-19T14:00:00Z", "agent:default"),
        )
        # Both outcome rows still readable.
        count = db.connection.execute("SELECT COUNT(*) FROM outcomes WHERE instrument_id = 'i_1'").fetchone()[0]
        assert count == 2
        cur = db.connection.execute(
            "SELECT target_id FROM edges WHERE source_id = 'o_2' AND edge_type = 'supersedes'"
        )
        assert cur.fetchone()[0] == "o_1"
    finally:
        db.close()


def test_outbox_state_update_allowed(tmp_path: Path):
    """`outbox` is an exception: the exporter updates state/exported_at/
    error_text/attempt_count (persistence.md §8 exemption). The migration
    002 outbox table doesn't have the append-only trigger."""

    db = _db(tmp_path)
    try:
        # Insert an event + outbox row.
        db.connection.execute(
            "INSERT INTO events(event_type, subject_kind, subject_id, payload_json, "
            "actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("decision.created", "decision", "d_1", "{}", "agent:default", "2026-05-18T14:00:00Z"),
        )
        event_id = db.connection.execute("SELECT id FROM events").fetchone()[0]
        db.connection.execute(
            "INSERT INTO outbox(event_id, export_kind, state) VALUES (?, 'jsonl', 'pending')",
            (event_id,),
        )
        # Update the outbox row's state (the exporter's pattern).
        db.connection.execute(
            "UPDATE outbox SET state = 'exported', exported_at = ? WHERE event_id = ?",
            ("2026-05-18T14:01:00Z", event_id),
        )
        row = db.connection.execute("SELECT state FROM outbox WHERE event_id = ?", (event_id,)).fetchone()
        assert row[0] == "exported"
    finally:
        db.close()
