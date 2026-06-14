"""Migration 035_memory_recall_events_filter_indexes.

Add composite indexes covering the recall-receipts filter paths on
`memory_recall_events` (bead trade-trace-yt45).

`_load_recall_events` (src/trade_trace/reports/recall_receipts.py)
builds a filtered, time-ordered scan:

    SELECT ... FROM memory_recall_events
    WHERE <one or more of run_id/agent_id/model_id/environment/recall_id = ?>
      [AND created_at <= ?]   -- optional as_of bound
    ORDER BY created_at ASC, recall_id ASC
    LIMIT ?

Migration 006 ships only `idx_memory_recall_events_actor
(actor_id, created_at)`. A filter on `run_id` or `agent_id` — the two
dominant attribution dimensions for a trading agent (per-run and
per-agent recall audits) — has no usable index, so SQLite full-scans
`memory_recall_events` (which grows by one row on every `memory.recall`
call), applies the equality as a residual predicate, and runs a
transient sort to satisfy the `created_at ASC` order.

Fix: two composite indexes, each leading with the equality column and
trailing with `created_at` so the filter+sort is satisfied by a single
index range walk:

    CREATE INDEX idx_memory_recall_events_run
        ON memory_recall_events(run_id, created_at)
    CREATE INDEX idx_memory_recall_events_agent
        ON memory_recall_events(agent_id, created_at)

The leading column lets SQLite seek to the requested run/agent
partition; the `created_at` column lets it walk that partition already
ordered (resolving the optional `as_of` `<=` as an index range and
satisfying the `ORDER BY created_at ASC` with no sort pass). The
`model_id` / `environment` filters remain rarer secondary dimensions
typically combined with run/agent, so they are intentionally not given
their own indexes here (keeping write/storage cost minimal); SQLite
resolves them as residual predicates inside the run/agent seek.

Index-only change: no table, column, or trigger DDL. `PRAGMA
table_info(memory_recall_events)` is unchanged (so `EXPECTED_INFO_HASH`
in `tests/integration/test_migrations_schema_hash.py` is unaffected),
but the two new `sqlite_master` rows bump `EXPECTED_DDL_HASH`. Additive,
non-destructive, forward-only — a fresh migration file rather than an
edit to the shipped m006 migration.
"""

from __future__ import annotations

import sqlite3


def _migration_035_memory_recall_events_filter_indexes(
    conn: sqlite3.Connection,
) -> None:
    """Add run_id / agent_id composite indexes for recall-receipts filters."""

    conn.execute(
        "CREATE INDEX idx_memory_recall_events_run "
        "ON memory_recall_events(run_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX idx_memory_recall_events_agent "
        "ON memory_recall_events(agent_id, created_at)"
    )


__all__ = ["_migration_035_memory_recall_events_filter_indexes"]
