"""Migration 010_strategy_id_new_row_triggers (extracted from storage/migrations.py per trade-trace-58ic). Schema-equivalence is gated by `tests/integration/test_migrations_schema_hash.py`."""

from __future__ import annotations

import sqlite3


def _migration_010_strategy_id_new_row_triggers(
    conn: sqlite3.Connection,
) -> None:
    """Validate `strategy_id` on new inserts into `decisions` and `theses`
    against the `strategies` table (bead trade-trace-z4q / DEBT-012).

    Migration 003 reserved `strategy_id` as a nullable TEXT column on
    `decisions` and `theses` because the `strategies` table itself
    didn't exist until migration 007. After 007 lands, that opens the
    door to rows referencing nonexistent strategies — making strategy
    reports/links/orphan cleanup fragile.

    Policy: new-row triggers (grandfathering pattern). NULL stays
    legal (the canonical "no strategy" value, also referenced by the
    ReportFilter sentinel `__none__`). Non-NULL values must exist in
    the `strategies` table at insert time. Rows that predated this
    migration are NOT validated — historic data is grandfathered.

    Why not strict FK: SQLite cannot add FKs to existing tables via
    ALTER TABLE; a rebuild would require copying every row and
    breaks the append-only invariant during the copy. Triggers give
    the same enforcement at insert time without touching history.
    """

    for table in ("decisions", "theses"):
        msg = (
            f"VALIDATION_ERROR: {table}.strategy_id references nonexistent "
            f"strategy; create the strategy first or leave the column NULL "
            f"(bead trade-trace-z4q)"
        )
        conn.execute(
            f"CREATE TRIGGER trg_{table}_strategy_id_exists "
            f"BEFORE INSERT ON {table} "
            f"WHEN NEW.strategy_id IS NOT NULL AND NOT EXISTS ("
            f"SELECT 1 FROM strategies WHERE id = NEW.strategy_id) "
            f"BEGIN SELECT RAISE(ABORT, '{msg}'); END"
        )
