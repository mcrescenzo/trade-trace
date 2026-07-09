"""Migration 015_pm_inline_sources_transition.

Additive inline-source transition checkpoint.

This migration deliberately keeps the legacy ``sources`` table and source edge
rows intact.  It only normalizes the canonical metadata containers so readers
can rely on a ``metadata_json.sources`` array being present on forecasts,
decisions, and memory nodes while destructive source-edge collapse is deferred.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

_APPEND_ONLY_UPDATE_TRIGGERS: dict[str, str] = {
    "forecasts": "append-only invariant: UPDATE on forecasts is forbidden; use a supersedes edge to record a correction (persistence.md §8)",
    "decisions": "append-only invariant: UPDATE on decisions is forbidden; use a supersedes edge to record a correction (persistence.md §8)",
    "memory_nodes": "append-only invariant: UPDATE on memory_nodes is forbidden; write a new versioned node + supersedes edge",
}


def _metadata_with_sources_array(raw: str | None) -> str:
    try:
        parsed: Any = json.loads(raw or "{}")
    except Exception:  # noqa: BLE001 - malformed historical metadata is normalized to an empty object
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    if not isinstance(parsed.get("sources"), list):
        parsed["sources"] = []
    return json.dumps(parsed, sort_keys=True)


def _normalize_table(conn: sqlite3.Connection, table: str) -> None:
    rows = conn.execute(f"SELECT id, metadata_json FROM {table}").fetchall()
    for row_id, metadata_json in rows:
        normalized = _metadata_with_sources_array(metadata_json)
        if normalized != metadata_json:
            conn.execute(
                f"UPDATE {table} SET metadata_json = ? WHERE id = ?",
                (normalized, row_id),
            )


def _migration_015_pm_inline_sources_transition(conn: sqlite3.Connection) -> None:
    """Ensure canonical metadata containers have inline source arrays."""

    for table in _APPEND_ONLY_UPDATE_TRIGGERS:
        conn.execute(f"DROP TRIGGER trg_{table}_no_update")
    try:
        for table in ("forecasts", "decisions", "memory_nodes"):
            _normalize_table(conn, table)
    finally:
        for table, message in _APPEND_ONLY_UPDATE_TRIGGERS.items():
            conn.execute(
                f"""
                CREATE TRIGGER trg_{table}_no_update
                BEFORE UPDATE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, '{message}');
                END
                """
            )
