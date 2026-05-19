"""Migration 009_events_append_only (extracted from storage/migrations.py per trade-trace-58ic). Schema-equivalence is gated by `tests/integration/test_migrations_schema_hash.py`."""

from __future__ import annotations

import sqlite3


def _migration_009_events_append_only(conn: sqlite3.Connection) -> None:
    """Harden `events` append-only and add opt-in memory embeddings storage.

    The embedding table is a regular row table containing sqlite-vec-compatible
    float32 blobs plus provider/model metadata. The sqlite-vec extension is only
    loaded by the connection layer when embeddings.provider != 'none'.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_node_embeddings (
            node_id TEXT NOT NULL REFERENCES memory_nodes(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            dim INTEGER NOT NULL CHECK (dim > 0),
            model_id TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (node_id, provider, model_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_node_embeddings_provider "
        "ON memory_node_embeddings(provider, model_id, dim)"
    )

    update_msg = (
        "append-only invariant: UPDATE on events is forbidden; "
        "append a new event to record follow-up state (persistence.md §8)"
    )
    delete_msg = (
        "append-only invariant: DELETE on events is forbidden (persistence.md §8)"
    )
    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_events_no_update
        BEFORE UPDATE ON events
        BEGIN
            SELECT RAISE(ABORT, '{update_msg}');
        END
        """
    )
    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_events_no_delete
        BEFORE DELETE ON events
        BEGIN
            SELECT RAISE(ABORT, '{delete_msg}');
        END
        """
    )
