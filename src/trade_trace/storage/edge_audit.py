"""Read-only integrity audit helpers for polymorphic graph edges.

The `edges` table stores polymorphic endpoints as
`source_kind/source_id/target_kind/target_id`. SQLite cannot express a single
foreign key across multiple endpoint tables, and broad triggers would make
future endpoint kinds/backfills risky. Write tools validate the endpoint rows
they create; this module audits historical/direct SQL rows without mutating
or deleting them.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Final, Literal

EndpointSide = Literal["source", "target"]

EDGE_ENDPOINT_TABLES: Final[dict[str, str]] = {
    "decision": "decisions",
    "thesis": "theses",
    "forecast": "forecasts",
    "outcome": "outcomes",
    "snapshot": "snapshots",
    "instrument": "instruments",
    "venue": "venues",
    "source": "sources",
    "memory_node": "memory_nodes",
    "signal": "signals",
    "strategy": "strategies",
}
"""Endpoint kinds with concrete backing tables in the current schema.

`review` and `playbook_version` remain enum-valid but are intentionally absent:
they do not have backing tables in this schema, so an audit cannot prove their
row existence without creating false positives.
"""


def _orphan_select(side: EndpointSide, kind: str, table: str) -> tuple[str, tuple[str, str]]:
    kind_col = f"{side}_kind"
    id_col = f"{side}_id"
    sql = (
        "SELECT e.id AS edge_id, ? AS endpoint_side, "
        f"e.{kind_col} AS endpoint_kind, e.{id_col} AS endpoint_id, "
        "e.source_kind, e.source_id, e.target_kind, e.target_id, "
        "e.edge_type, e.created_at, e.actor_id "
        "FROM edges e "
        f"LEFT JOIN {table} endpoint ON endpoint.id = e.{id_col} "
        f"WHERE e.{kind_col} = ? AND endpoint.id IS NULL"
    )
    return sql, (side, kind)


def find_orphan_edges(conn: sqlite3.Connection, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Return edge endpoints whose kind has a table but whose id is missing.

    The query is read-only and intentionally reports one row per missing
    endpoint side. A single edge with both source and target missing will appear
    twice so repair tooling can see exactly which endpoint(s) are bad.
    Historical or direct-SQL orphans are surfaced; this helper does not migrate,
    rewrite, or delete them.
    """

    if limit is not None and limit < 1:
        raise ValueError("limit must be >= 1")

    selects: list[str] = []
    params: list[Any] = []
    for side in ("source", "target"):
        for kind, table in EDGE_ENDPOINT_TABLES.items():
            sql, sql_params = _orphan_select(side, kind, table)
            selects.append(sql)
            params.extend(sql_params)

    query = " UNION ALL ".join(selects) + " ORDER BY edge_id, endpoint_side"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    old_row_factory = conn.row_factory
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.row_factory = old_row_factory
    return [dict(row) for row in rows]
