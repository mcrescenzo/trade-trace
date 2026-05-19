"""Migration 006_memory_layer (extracted from storage/migrations.py per trade-trace-58ic). Schema-equivalence is gated by `tests/integration/test_migrations_schema_hash.py`."""

from __future__ import annotations

import sqlite3


def _migration_006_memory_layer(conn: sqlite3.Connection) -> None:
    """M3 memory layer per bead trade-trace-e86 and docs/architecture/memory-layer.md.

    Adds:
    - `memory_nodes` — append-only typed memory rows (observation,
      reflection, playbook_rule) with bi-temporal validity columns
      (`valid_from`, `valid_to`, `invalidated_at`, `invalidated_by`),
      `importance` (1-10), `confidence_base`, and `decay_rate_per_day`.
    - `memory_recall_events` — append-only log of every `memory.recall`
      call (`strategies_used`, `node_ids_returned` JSON arrays). Drives
      the `memory_node_stats` rebuildable projection.
    - `memory_node_stats` — projection: per-node `recall_count` +
      `last_recalled_at`. Rebuildable from `memory_recall_events` per
      persistence.md §7.
    - `memory_node_fts` — FTS5 virtual table on `body` for the BM25
      recall strategy. The trigger pair keeps it in lockstep with
      `memory_nodes` writes.

    Append-only triggers cover `memory_nodes` and `memory_recall_events`;
    `memory_node_stats` is rebuildable so UPDATE/DELETE are allowed there
    (the projection-rebuild path needs them).

    Preflight: FTS5 is a hard dependency of the recall path (bead
    trade-trace-qis / DEBT-013). Migration aborts up front with a
    descriptive `FTS5UnavailableError` rather than failing partway
    through with a generic OperationalError after some tables have
    been created.
    """

    # Late-bind on the package so tests can monkeypatch
    # `trade_trace.storage.migrations._require_fts5` from the outside
    # (see tests/integration/test_migrations.py::test_memory_layer_migration_requires_fts5).
    from trade_trace.storage import migrations as _pkg

    _pkg._require_fts5(conn)

    conn.execute(
        """
        CREATE TABLE memory_nodes (
            id TEXT PRIMARY KEY,
            node_type TEXT NOT NULL CHECK (node_type IN
                ('observation','reflection','playbook_rule')),
            version INTEGER NOT NULL DEFAULT 1,
            parent_node_id TEXT REFERENCES memory_nodes(id),
            title TEXT,
            body TEXT NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{}',
            confidence_base REAL NOT NULL DEFAULT 1.0
                CHECK (confidence_base >= 0.0 AND confidence_base <= 1.0),
            decay_rate_per_day REAL,
            importance INTEGER NOT NULL DEFAULT 5
                CHECK (importance >= 1 AND importance <= 10),
            valid_from TEXT NOT NULL,
            valid_to TEXT,
            invalidated_at TEXT,
            invalidated_by TEXT REFERENCES memory_nodes(id),
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT,
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_memory_nodes_type ON memory_nodes(node_type)")
    conn.execute("CREATE INDEX idx_memory_nodes_validity "
                 "ON memory_nodes(valid_from, valid_to)")

    # Append-only triggers on memory_nodes (persistence.md §8).
    for action, msg in (
        ("UPDATE", "append-only invariant: UPDATE on memory_nodes is forbidden; "
                   "write a new versioned node + supersedes edge"),
        ("DELETE", "append-only invariant: DELETE on memory_nodes is forbidden"),
    ):
        conn.execute(
            f"""
            CREATE TRIGGER trg_memory_nodes_no_{action.lower()}
            BEFORE {action} ON memory_nodes
            BEGIN
                SELECT RAISE(ABORT, '{msg}');
            END
            """
        )

    # FTS5 virtual table for BM25 recall. The trigger pair keeps it in
    # sync with INSERTs (UPDATE/DELETE blocked above, so no DELETE trigger
    # is needed).
    conn.execute(
        """
        CREATE VIRTUAL TABLE memory_node_fts USING fts5(
            id UNINDEXED, title, body,
            tokenize = 'porter ascii'
        )
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_memory_nodes_fts_insert
        AFTER INSERT ON memory_nodes
        BEGIN
            INSERT INTO memory_node_fts(id, title, body)
            VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
        END
        """
    )

    # Append-only recall event log.
    conn.execute(
        """
        CREATE TABLE memory_recall_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recall_id TEXT NOT NULL UNIQUE,
            query TEXT NOT NULL,
            strategies_used TEXT NOT NULL,        -- JSON array
            node_ids_returned TEXT NOT NULL,      -- JSON array; top-k order
            context_json TEXT NOT NULL DEFAULT '{}',
            limit_k INTEGER NOT NULL,
            as_of TEXT,
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT
        )
        """
    )
    conn.execute("CREATE INDEX idx_memory_recall_events_actor "
                 "ON memory_recall_events(actor_id, created_at)")

    for action, msg in (
        ("UPDATE", "append-only invariant: UPDATE on memory_recall_events is "
                   "forbidden"),
        ("DELETE", "append-only invariant: DELETE on memory_recall_events is "
                   "forbidden"),
    ):
        conn.execute(
            f"""
            CREATE TRIGGER trg_memory_recall_events_no_{action.lower()}
            BEFORE {action} ON memory_recall_events
            BEGIN
                SELECT RAISE(ABORT, '{msg}');
            END
            """
        )

    # Rebuildable projection (no triggers — projection rebuild uses
    # DELETE + bulk INSERT inside one transaction per persistence.md §7).
    conn.execute(
        """
        CREATE TABLE memory_node_stats (
            node_id TEXT PRIMARY KEY REFERENCES memory_nodes(id),
            recall_count INTEGER NOT NULL DEFAULT 0,
            last_recalled_at TEXT
        )
        """
    )
