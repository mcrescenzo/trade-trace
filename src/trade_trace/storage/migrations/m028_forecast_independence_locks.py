"""Migration 028_forecast_independence_locks.

Pre-commit forecast independence lock (trade-trace-4kec.9). The frozen
`forecast.anchor_to_snapshot` linked a forecast to a market snapshot *after the
fact* and proved nothing about whether the forecast was made blind to the
market price. This table records, immutably, that a forecast was committed
BLIND (no snapshot consulted) and a market snapshot was revealed/bound only
afterward — capturing the event-log ordering so independence can be proven.
Append-only, single insert at reveal time.
"""

from __future__ import annotations

import sqlite3


def _migration_028_forecast_independence_locks(conn: sqlite3.Connection) -> None:
    """Create the append-only forecast independence lock table."""

    conn.execute(
        """
        CREATE TABLE forecast_independence_locks (
            id TEXT PRIMARY KEY,
            forecast_id TEXT NOT NULL UNIQUE REFERENCES forecasts(id),
            snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
            blind_committed_at TEXT NOT NULL,
            blind_commit_seq INTEGER NOT NULL,
            revealed_at TEXT NOT NULL,
            reveal_seq INTEGER NOT NULL,
            independence_proven INTEGER NOT NULL CHECK (independence_proven IN (0, 1)),
            run_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            CHECK (reveal_seq > blind_commit_seq OR independence_proven = 0)
        )
        """,
    )
    conn.execute("CREATE INDEX idx_fil_forecast ON forecast_independence_locks(forecast_id)")
    conn.execute("CREATE INDEX idx_fil_snapshot ON forecast_independence_locks(snapshot_id)")
    conn.execute(
        """
        CREATE TRIGGER trg_forecast_independence_locks_no_update
        BEFORE UPDATE ON forecast_independence_locks
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on forecast_independence_locks is forbidden');
        END
        """,
    )
    conn.execute(
        """
        CREATE TRIGGER trg_forecast_independence_locks_no_delete
        BEFORE DELETE ON forecast_independence_locks
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on forecast_independence_locks is forbidden');
        END
        """,
    )


__all__ = ["_migration_028_forecast_independence_locks"]
