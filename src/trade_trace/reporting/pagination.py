"""Cursor-based pagination for read-only reporting helpers.

The contract:

    paginate_query(conn, sql=..., order_by=..., cursor=..., limit=...)

returns a `Page` with a list of rows and a `next_cursor` string
(opaque, base64url-encoded JSON). The caller passes `next_cursor`
back as `cursor` on the next request; when no more rows remain
`next_cursor` is `None`.

Why cursor and not offset:

- Offset pagination scans every prior row on every page. On large
  report targets (~100k events) the final page
  would cost as much as the first.
- A cursor binds the next page to "rows where the ordering column
  is > (or <) the last value seen" — a single index seek.

The cursor is stable across requests as long as the underlying
sort key is monotone. For the journal's `events.id` (autoincrement
INTEGER PRIMARY KEY) that holds by construction.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

DEFAULT_LIMIT = 50
MAX_LIMIT = 500
"""Hard ceiling on rows returned per page. Reporting consumers should
request smaller pages; the helper clamps any caller that asks for more."""


class PaginationError(ValueError):
    """Raised when a cursor is malformed or references a column the
    query doesn't include."""


@dataclass
class Page:
    rows: list[Any]
    next_cursor: str | None = None
    limit: int = DEFAULT_LIMIT
    meta: dict[str, Any] = field(default_factory=dict)


def _encode_cursor(value: Any) -> str:
    payload = json.dumps({"after": value}, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> Any:
    if not cursor:
        raise PaginationError("cursor must be non-empty when provided")
    # base64url-decode tolerates missing padding.
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding)
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PaginationError(f"invalid cursor: {exc}") from exc
    if not isinstance(payload, dict) or "after" not in payload:
        raise PaginationError("cursor payload missing 'after' field")
    return payload["after"]


def _split_order_by(order_by: str) -> tuple[str, str]:
    """Return `(column, direction)` from an `order_by` clause like
    `"id"` or `"id DESC"`. Multi-column order is intentionally not
    supported — cursor pagination over a composite key needs a
    composite cursor and should use a dedicated helper when required."""

    parts = order_by.strip().split()
    if len(parts) == 1:
        return parts[0], "ASC"
    if len(parts) == 2 and parts[1].upper() in ("ASC", "DESC"):
        return parts[0], parts[1].upper()
    raise PaginationError(
        f"order_by must be 'column' or 'column ASC|DESC'; got {order_by!r}",
    )


def paginate_query(
    conn: sqlite3.Connection,
    *,
    sql: str,
    order_by: str,
    cursor: str | None,
    limit: int = DEFAULT_LIMIT,
) -> Page:
    """Run `sql` with cursor-based pagination.

    `sql` must be a `SELECT` over a single primary table; the
    pagination layer appends `WHERE <order_column> ? <last_seen>`,
    `ORDER BY <order_by>`, and `LIMIT <limit+1>`. The extra row
    decides whether to emit a `next_cursor`.

    The function is sqlite-only — it formats the WHERE clause using
    a parameterized query, but the `order_by` column is interpolated
    verbatim (since SQL placeholders can't replace identifiers). The
    caller is responsible for passing a column they trust; the
    Callers should pass constants from trusted code.
    """

    column, direction = _split_order_by(order_by)
    clamped_limit = max(1, min(int(limit), MAX_LIMIT))

    where = ""
    params: tuple[Any, ...] = ()
    if cursor is not None:
        after = _decode_cursor(cursor)
        op = ">" if direction == "ASC" else "<"
        where = f" WHERE {column} {op} ?"
        params = (after,)

    paged_sql = f"{sql}{where} ORDER BY {column} {direction} LIMIT ?"
    rows = list(conn.execute(paged_sql, params + (clamped_limit + 1,)))

    next_cursor: str | None = None
    if len(rows) > clamped_limit:
        rows = rows[:clamped_limit]
        last = rows[-1]
        # Cursor key is the first column of the row, which by
        # convention is the order-by column. Reporting queries using
        # this helper are written with the order column first to make
        # this invariant trivial to enforce.
        next_cursor = _encode_cursor(last[0])
    return Page(rows=rows, next_cursor=next_cursor, limit=clamped_limit)


def paginate_created_at_id_query(
    conn: sqlite3.Connection,
    *,
    sql: str,
    cursor: str | None,
    limit: int = DEFAULT_LIMIT,
    params: tuple[Any, ...] = (),
    id_index: int = 0,
    created_at_index: int = -1,
) -> Page:
    """Run a newest-first `(created_at, id)` keyset page.

    Several report tables select `id` first for display but sort by
    `created_at`. A simple cursor over the first selected column would
    repeat or skip rows. This helper encodes the true order key plus an
    id tie-breaker so duplicate timestamps walk correctly.
    """

    clamped_limit = max(1, min(int(limit), MAX_LIMIT))
    where = ""
    page_params: list[Any] = list(params)
    if cursor is not None:
        after = _decode_cursor(cursor)
        if not isinstance(after, list) or len(after) != 2:
            raise PaginationError(
                "created_at cursor payload must contain [created_at, id]",
            )
        after_created_at, after_id = after
        connector = " AND " if " WHERE " in sql.upper() else " WHERE "
        where = (
            connector
            + "(created_at < ? OR (created_at = ? AND id < ?))"
        )
        page_params.extend([after_created_at, after_created_at, after_id])

    paged_sql = f"{sql}{where} ORDER BY created_at DESC, id DESC LIMIT ?"
    rows = list(conn.execute(paged_sql, tuple(page_params) + (clamped_limit + 1,)))

    next_cursor: str | None = None
    if len(rows) > clamped_limit:
        rows = rows[:clamped_limit]
        last = rows[-1]
        next_cursor = _encode_cursor([last[created_at_index], last[id_index]])
    return Page(rows=rows, next_cursor=next_cursor, limit=clamped_limit)
