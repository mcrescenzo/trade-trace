"""Polymorphic edge endpoint validation/audit coverage for trade-trace-amc."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from trade_trace.mcp_server import mcp_call
from trade_trace.storage import apply_pending_migrations, find_orphan_edges, open_database
from trade_trace.storage.paths import db_path


def _db(tmp_path: Path):
    db = open_database(db_path(tmp_path / "home"))
    apply_pending_migrations(db.connection)
    return db


def _seed_minimal(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        INSERT INTO venues(id, name, kind, created_at, actor_id)
            VALUES ('v_1', 'manual', 'manual', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
            VALUES ('i_1', 'v_1', 'Test', 'prediction_market', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO theses(id, instrument_id, side, body, created_at, actor_id)
            VALUES ('t_1', 'i_1', 'yes', 'thesis body', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO sources(id, kind, stance, created_at, actor_id)
            VALUES ('s_1', 'note', 'supports', '2026-05-18T14:00:00Z', 'agent:default');
        """
    )


def test_orphan_edge_audit_reports_direct_sql_missing_endpoint(tmp_path: Path):
    """Direct SQL/historical orphans remain insertable but auditable.

    Policy note: this bead intentionally does not add polymorphic DB triggers;
    write-tool validation is lower blast radius, while this read-only audit
    surfaces existing bad rows without migration or deletion.
    """

    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        db.connection.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
            "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "e_orphan", "source", "s_missing", "thesis", "t_1", "supports",
                "2026-05-18T14:01:00Z", "agent:default",
            ),
        )

        rows = find_orphan_edges(db.connection)

        assert rows == [
            {
                "edge_id": "e_orphan",
                "endpoint_side": "source",
                "endpoint_kind": "source",
                "endpoint_id": "s_missing",
                "source_kind": "source",
                "source_id": "s_missing",
                "target_kind": "thesis",
                "target_id": "t_1",
                "edge_type": "supports",
                "created_at": "2026-05-18T14:01:00Z",
                "actor_id": "agent:default",
            }
        ]
    finally:
        db.close()


def test_orphan_edge_audit_ignores_valid_edge(tmp_path: Path):
    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        db.connection.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
            "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "e_valid", "source", "s_1", "thesis", "t_1", "supports",
                "2026-05-18T14:01:00Z", "agent:default",
            ),
        )

        assert find_orphan_edges(db.connection) == []
    finally:
        db.close()


def test_public_write_tool_rejects_missing_edge_endpoint(tmp_path: Path):
    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}).ok
    source_env = mcp_call(
        "memory.retain",
        {"home": str(home), "node_type": "observation", "body": "source node"},
    )
    assert source_env.ok, source_env
    source = source_env.data["id"]

    env = mcp_call(
        "memory.link",
        {
            "home": str(home),
            "source_kind": "memory_node",
            "source_id": source,
            "target_kind": "thesis",
            "target_id": "t_missing",
            "edge_type": "about",
        },
    )

    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details == {"entity_kind": "thesis", "target_id": "t_missing"}


def test_public_write_tool_valid_edge_still_works(tmp_path: Path):
    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}).ok
    a_env = mcp_call(
        "memory.retain",
        {"home": str(home), "node_type": "observation", "body": "source node"},
    )
    assert a_env.ok, a_env
    a = a_env.data["id"]
    b_env = mcp_call(
        "memory.retain",
        {"home": str(home), "node_type": "observation", "body": "target node"},
    )
    assert b_env.ok, b_env
    b = b_env.data["id"]

    env = mcp_call(
        "memory.link",
        {
            "home": str(home),
            "source_kind": "memory_node",
            "source_id": a,
            "target_kind": "memory_node",
            "target_id": b,
            "edge_type": "about",
        },
    )

    assert env.ok, env
    assert env.data["source_id"] == a
    assert env.data["target_id"] == b
