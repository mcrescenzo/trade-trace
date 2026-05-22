"""Migration 011_agent_continuity_provenance.

Add nullable agent/session segmentation fields to append-only source-like rows
whose public Pydantic/tool schemas already expose common metadata. This keeps
A-roadmap continuity features from relying on phantom provenance fields.
"""

from __future__ import annotations

import sqlite3

_SEGMENTATION_COLUMNS = ("agent_id", "model_id", "environment", "run_id")


def _migration_011_agent_continuity_provenance(conn: sqlite3.Connection) -> None:
    """Add passive run/session provenance columns to snapshots and sources.

    The fields are nullable, reporting-only dimensions. They do not imply a
    scheduler, runtime manager, broker account, execution environment, or data
    fetcher. Existing rows keep NULLs; existing write callers remain valid.
    """

    for table in ("snapshots", "sources"):
        for column in _SEGMENTATION_COLUMNS:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
        conn.execute(
            f"CREATE INDEX idx_{table}_agent_run ON "
            f"{table}(agent_id, model_id, environment, run_id)"
        )
