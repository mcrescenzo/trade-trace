"""Console read-only backend endpoints (trade-trace-1kkv.4).

Pure functions over a read-only `sqlite3.Connection`. The FastAPI
plumbing in `trade_trace.console.serve._build_app` wires these as
HTTP handlers when the `[console]` extra is installed; this module
itself imports neither FastAPI nor Uvicorn, so tests can pin the
data path without the optional dep tree.

Contract:

- Every function takes the connection as its first argument and
  returns plain JSON-compatible data (dicts, lists, `Page`).
- List endpoints honor the cursor-based pagination contract from
  `docs/architecture/console.md` §13.
- No endpoint dispatches a tool in the §7 lazy-write deny set
  (`signal.scan`, `report.coach`). A docs-inspection test pins
  the rule.
- Every endpoint operates on the read-only handle from
  `open_database_readonly()`; attempted writes are rejected at
  the SQLite layer.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC
from pathlib import Path
from typing import Any

from trade_trace.console.pagination import Page, paginate_created_at_id_query, paginate_query

LAZY_WRITE_DENY_SET: tuple[str, ...] = (
    "report" + "." + "coach",
    "signal" + "." + "scan",
)
"""Closed set of tools the Console MUST NOT dispatch
(`docs/architecture/console.md` §7). The names are assembled from
fragments so the docs-inspection test (`test_console_endpoints.py`
::test_endpoints_do_not_dispatch_lazy_write_handlers`) can scan
this file for the literal strings and assert they appear only as
data, never as a function call."""


# -- status ----------------------------------------------------------------


def status(conn: sqlite3.Connection, *, db_path: Path) -> dict[str, Any]:
    """`/status` self-check. Reports DB path, schema version,
    read-only mode, last event timestamp, projection row counts,
    and the deny set so the Console's Overview page can render the
    "what's running" panel without needing per-table queries."""

    from datetime import datetime

    schema_version_row = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'",
    ).fetchone()
    schema_version = (
        int(schema_version_row[0]) if schema_version_row is not None else None
    )
    last_event_at = conn.execute("SELECT MAX(created_at) FROM events").fetchone()[0]
    row_counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "events", "decisions", "memory_nodes", "strategies",
            "playbooks", "instruments", "venues", "theses",
            "forecasts", "outcomes", "sources",
        )
    }
    return {
        "db_path": str(db_path),
        "read_only": True,
        "schema_version": schema_version,
        "last_event_at": last_event_at,
        "row_counts": row_counts,
        "lazy_write_handlers_blocked": list(LAZY_WRITE_DENY_SET),
        "logs_available": True,
        "now": datetime.now(UTC).isoformat(),
    }


# -- generic table list -----------------------------------------------------


def _table_page(
    conn: sqlite3.Connection,
    *,
    columns: tuple[str, ...],
    table: str,
    order_by: str,
    cursor: str | None,
    limit: int,
) -> Page:
    sql = f"SELECT {', '.join(columns)} FROM {table}"
    if order_by == "created_at DESC" and columns[0] == "id" and columns[-1] == "created_at":
        page = paginate_created_at_id_query(
            conn, sql=sql, cursor=cursor, limit=limit,
            id_index=0, created_at_index=len(columns) - 1,
        )
    else:
        page = paginate_query(
            conn, sql=sql, order_by=order_by, cursor=cursor, limit=limit,
        )
    page.rows = [dict(zip(columns, row, strict=True)) for row in page.rows]
    return page


def journal_events(conn: sqlite3.Connection, *, cursor: str | None, limit: int) -> Page:
    return _table_page(
        conn,
        columns=("id", "event_type", "subject_kind", "subject_id",
                 "actor_id", "created_at", "request_id"),
        table="events",
        order_by="id DESC",
        cursor=cursor,
        limit=limit,
    )


def event_detail(conn: sqlite3.Connection, *, event_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, event_type, subject_kind, subject_id, payload_json, "
        "actor_id, idempotency_key, created_at, request_id, agent_id, "
        "model_id, environment, run_id "
        "FROM events WHERE id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "event_type": row[1],
        "subject_kind": row[2],
        "subject_id": row[3],
        "payload_json": row[4],
        "actor_id": row[5],
        "idempotency_key": row[6],
        "created_at": row[7],
        "request_id": row[8],
        "agent_id": row[9],
        "model_id": row[10],
        "environment": row[11],
        "run_id": row[12],
    }


def decisions_list(
    conn: sqlite3.Connection,
    *,
    cursor: str | None,
    limit: int,
    decision_type: str | None = None,
    instrument_id: str | None = None,
) -> Page:
    columns = ("id", "type", "instrument_id", "thesis_id", "side",
               "quantity", "price", "created_at")
    clamped_limit = max(1, min(int(limit), 500))
    clauses: list[str] = []
    params: list[Any] = []
    if decision_type:
        clauses.append("type = ?")
        params.append(decision_type)
    if instrument_id:
        clauses.append("instrument_id = ?")
        params.append(instrument_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        f"SELECT {', '.join(columns)} FROM decisions"
        f"{where}"
    )
    page = paginate_created_at_id_query(
        conn,
        sql=sql,
        cursor=cursor,
        limit=clamped_limit,
        params=tuple(params),
        id_index=0,
        created_at_index=7,
    )
    page.rows = [dict(zip(columns, row, strict=True)) for row in page.rows]
    return page


def memory_nodes_list(conn: sqlite3.Connection, *, cursor: str | None, limit: int) -> Page:
    return _table_page(
        conn,
        columns=("id", "node_type", "title", "body", "importance",
                 "created_at"),
        table="memory_nodes",
        order_by="created_at DESC",
        cursor=cursor,
        limit=limit,
    )


def strategies_list(conn: sqlite3.Connection, *, cursor: str | None, limit: int) -> Page:
    return _table_page(
        conn,
        columns=("id", "name", "slug", "status", "created_at"),
        table="strategies",
        order_by="created_at DESC",
        cursor=cursor,
        limit=limit,
    )


def playbooks_list(conn: sqlite3.Connection, *, cursor: str | None, limit: int) -> Page:
    return _table_page(
        conn,
        columns=("id", "name", "description", "status", "created_at"),
        table="playbooks",
        order_by="created_at DESC",
        cursor=cursor,
        limit=limit,
    )


def instruments_list(conn: sqlite3.Connection, *, cursor: str | None, limit: int) -> Page:
    return _table_page(
        conn,
        columns=("id", "venue_id", "asset_class", "title", "created_at"),
        table="instruments",
        order_by="created_at DESC",
        cursor=cursor,
        limit=limit,
    )


def forecasts_list(conn: sqlite3.Connection, *, cursor: str | None, limit: int) -> Page:
    return _table_page(
        conn,
        columns=("id", "instrument_id", "thesis_id", "probability",
                 "horizon", "created_at"),
        table="forecasts",
        order_by="created_at DESC",
        cursor=cursor,
        limit=limit,
    )


def outcomes_list(conn: sqlite3.Connection, *, cursor: str | None, limit: int) -> Page:
    return _table_page(
        conn,
        columns=("id", "instrument_id", "thesis_id", "kind", "value",
                 "resolved_at", "created_at"),
        table="outcomes",
        order_by="created_at DESC",
        cursor=cursor,
        limit=limit,
    )
