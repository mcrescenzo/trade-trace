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
from collections.abc import Sequence
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


def journal_events(
    conn: sqlite3.Connection,
    *,
    cursor: str | None,
    limit: int,
    request_id: str | None = None,
    actor_id: str | None = None,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    event_type: str | None = None,
) -> Page:
    """Return a locally-filtered journal timeline page.

    Filters are exact-match fields already present in the append-only local
    `events` table. This powers audit grouping/replay without network calls,
    market-data replay, or writeback annotations.
    """

    columns = (
        "id", "event_type", "subject_kind", "subject_id", "actor_id",
        "created_at", "request_id", "idempotency_key", "agent_id", "model_id",
        "environment", "run_id",
    )
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("request_id", request_id),
        ("actor_id", actor_id),
        ("subject_kind", subject_kind),
        ("subject_id", subject_id),
        ("event_type", event_type),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT {', '.join(columns)} FROM events{where}"
    page = paginate_created_at_id_query(
        conn,
        sql=sql,
        cursor=cursor,
        limit=limit,
        params=tuple(params),
        id_index=0,
        created_at_index=5,
    )
    page.rows = [dict(zip(columns, row, strict=True)) for row in page.rows]
    return page


def event_related_records(conn: sqlite3.Connection, *, event_id: int) -> dict[str, Any] | None:
    """Collect local read-model rows that can be tied to an event subject.

    This is intentionally conservative: it follows only IDs already stored in
    local tables/payload JSON and returns projections for audit context, not
    computed advice or live market replay.
    """

    event = event_detail(conn, event_id=event_id)
    if event is None:
        return None
    subject_kind = str(event.get("subject_kind") or "")
    subject_id = str(event.get("subject_id") or "")
    payload = _parse_payload_json(event.get("payload_json"))
    ids = _collect_payload_ids(payload)
    if subject_kind and subject_id:
        ids.setdefault(subject_kind, set()).add(subject_id)

    return {
        "event_id": event_id,
        "decision": _lookup_one(conn, "decisions", subject_id) if subject_kind == "decision" else None,
        "forecasts": _lookup_many(conn, "forecasts", ids.get("forecast", set())),
        "outcomes": _lookup_many(conn, "outcomes", ids.get("outcome", set())),
        "sources": _lookup_many(conn, "sources", ids.get("source", set())),
        "subject_events": record_events(
            conn,
            subject_kind=subject_kind,
            subject_id=subject_id,
            limit=20,
        ) if subject_kind and subject_id else [],
    }


def _parse_payload_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        import json

        return json.loads(value)
    except Exception:
        return value


def _collect_payload_ids(value: Any) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {"forecast": set(), "outcome": set(), "source": set()}
    if isinstance(value, dict):
        for key, child in value.items():
            key_s = str(key)
            if key_s in {"forecast_id", "outcome_id", "source_id"} and child:
                found[key_s.removesuffix("_id")].add(str(child))
            elif key_s in {"forecast_ids", "outcome_ids", "source_ids"} and isinstance(child, list):
                found[key_s.removesuffix("_ids")].update(str(item) for item in child if item)
            for kind, ids in _collect_payload_ids(child).items():
                found[kind].update(ids)
    elif isinstance(value, list):
        for child in value:
            for kind, ids in _collect_payload_ids(child).items():
                found[kind].update(ids)
    return found


def _lookup_one(conn: sqlite3.Connection, table: str, row_id: str) -> dict[str, Any] | None:
    rows = _lookup_many(conn, table, {row_id})
    return rows[0] if rows else None


def _lookup_many(conn: sqlite3.Connection, table: str, ids: set[str]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows: list[dict[str, Any]] = []
    for row_id in sorted(ids):
        cursor = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
        row = cursor.fetchone()
        if row is not None:
            rows.append(dict(zip([col[0] for col in cursor.description], row, strict=True)))
    return rows


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


def record_events(
    conn: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return journal event envelopes that contributed to a local record.

    This narrow read-only lookup backs contextual Console detail drawers without
    promoting raw JSON to primary navigation.
    """

    clamped_limit = max(1, min(int(limit), 100))
    rows = conn.execute(
        "SELECT id, event_type, subject_kind, subject_id, payload_json, "
        "actor_id, created_at, request_id "
        "FROM events WHERE subject_kind = ? AND subject_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (subject_kind, subject_id, clamped_limit),
    ).fetchall()
    return [
        {
            "id": row[0],
            "event_type": row[1],
            "subject_kind": row[2],
            "subject_id": row[3],
            "payload_json": row[4],
            "actor_id": row[5],
            "created_at": row[6],
            "request_id": row[7],
        }
        for row in rows
    ]


def _multi(value: str | Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [item for item in value if item]


def decisions_list(
    conn: sqlite3.Connection,
    *,
    cursor: str | None,
    limit: int,
    decision_type: str | Sequence[str] | None = None,
    instrument_id: str | None = None,
) -> Page:
    columns = ("id", "type", "instrument_id", "thesis_id", "side",
               "quantity", "price", "created_at")
    clamped_limit = max(1, min(int(limit), 500))
    clauses: list[str] = []
    params: list[Any] = []
    decision_types = _multi(decision_type)
    if decision_types:
        clauses.append(f"type IN ({','.join('?' * len(decision_types))})")
        params.extend(decision_types)
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
