"""Cursor-based pagination contract for the Console
(trade-trace-1kkv.14, see docs/architecture/console.md §13).

The contract is:

    GET /<list>?cursor=<base64>&limit=<n>

with the response carrying `next_cursor` (string, opaque) when more
rows remain, or `null` when the page ended. `limit` defaults to 50
and is clamped to `MAX_LIMIT`. Cursors are stable across requests as
long as the underlying sort key is monotone.
"""

from __future__ import annotations

import sqlite3

import pytest


def _seed(conn: sqlite3.Connection, rows: int) -> None:
    """Build a tiny in-memory table mimicking the journal events
    list shape: a monotone integer id plus a payload."""

    conn.execute("CREATE TABLE events_test(id INTEGER PRIMARY KEY, body TEXT)")
    conn.executemany(
        "INSERT INTO events_test(id, body) VALUES (?, ?)",
        [(i, f"row-{i}") for i in range(1, rows + 1)],
    )
    conn.commit()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    try:
        yield c
    finally:
        c.close()


def test_first_page_with_no_cursor(conn):
    from trade_trace.console.pagination import paginate_query

    _seed(conn, 120)
    page = paginate_query(
        conn,
        sql="SELECT id, body FROM events_test",
        order_by="id",
        cursor=None,
        limit=50,
    )
    assert [r[0] for r in page.rows] == list(range(1, 51))
    assert page.next_cursor is not None
    assert page.limit == 50


def test_next_page_uses_returned_cursor(conn):
    from trade_trace.console.pagination import paginate_query

    _seed(conn, 120)
    page1 = paginate_query(conn, sql="SELECT id, body FROM events_test",
                           order_by="id", cursor=None, limit=50)
    page2 = paginate_query(conn, sql="SELECT id, body FROM events_test",
                           order_by="id", cursor=page1.next_cursor, limit=50)
    assert [r[0] for r in page2.rows] == list(range(51, 101))


def test_final_page_returns_null_cursor(conn):
    from trade_trace.console.pagination import paginate_query

    _seed(conn, 60)
    page1 = paginate_query(conn, sql="SELECT id, body FROM events_test",
                           order_by="id", cursor=None, limit=50)
    page2 = paginate_query(conn, sql="SELECT id, body FROM events_test",
                           order_by="id", cursor=page1.next_cursor, limit=50)
    assert len(page2.rows) == 10
    assert page2.next_cursor is None


def test_limit_is_clamped_to_max_limit(conn):
    from trade_trace.console.pagination import MAX_LIMIT, paginate_query

    _seed(conn, 10_000)
    page = paginate_query(conn, sql="SELECT id, body FROM events_test",
                          order_by="id", cursor=None, limit=10_000)
    assert page.limit == MAX_LIMIT
    assert len(page.rows) == MAX_LIMIT


def test_cursor_format_is_opaque_base64(conn):
    """The cursor MUST be opaque so callers don't bind to the
    internal encoding. The contract is base64url of a small JSON
    object; the test pins that decoded JSON parses cleanly so a
    future revision can't silently switch to a binary blob without
    bumping the contract."""

    import base64
    import json

    from trade_trace.console.pagination import paginate_query

    _seed(conn, 100)
    page = paginate_query(conn, sql="SELECT id, body FROM events_test",
                          order_by="id", cursor=None, limit=10)
    cursor_bytes = base64.urlsafe_b64decode(page.next_cursor + "==")
    decoded = json.loads(cursor_bytes)
    assert "after" in decoded
    assert decoded["after"] == 10


def test_invalid_cursor_raises_validation_error(conn):
    from trade_trace.console.pagination import (
        PaginationError,
        paginate_query,
    )

    _seed(conn, 20)
    with pytest.raises(PaginationError):
        paginate_query(conn, sql="SELECT id, body FROM events_test",
                       order_by="id", cursor="not-a-real-cursor", limit=10)


def test_descending_order_supported(conn):
    from trade_trace.console.pagination import paginate_query

    _seed(conn, 30)
    page = paginate_query(conn, sql="SELECT id, body FROM events_test",
                          order_by="id DESC", cursor=None, limit=10)
    assert [r[0] for r in page.rows] == list(range(30, 20, -1))
    page2 = paginate_query(conn, sql="SELECT id, body FROM events_test",
                           order_by="id DESC", cursor=page.next_cursor, limit=10)
    assert [r[0] for r in page2.rows] == list(range(20, 10, -1))


def test_empty_table_returns_empty_page_and_null_cursor(conn):
    from trade_trace.console.pagination import paginate_query

    _seed(conn, 0)
    page = paginate_query(conn, sql="SELECT id, body FROM events_test",
                          order_by="id", cursor=None, limit=50)
    assert page.rows == []
    assert page.next_cursor is None
