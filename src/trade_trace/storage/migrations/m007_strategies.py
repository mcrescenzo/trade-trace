"""Migration 007_strategies (extracted from storage/migrations.py per trade-trace-58ic). Schema-equivalence is gated by `tests/integration/test_migrations_schema_hash.py`."""

from __future__ import annotations

import sqlite3


def _migration_007_strategies(conn: sqlite3.Connection) -> None:
    """Strategies table per bead trade-trace-ubp.

    First-class strategy rows (not tags). `slug` is a unique lowercase-
    kebab string scoped to a single Trade Trace database; `status` is a
    closed enum (active | archived). Archived strategies remain valid
    FK targets for historical decisions/theses so the audit history
    survives the soft-archive.
    """

    conn.execute(
        """
        CREATE TABLE strategies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE
                CHECK (length(slug) BETWEEN 1 AND 64),
            description TEXT,
            hypothesis TEXT,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','archived')),
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_strategies_slug ON strategies(slug)")
    conn.execute("CREATE INDEX idx_strategies_status ON strategies(status)")
    # Append-only on `created_at` semantics: rows can be UPDATEd by
    # strategy.update (which mutates `description`, `hypothesis`,
    # `status`, `meta_json`, `updated_at`). DELETE is blocked because
    # archived strategies stay live as FK targets.
    conn.execute(
        "CREATE TRIGGER trg_strategies_no_delete "
        "BEFORE DELETE ON strategies BEGIN "
        "SELECT RAISE(ABORT, 'append-only invariant: DELETE on strategies "
        "is forbidden; archive via strategy.update status=archived "
        "instead'); END"
    )
