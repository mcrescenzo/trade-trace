from __future__ import annotations

import json
from pathlib import Path

from tests._mcp_helpers import with_legacy_idempotency_key
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.migrations import _migration_009_events_append_only
from trade_trace.storage.paths import db_path
from trade_trace.tools import memory as memory_tools


def _init(home: Path) -> None:
    env = mcp_call("journal.init", {"home": str(home)})
    assert env.ok, env



def test_embeddings_provider_none_does_not_load_sqlite_vec(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    _init(home)

    calls: list[object] = []

    def _boom(conn):
        calls.append(conn)
        raise AssertionError("sqlite-vec loader must not run when provider=none")

    monkeypatch.setattr("trade_trace.storage.database.load_sqlite_vec_extension", _boom)
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT value FROM config WHERE key = 'embeddings.provider'"
        ).fetchone()
    finally:
        db.close()

    assert row is None or row[0] == "none"
    assert calls == []


def test_embeddings_provider_local_does_not_load_sqlite_vec(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    _init(home)

    env = mcp_call("journal.config_set", with_legacy_idempotency_key("journal.config_set", {
        "home": str(home),
        "key": "embeddings.provider",
        "value": "local",
        "_confirm": True,
    }))
    assert env.ok, env

    calls: list[object] = []

    def _record(conn):
        calls.append(conn)

    monkeypatch.setattr("trade_trace.storage.database.load_sqlite_vec_extension", _record)
    db = open_database(db_path(home), create_parent=False)
    try:
        assert db.connection.execute(
            "SELECT value FROM config WHERE key = 'embeddings.provider'"
        ).fetchone()[0] == "local"
    finally:
        db.close()

    assert calls == []


def test_migration_009_memory_node_embeddings_is_idempotent(tmp_path: Path):
    home = tmp_path / "home"
    db = open_database(db_path(home))
    try:
        apply_pending_migrations(db.connection, target_version=8)
        _migration_009_events_append_only(db.connection)
        _migration_009_events_append_only(db.connection)
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='memory_node_embeddings'"
        ).fetchone()
        assert row[0] == "memory_node_embeddings"
    finally:
        db.close()


def test_vec_insert_and_similarity_query_round_trip(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    _init(home)
    retain_a = mcp_call("memory.retain", {
        "home": str(home), "node_type": "observation", "body": "alpha vector", "id": "mem_alpha_vector", "idempotency_key": "test:retain-alpha-vector",
    })
    retain_b = mcp_call("memory.retain", {
        "home": str(home), "node_type": "observation", "body": "beta vector", "id": "mem_beta_vector", "idempotency_key": "test:retain-beta-vector",
    })
    assert retain_a.ok and retain_b.ok

    monkeypatch.setattr("trade_trace.storage.database.load_sqlite_vec_extension", lambda conn: None)
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            "INSERT INTO config(key, value, updated_at) VALUES "
            "('embeddings.provider', 'local', '2026-01-01T00:00:00Z') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        db.connection.execute(
            "INSERT INTO memory_node_embeddings"
            "(node_id, provider, dim, model_id, embedding, created_at) "
            "VALUES (?, 'local', 2, 'test-model', ?, '2026-01-01T00:00:00Z')",
            (retain_a.data["id"], memory_tools._float32_blob([1.0, 0.0])),
        )
        db.connection.execute(
            "INSERT INTO memory_node_embeddings"
            "(node_id, provider, dim, model_id, embedding, created_at) "
            "VALUES (?, 'local', 2, 'test-model', ?, '2026-01-01T00:00:00Z')",
            (retain_b.data["id"], memory_tools._float32_blob([0.0, 1.0])),
        )
        db.connection.commit()
        monkeypatch.setattr(memory_tools, "_query_embedding", lambda *a, **k: [1.0, 0.0])
        ranked = memory_tools._semantic_rank(
            db.connection,
            "alpha",
            "local",
            {retain_a.data["id"]: {}, retain_b.data["id"]: {}},
        )
    finally:
        db.close()

    assert ranked == [retain_a.data["id"]]


def test_semantic_strategy_appears_in_memory_recall_when_enabled(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    _init(home)
    retain = mcp_call("memory.retain", {
        "home": str(home), "node_type": "observation", "body": "semantic recall row",
    })
    assert retain.ok, retain

    monkeypatch.setattr("trade_trace.storage.database.load_sqlite_vec_extension", lambda conn: None)
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            "INSERT INTO config(key, value, updated_at) VALUES "
            "('embeddings.provider', 'local', '2026-01-01T00:00:00Z') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        db.connection.execute(
            "INSERT INTO memory_node_embeddings"
            "(node_id, provider, dim, model_id, embedding, created_at) "
            "VALUES (?, 'local', 2, 'test-model', ?, '2026-01-01T00:00:00Z')",
            (retain.data["id"], memory_tools._float32_blob([1.0, 0.0])),
        )
        db.connection.commit()
    finally:
        db.close()

    monkeypatch.setattr(memory_tools, "_query_embedding", lambda *a, **k: [1.0, 0.0])
    recall = mcp_call("memory.recall", {
        "home": str(home), "query": "semantic", "k": 5, "strategies": ["semantic"],
    })

    assert recall.ok, recall
    assert "semantic" in recall.data["strategies_used"]
    assert recall.data["items"][0]["id"] == retain.data["id"]
    item = recall.data["items"][0]
    assert "semantic" in item["strategy_provenance"]
    serialized_item = json.dumps(item, sort_keys=True)
    assert "api_key" not in serialized_item
    assert str(home) not in serialized_item
