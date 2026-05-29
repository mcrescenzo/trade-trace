"""Migration 029_resolution_interpretations.

Resolution-criteria interpretation as a first-class field (trade-trace-4kec.12).
Records the agent's READING of how a market will resolve, at forecast time, so
"right about the world, wrong about the contract" becomes a measurable error
class when checked against the actual resolution source. Append-only.
"""

from __future__ import annotations

import sqlite3


def _migration_029_resolution_interpretations(conn: sqlite3.Connection) -> None:
    """Create the append-only resolution-interpretation table."""

    conn.execute(
        """
        CREATE TABLE resolution_interpretations (
            id TEXT PRIMARY KEY,
            forecast_id TEXT NOT NULL UNIQUE REFERENCES forecasts(id),
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            interpreted_resolution_source TEXT,
            interpreted_yes_condition TEXT NOT NULL,
            expected_outcome_label TEXT,
            as_of TEXT NOT NULL,
            run_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT,
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """,
    )
    conn.execute("CREATE INDEX idx_resint_forecast ON resolution_interpretations(forecast_id)")
    conn.execute("CREATE INDEX idx_resint_instrument ON resolution_interpretations(instrument_id)")
    conn.execute(
        """
        CREATE TRIGGER trg_resolution_interpretations_no_update
        BEFORE UPDATE ON resolution_interpretations
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on resolution_interpretations is forbidden');
        END
        """,
    )
    conn.execute(
        """
        CREATE TRIGGER trg_resolution_interpretations_no_delete
        BEFORE DELETE ON resolution_interpretations
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on resolution_interpretations is forbidden');
        END
        """,
    )


__all__ = ["_migration_029_resolution_interpretations"]
