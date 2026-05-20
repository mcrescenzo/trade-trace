from __future__ import annotations

import json

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.contracts.envelope import SuccessEnvelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_tool_specs
from trade_trace.security.credential_keys import PROJECT_CREDENTIAL_KEYS
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def test_idea_capture_registered_and_self_describing():
    reg = default_registry().get("idea.capture")
    assert reg.is_write is True
    assert reg.json_schema is not None
    assert reg.json_schema["required"] == ["thought", "idempotency_key"]
    assert "no external" in reg.description.lower() or "does not fetch" in reg.description.lower()
    assert reg.metadata()["next_actions"]


def test_idea_capture_mcp_spec_omits_private_auth_fragments():
    specs = [spec for spec in mcp_tool_specs() if spec["name"] == "idea.capture"]
    assert len(specs) == 1
    rendered = json.dumps(specs[0], sort_keys=True).lower()
    forbidden_fragments = sorted(
        PROJECT_CREDENTIAL_KEYS
        | {
            "access_key",
            "credential",
            "credentials",
            "secret",
            "token",
            "transport_hint",
            "mcp_transport_hints",
        }
    )
    assert not [fragment for fragment in forbidden_fragments if fragment in rendered]


def test_idea_capture_writes_source_memory_and_provenance_edge(home):
    env = _mcp(home, "idea.capture", {
        "thought": "Rough thought: investigate CPI surprise in rate-cut prediction markets later.",
        "title": "CPI surprise draft",
        "captured_at": "2026-05-20T14:00:00Z",
        "tags": ["macro"],
        "idempotency_key": "00000000-0000-4000-8000-idea00000001",
    })
    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    data = env.data
    assert data["capture_state"] == "draft_needs_enrichment"
    assert data["source_id"].startswith("src_")
    assert data["memory_node_id"].startswith("mem_")
    assert data["source_memory_edge_id"].startswith("edg_")
    assert data["no_advice_boundary"] == {
        "external_fetch_performed": False,
        "trade_execution_performed": False,
        "advice_generated": False,
        "note": "This stores your thought locally for later enrichment; it is not investment advice.",
    }
    assert any("thesis.add" in action for action in data["next_actions"])

    db = open_database(db_path(home), create_parent=False)
    try:
        source_row = db.connection.execute(
            "SELECT kind, stance, title, note, metadata_json FROM sources WHERE id = ?",
            (data["source_id"],),
        ).fetchone()
        memory_row = db.connection.execute(
            "SELECT node_type, title, body, meta_json, confidence_base FROM memory_nodes WHERE id = ?",
            (data["memory_node_id"],),
        ).fetchone()
        edge_row = db.connection.execute(
            "SELECT source_kind, source_id, target_kind, target_id, edge_type FROM edges WHERE id = ?",
            (data["source_memory_edge_id"],),
        ).fetchone()
    finally:
        db.close()

    assert source_row[:4] == (
        "note",
        "neutral",
        "CPI surprise draft",
        "Rough thought: investigate CPI surprise in rate-cut prediction markets later.",
    )
    source_meta = json.loads(source_row[4])
    assert source_meta["draft_state"] == "needs_enrichment"
    assert source_meta["external_fetch_performed"] is False
    assert source_meta["no_advice"] is True

    assert memory_row[0] == "observation"
    assert memory_row[1] == "CPI surprise draft"
    assert memory_row[4] == 0.5
    memory_meta = json.loads(memory_row[3])
    assert memory_meta["source_id"] == data["source_id"]
    assert "needs_enrichment" in memory_meta["tags"]

    assert edge_row == (
        "source",
        data["source_id"],
        "memory_node",
        data["memory_node_id"],
        "about",
    )


def test_idea_capture_replay_returns_same_ids(home):
    payload = {
        "thought": "Draft thought to replay without duplicate primitive rows.",
        "idempotency_key": "00000000-0000-4000-8000-idea00000002",
    }
    first = _mcp(home, "idea.capture", payload)
    second = _mcp(home, "idea.capture", payload)
    assert first.ok and second.ok
    assert isinstance(first, SuccessEnvelope)
    assert isinstance(second, SuccessEnvelope)
    assert first.data["source_id"] == second.data["source_id"]
    assert first.data["memory_node_id"] == second.data["memory_node_id"]
    assert first.data["source_memory_edge_id"] == second.data["source_memory_edge_id"]


def test_idea_capture_invalid_downstream_validation_is_atomic(home):
    env = _mcp(home, "idea.capture", {
        "thought": "This should not leave a source row behind.",
        "importance": 99,
        "idempotency_key": "00000000-0000-4000-8000-idea00000003",
    })
    assert not env.ok
    assert env.error.code == "VALIDATION_ERROR"

    db = open_database(db_path(home), create_parent=False)
    try:
        counts = db.connection.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM sources), "
            "(SELECT COUNT(*) FROM memory_nodes), "
            "(SELECT COUNT(*) FROM edges)"
        ).fetchone()
    finally:
        db.close()
    assert counts == (0, 0, 0)


def test_idea_capture_reused_idempotency_key_with_changed_capture_conflicts(home):
    payload = {
        "thought": "Original captured idea.",
        "title": "Original title",
        "tags": ["macro"],
        "metadata_json": {"desk": "rates"},
        "idempotency_key": "00000000-0000-4000-8000-idea00000004",
    }
    first = _mcp(home, "idea.capture", payload)
    assert first.ok, first

    changed = {**payload, "thought": "Changed captured idea."}
    second = _mcp(home, "idea.capture", changed)
    assert not second.ok
    assert second.error.code == "IDEMPOTENCY_CONFLICT"

    replay = _mcp(home, "idea.capture", payload)
    assert replay.ok
    assert replay.data["source_id"] == first.data["source_id"]
    assert replay.data["memory_node_id"] == first.data["memory_node_id"]

    db = open_database(db_path(home), create_parent=False)
    try:
        counts = db.connection.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM sources), "
            "(SELECT COUNT(*) FROM memory_nodes), "
            "(SELECT COUNT(*) FROM edges)"
        ).fetchone()
    finally:
        db.close()
    assert counts == (1, 1, 1)
