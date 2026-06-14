"""Migration 033_decisions_type_created_at_index.

Add a composite index covering the `list_trades` hot path
(bead trade-trace-ynam).

`list_trades` (src/trade_trace/reporting/trade_rows.py) fires on every
trade-listing call with no instrument or strategy filter:

    ... FROM decisions d ...
    WHERE d.type IN ('actual_enter','actual_exit','paper_enter',
                     'paper_exit','add','reduce')
      [AND d.created_at >= ?]   -- optional opened_from bound
      [AND d.created_at <= ?]   -- optional opened_to bound
    ORDER BY d.created_at DESC, d.id DESC LIMIT ?

with the keyset cursor predicate

    (d.created_at < ? OR (d.created_at = ? AND d.id < ?))

The six `type` values are exactly `TRADING_DECISION_TYPES`
(src/trade_trace/reporting/trade_rows.py).

Migration 003 ships only `idx_decisions_instr` (instrument_id),
`idx_decisions_thesis` (thesis_id), and `idx_decisions_strategy`
(strategy_id) — none cover `type` or `created_at`. So a `list_trades`
call with no instrument/strategy filter has no usable index: SQLite
full-scans `decisions`, applies the `type IN (...)` filter as a residual
predicate, and runs a transient sort pass to satisfy the
`(created_at DESC, id DESC)` order. The optional `opened_from` /
`opened_to` bounds are likewise unindexed residual predicates. On a
growing decisions table (every session writes at least one decision
row) that is O(n log n) per page.

Fix: a composite index matching the filter+sort exactly:

    CREATE INDEX idx_decisions_type_created_at
        ON decisions(type, created_at DESC)

The leading `type` column lets SQLite seek directly to each of the six
trading-type partitions for the `type IN (...)` filter; the
`created_at DESC` column lets it walk each partition in the requested
order, resolve the `opened_from`/`opened_to` bounds as an index range,
and seek to the keyset cursor position — instead of scanning every
decision row and sorting. The `id` keyset tie-breaker remains a residual
within the (typically tiny) duplicate-timestamp group.

Index-only change: no table, column, or trigger DDL. `PRAGMA
table_info(decisions)` is unchanged (so `EXPECTED_INFO_HASH` in
`tests/integration/test_migrations_schema_hash.py` is unaffected), but
the new `sqlite_master` row bumps `EXPECTED_DDL_HASH`. Additive,
non-destructive, forward-only.
"""

from __future__ import annotations

import sqlite3


def _migration_033_decisions_type_created_at_index(conn: sqlite3.Connection) -> None:
    """Add the composite index covering the list_trades hot path."""

    conn.execute(
        "CREATE INDEX idx_decisions_type_created_at "
        "ON decisions(type, created_at DESC)"
    )


__all__ = ["_migration_033_decisions_type_created_at_index"]
