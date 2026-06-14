"""Migration 032_positions_opened_at_index.

Add a covering keyset index for the `list_positions` page scan
(bead trade-trace-b5hg).

`list_positions` (src/trade_trace/reporting/position_rows.py) pages
through positions via `paginate_created_at_id_query`, which emits:

    ... ORDER BY p.opened_at DESC, p.id DESC LIMIT ?

with a keyset cursor predicate

    (p.opened_at < ? OR (p.opened_at = ? AND p.id < ?))

and optional `opened_from` / `opened_to` range filters
(`p.opened_at >= ?`, `p.opened_at <= ?`).

Migration 003 ships only `idx_positions_instr` (instrument_id) and
`idx_positions_status` (status) — neither covers `opened_at`. So every
paginated call does a full scan of `positions` followed by a transient
sort pass to satisfy the `(opened_at DESC, id DESC)` order, and the
range filters are unindexed residual predicates. On a growing positions
projection that is O(n log n) per page.

Fix: a composite index matching the keyset order exactly:

    CREATE INDEX idx_positions_opened_at
        ON positions(opened_at DESC, id DESC)

`opened_at DESC, id DESC` lets SQLite walk the index in the requested
order (no sort pass), seek directly to the cursor position, and resolve
the `opened_from`/`opened_to` range as an index range on the leading
column. The `id` tie-breaker keeps duplicate-timestamp pages stable.

Index-only change: no table, column, or trigger DDL. `PRAGMA
table_info(positions)` is unchanged (so `EXPECTED_INFO_HASH` in
`tests/integration/test_migrations_schema_hash.py` is unaffected), but
the new `sqlite_master` row bumps `EXPECTED_DDL_HASH`. Additive,
non-destructive, forward-only.
"""

from __future__ import annotations

import sqlite3


def _migration_032_positions_opened_at_index(conn: sqlite3.Connection) -> None:
    """Add the covering keyset index for the list_positions page scan."""

    conn.execute(
        "CREATE INDEX idx_positions_opened_at "
        "ON positions(opened_at DESC, id DESC)"
    )


__all__ = ["_migration_032_positions_opened_at_index"]
