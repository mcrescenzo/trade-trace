"""Migration 034_edges_target_type_index.

Add a covering index for the `source_count` correlated subquery in
`list_trades` (bead trade-trace-yt45).

`list_trades` (src/trade_trace/reporting/trade_rows.py) attaches a
per-decision source count via a correlated subquery:

    (SELECT COUNT(*) FROM edges e
       WHERE e.target_kind = 'decision'
         AND e.target_id = d.id
         AND (
             e.edge_type = 'cites'
             OR (
                 e.source_kind = 'source'
                 AND e.edge_type IN ('about', 'supports', 'contradicts')
             )
         )) AS source_count

Migration 003 ships `idx_edges_target (target_kind, target_id)`. SQLite
uses it to seek on `target_kind='decision' AND target_id=d.id`, but the
index body stops at `target_id`, so the `edge_type`/`source_kind`
predicate is resolved by fetching each matching edge row from the table
(a post-seek row scan inside the per-decision subquery). On a trade list
with many decisions, each carrying several cited edges, that is one
table probe per qualifying edge per listed trade.

Fix: a covering index that carries `edge_type` after the seek columns:

    CREATE INDEX idx_edges_target_type
        ON edges(target_kind, target_id, edge_type)

The leading `target_kind, target_id` give the same equality seek as the
existing index; the trailing `edge_type` lets SQLite resolve the
`edge_type = 'cites' OR edge_type IN ('about','supports','contradicts')`
branch directly from the index entries, so the COUNT never re-fetches
those rows from the table. (The `source_kind = 'source'` half of the
OR still needs the row for that branch, but the dominant `cites` /
stance edges are covered.) The existing `idx_edges_target` is left in
place — it remains the better choice for queries that project columns
this index does not carry.

Index-only change: no table, column, or trigger DDL. `PRAGMA
table_info(edges)` is unchanged (so `EXPECTED_INFO_HASH` in
`tests/integration/test_migrations_schema_hash.py` is unaffected), but
the new `sqlite_master` row bumps `EXPECTED_DDL_HASH`. Additive,
non-destructive, forward-only — a fresh migration file rather than an
edit to the shipped m003 migration.
"""

from __future__ import annotations

import sqlite3


def _migration_034_edges_target_type_index(conn: sqlite3.Connection) -> None:
    """Add the covering index for the list_trades source_count subquery."""

    conn.execute(
        "CREATE INDEX idx_edges_target_type "
        "ON edges(target_kind, target_id, edge_type)"
    )


__all__ = ["_migration_034_edges_target_type_index"]
