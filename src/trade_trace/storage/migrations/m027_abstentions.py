"""Migration 027_abstentions.

First-class abstention / no-bet records (trade-trace-4kec.8). Recording a
"considered and passed" decision against a market makes the calibration
denominator honest: without it, calibration is survivorship-biased toward the
forecasts the agent chose to commit. Append-only, like every other journal
record table.
"""

from __future__ import annotations

import sqlite3


def _migration_027_abstentions(conn: sqlite3.Connection) -> None:
    """Create the append-only abstention record table."""

    conn.execute(
        """
        CREATE TABLE abstentions (
            id TEXT PRIMARY KEY,
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            thesis_id TEXT REFERENCES theses(id),
            reason TEXT NOT NULL,
            considered_probability REAL,
            as_of TEXT NOT NULL,
            run_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT,
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            CHECK (
                considered_probability IS NULL
                OR (considered_probability >= 0 AND considered_probability <= 1)
            )
        )
        """,
    )
    conn.execute("CREATE INDEX idx_abstentions_instrument ON abstentions(instrument_id, created_at)")
    conn.execute("CREATE INDEX idx_abstentions_created_at ON abstentions(created_at)")
    conn.execute(
        """
        CREATE TRIGGER trg_abstentions_no_update
        BEFORE UPDATE ON abstentions
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on abstentions is forbidden; record a new abstention');
        END
        """,
    )
    conn.execute(
        """
        CREATE TRIGGER trg_abstentions_no_delete
        BEFORE DELETE ON abstentions
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on abstentions is forbidden');
        END
        """,
    )


__all__ = ["_migration_027_abstentions"]
