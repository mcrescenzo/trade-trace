"""Migration 001_meta_table (extracted from storage/migrations.py per trade-trace-58ic). Schema-equivalence is gated by `tests/integration/test_migrations_schema_hash.py`."""

from __future__ import annotations

import sqlite3


def _migration_001_meta_table(conn: sqlite3.Connection) -> None:
    """Initial migration: create the `meta` table that stores schema_version
    and the package/contract version pair the DB was initialized against.

    `meta` is a low-volume key/value table. Updates write a corresponding
    `meta.updated` event once events ship in M1 (persistence.md §2).
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
