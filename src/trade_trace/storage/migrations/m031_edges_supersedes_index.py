"""Migration 031_edges_supersedes_index.

Add a partial covering index for the supersedes edge scan in
`_superseded_node_ids` (bead trade-trace-17k9).

`_superseded_node_ids` (src/trade_trace/tools/memory.py) runs on every
memory recall to find nodes that have been superseded:

    SELECT DISTINCT target_id FROM edges
    WHERE source_kind = 'memory_node'
      AND target_kind = 'memory_node'
      AND edge_type = 'supersedes'
      [AND created_at <= ?]   -- only when an as_of point-in-time is given

Migration 003 ships three edge indexes — `idx_edges_source`
(source_kind, source_id), `idx_edges_target` (target_kind, target_id),
and `idx_edges_type` (edge_type). None of them cover this
triple-predicate equality. SQLite picks `idx_edges_target` to seek on
`target_kind='memory_node'`, then scans every memory_node-*targeted*
edge row-by-row testing `source_kind` and `edge_type`. On a graph with
many cross-type edges into memory_nodes (`about`, `supports`,
`contradicts`, `derived_from`, …) that degrades to a full scan of the
memory_node target partition on every recall.

Fix: a partial index keyed on `edge_type='supersedes'`. Because the
partition predicate pins `edge_type`, the index body only needs the
remaining equality columns plus the optional range column and the
projected column:

    CREATE INDEX idx_edges_supersedes
        ON edges(source_kind, target_kind, created_at, target_id)
        WHERE edge_type = 'supersedes'

`source_kind, target_kind` give a tight equality seek; `created_at`
lets the optional `as_of` form resolve the `<=` as an index range
inside that seek; `target_id` makes the index covering for the
`DISTINCT target_id` projection so the scan never touches the table.
The index is small — it only holds supersedes edges, a tiny fraction
of all edges — so the write/storage cost is negligible.

Index-only change: no table, column, or trigger DDL. `PRAGMA
table_info` is unchanged (so `EXPECTED_INFO_HASH` in
`tests/integration/test_migrations_schema_hash.py` is unaffected), but
the new `sqlite_master` row bumps `EXPECTED_DDL_HASH`.
"""

from __future__ import annotations

import sqlite3


def _migration_031_edges_supersedes_index(conn: sqlite3.Connection) -> None:
    """Add the partial covering index for the supersedes edge scan."""

    conn.execute(
        "CREATE INDEX idx_edges_supersedes "
        "ON edges(source_kind, target_kind, created_at, target_id) "
        "WHERE edge_type = 'supersedes'"
    )


__all__ = ["_migration_031_edges_supersedes_index"]
