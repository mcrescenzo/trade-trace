"""Migration 013_forecast_snapshot_anchor.

Add a one-to-one anchor connecting forecasts to the market snapshot whose
implied probability should be copied for later scoring/reporting.
"""

from __future__ import annotations

import sqlite3


def _migration_013_forecast_snapshot_anchor(conn: sqlite3.Connection) -> None:
    """Create forecast_snapshot_anchor table."""

    conn.execute(
        """
        CREATE TABLE forecast_snapshot_anchor (
            id TEXT PRIMARY KEY,
            forecast_id TEXT NOT NULL UNIQUE REFERENCES forecasts(id),
            snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
            market_implied_probability REAL,
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_fsa_forecast ON forecast_snapshot_anchor(forecast_id)")
    conn.execute("CREATE INDEX idx_fsa_snapshot ON forecast_snapshot_anchor(snapshot_id)")
