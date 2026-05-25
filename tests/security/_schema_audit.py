"""Shared schema-audit helpers per trade-trace-hiiv (SIMP-019).

Two security tests independently walked `sqlite_master` + `PRAGMA
table_info(...)` to enumerate every column of every user table.
The walks were nearly identical; this module centralizes them so a
new test only adds the assertion, not the iteration.

The helpers stay deliberately small — security assertions live in the
calling test and are visible to the reader; this module is only the
iteration.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator


def all_user_table_names(conn: sqlite3.Connection) -> list[str]:
    """Return every non-`sqlite_*` table name from `sqlite_master`."""

    return [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name ASC"
        ).fetchall()
    ]


def iter_table_columns(
    conn: sqlite3.Connection,
) -> Iterator[tuple[str, str]]:
    """Yield `(table, column)` for every user table's every column."""

    for table in all_user_table_names(conn):
        for col_row in conn.execute(f"PRAGMA table_info({table})").fetchall():
            yield table, col_row[1]
