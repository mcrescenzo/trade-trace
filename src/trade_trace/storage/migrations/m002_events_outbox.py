"""Migration 002_events_outbox (extracted from storage/migrations.py per trade-trace-58ic). Schema-equivalence is gated by `tests/integration/test_migrations_schema_hash.py`."""

from __future__ import annotations

import sqlite3


def _migration_002_events_outbox(conn: sqlite3.Connection) -> None:
    """Create the `events` log and `outbox` queue per persistence.md §3-§4.

    `events` is append-only; the deduplication index is the partial unique
    index on `(event_type, actor_id, idempotency_key)` where the key is not
    null (per persistence.md §3 indexes block). `outbox` is the queue that
    drives optional JSONL export; one row per `events.id` when export is
    enabled.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            subject_kind TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            idempotency_key TEXT,
            created_at TEXT NOT NULL,
            request_id TEXT,
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_subject "
        "ON events(subject_kind, subject_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at)"
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_events_idempotency
        ON events(event_type, actor_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            export_kind TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending'
                CHECK (state IN ('pending', 'exported', 'failed')),
            exported_at TEXT,
            error_text TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_outbox_pending "
        "ON outbox(state, export_kind, id)"
    )

    # `config` is a key/value table for runtime flags like
    # `outbox.jsonl_enabled`. Distinct from `meta` (which holds
    # immutable-after-init schema/version metadata).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
