"""Migration 005_signals (extracted from storage/migrations.py per trade-trace-58ic). Schema-equivalence is gated by `tests/integration/test_migrations_schema_hash.py`."""

from __future__ import annotations

import sqlite3


def _migration_005_signals(conn: sqlite3.Connection) -> None:
    """M2 signals table per trade-trace-och.

    Append-only. Rows are emitted lazily by `report.coach` or an explicit
    scan tool — never by a background daemon. `kind` is an open enum
    (extensions are non-breaking per operability.md §4.3); `severity` is
    a closed enum CHECK-constrained to {info, warn, critical}. Indexed
    on (kind, severity, created_at) for the coach's scan query.
    """

    conn.execute(
        """
        CREATE TABLE signals (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            severity TEXT NOT NULL CHECK (severity IN ('info','warn','critical')),
            body TEXT,
            meta_json TEXT NOT NULL DEFAULT '{}',
            related_refs_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            expires_at TEXT,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_signals_scan ON signals(kind, severity, created_at)"
    )
    conn.execute(
        "CREATE INDEX idx_signals_expires ON signals(expires_at) "
        "WHERE expires_at IS NOT NULL"
    )

    # Append-only triggers per persistence.md §8 (signals is on the
    # append-only list there).
    update_msg = (
        "append-only invariant: UPDATE on signals is forbidden; "
        "emit a new signal row to record a change (persistence.md §8)"
    )
    delete_msg = (
        "append-only invariant: DELETE on signals is forbidden (persistence.md §8)"
    )
    conn.execute(
        f"""
        CREATE TRIGGER trg_signals_no_update
        BEFORE UPDATE ON signals
        BEGIN
            SELECT RAISE(ABORT, '{update_msg}');
        END
        """
    )
    conn.execute(
        f"""
        CREATE TRIGGER trg_signals_no_delete
        BEFORE DELETE ON signals
        BEGIN
            SELECT RAISE(ABORT, '{delete_msg}');
        END
        """
    )
