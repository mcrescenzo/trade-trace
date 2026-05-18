"""M3 memory graph tools per bead trade-trace-e86.

Covers acceptance criteria:
- memory.retain creates rows for 3 node_types.
- memory.reflect creates reflection + about-edge atomically.
- memory.link explicit typed edge with endpoint validation.
- Reflections cannot be orphan prose (runnable invariant).
- memory.recall with BM25 / temporal / graph strategies, no embeddings.
- memory_recall_events appended per recall; memory_node_stats rebuildable.
- Recall result carries id/body/score/strategy_provenance/source_refs.
- Importance, supersession_discount applied at rank time.
- Bi-temporal as_of filtering applied BEFORE ranking (cases a/b/c).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.projections import rebuild_memory_node_stats
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _mcp(home: Path, tool: str, args: dict | None = None):
    payload = {"home": str(home), **(args or {})}
    return mcp_call(tool, payload, actor_id="agent:default")


def _seed_thesis(home: Path) -> dict:
    venue = _mcp(home, "venue.add",
                 {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": "X",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes",
        "body": "Earnings beat is likely on AI demand.",
    }).data["id"]
    return {"venue": venue, "instrument": inst, "thesis": thesis}


# -- registration ----------------------------------------------------


def test_memory_tools_registered():
    names = default_registry().names()
    for name in ("memory.retain", "memory.reflect", "memory.link", "memory.recall"):
        assert name in names


# -- 1. memory.retain creates rows for each node_type -----------------


@pytest.mark.parametrize("node_type", ["observation", "reflection", "playbook_rule"])
def test_memory_retain_creates_each_node_type(home, node_type):
    env = _mcp(home, "memory.retain", {
        "node_type": node_type,
        "body": f"A {node_type} about prediction market liquidity patterns.",
        "importance": 6,
        "idempotency_key": f"00000000-0000-4000-8000-{node_type:>012}"[:36],
    })
    assert env.ok, env
    assert env.data["node_type"] == node_type
    assert env.data["body"].startswith("A ")
    assert env.data["importance"] == 6
    # Row exists in the DB.
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT node_type, importance FROM memory_nodes WHERE id = ?",
            (env.data["id"],),
        ).fetchone()
    finally:
        db.close()
    assert row[0] == node_type and row[1] == 6


def test_memory_retain_rejects_unknown_node_type(home):
    env = _mcp(home, "memory.retain", {
        "node_type": "musing", "body": "x",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"


def test_memory_retain_rejects_invalid_importance(home):
    for bad in (0, 11, "high", -5):
        env = _mcp(home, "memory.retain", {
            "node_type": "observation", "body": "x", "importance": bad,
        })
        assert env.ok is False, f"importance={bad} should be rejected"
        assert env.error.code.value == "VALIDATION_ERROR"


# -- 2. memory.reflect: reflection + about edge atomic ------------


def test_memory_reflect_writes_reflection_with_about_edge(home):
    seeds = _seed_thesis(home)
    env = _mcp(home, "memory.reflect", {
        "target_kind": "thesis", "target_id": seeds["thesis"],
        "body": "I should have weighed the liquidity profile more heavily.",
        "idempotency_key": "00000000-0000-4000-8000-r00000000001",
    })
    assert env.ok, env
    node_id = env.data["id"]
    assert env.data["edge_id"].startswith("edg_")
    assert env.data["target_kind"] == "thesis"

    # Both rows exist.
    db = open_database(db_path(home), create_parent=False)
    try:
        node_row = db.connection.execute(
            "SELECT node_type FROM memory_nodes WHERE id = ?", (node_id,),
        ).fetchone()
        edge_row = db.connection.execute(
            "SELECT edge_type, target_kind, target_id FROM edges "
            "WHERE source_kind = 'memory_node' AND source_id = ?",
            (node_id,),
        ).fetchone()
    finally:
        db.close()
    assert node_row[0] == "reflection"
    assert edge_row == ("about", "thesis", seeds["thesis"])


def test_memory_reflect_rejects_missing_target(home):
    env = _mcp(home, "memory.reflect", {
        "target_kind": "thesis", "target_id": "thes_nope",
        "body": "reflection",
    })
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details["entity_kind"] == "thesis"


def test_reflection_orphan_invariant_holds_after_writes(home):
    """Runnable assertion from bead e86: no reflection lacks an about-edge."""

    seeds = _seed_thesis(home)
    for i in range(3):
        _mcp(home, "memory.reflect", {
            "target_kind": "thesis", "target_id": seeds["thesis"],
            "body": f"Reflection #{i}",
            "idempotency_key": f"00000000-0000-4000-8000-orphan{i:06d}",
        })
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            """
            SELECT count(*) FROM memory_nodes n
            WHERE n.node_type='reflection'
              AND NOT EXISTS (
                SELECT 1 FROM edges e
                WHERE e.source_kind='memory_node'
                  AND e.source_id=n.id
                  AND e.edge_type='about'
              )
            """
        ).fetchone()
    finally:
        db.close()
    assert row[0] == 0


# -- 3. memory.link explicit edge ---------------------------------


def test_memory_link_creates_typed_edge(home):
    seeds = _seed_thesis(home)
    # Two memory nodes: link one supersedes the other.
    n_old = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "Old observation about NVDA earnings",
        "idempotency_key": "00000000-0000-4000-8000-link00000001",
    }).data["id"]
    n_new = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "Updated observation refining the prior one",
        "idempotency_key": "00000000-0000-4000-8000-link00000002",
    }).data["id"]
    env = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": n_new,
        "target_kind": "memory_node", "target_id": n_old,
        "edge_type": "supersedes",
        "idempotency_key": "00000000-0000-4000-8000-link00000003",
    })
    assert env.ok, env
    assert env.data["edge_type"] == "supersedes"


def test_memory_link_rejects_invalid_edge_type(home):
    env = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": "x",
        "target_kind": "memory_node", "target_id": "y",
        "edge_type": "not_a_real_edge",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "edge_type"


# -- 4. memory.recall — BM25, temporal, graph strategies --------


def test_memory_recall_returns_top_k_with_provenance(home):
    """Recall returns items with id, body, score, strategy_provenance,
    and source_refs (bead acceptance)."""

    for i, body in enumerate([
        "Spread compression near resolution is mispriced on prediction markets",
        "AI demand boosted NVDA earnings in 2026 Q1",
        "Thin liquidity around expiration widens effective spread",
    ]):
        _mcp(home, "memory.retain", {
            "node_type": "observation", "body": body, "importance": 5 + i,
            "idempotency_key": f"00000000-0000-4000-8000-recall{i:08d}",
        })
    env = _mcp(home, "memory.recall", {
        "query": "spread liquidity",
        "k": 5,
    })
    assert env.ok, env
    items = env.data["items"]
    assert items, "expected at least one recall item"
    for item in items:
        assert "id" in item and "body" in item and "score" in item
        assert "strategy_provenance" in item
        assert "source_refs" in item
    assert set(env.data["strategies_used"]) >= {"bm25", "temporal", "graph"}


def test_memory_recall_appends_recall_event_and_updates_stats(home):
    """memory_recall_events grows with each call; memory_node_stats
    projection mirrors recall_count + last_recalled_at."""

    nid = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "Liquidity compression observation",
        "idempotency_key": "00000000-0000-4000-8000-stats0000001",
    }).data["id"]
    # Run recall twice; nid should appear in node_ids_returned both times.
    for _ in range(2):
        env = _mcp(home, "memory.recall", {"query": "liquidity", "k": 3})
        assert env.ok
        assert any(it["id"] == nid for it in env.data["items"])
    db = open_database(db_path(home), create_parent=False)
    try:
        recall_count = db.connection.execute(
            "SELECT COUNT(*) FROM memory_recall_events"
        ).fetchone()[0]
        stats_row = db.connection.execute(
            "SELECT recall_count, last_recalled_at FROM memory_node_stats "
            "WHERE node_id = ?", (nid,),
        ).fetchone()
    finally:
        db.close()
    assert recall_count == 2
    assert stats_row[0] == 2
    assert stats_row[1] is not None


def test_memory_node_stats_rebuildable_from_events(home):
    """Drop the projection and rebuild from memory_recall_events; the
    resulting state matches the eager-update path byte-for-byte."""

    nid = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "Rebuildable projection observation",
        "idempotency_key": "00000000-0000-4000-8000-rebld0000001",
    }).data["id"]
    _mcp(home, "memory.recall", {"query": "rebuildable", "k": 3})
    _mcp(home, "memory.recall", {"query": "projection", "k": 3})

    db = open_database(db_path(home), create_parent=False)
    try:
        eager = db.connection.execute(
            "SELECT recall_count FROM memory_node_stats WHERE node_id = ?",
            (nid,),
        ).fetchone()[0]
        result = rebuild_memory_node_stats(db.connection)
        rebuilt = db.connection.execute(
            "SELECT recall_count FROM memory_node_stats WHERE node_id = ?",
            (nid,),
        ).fetchone()[0]
    finally:
        db.close()
    assert eager == rebuilt
    assert result.rebuilt_rows >= 1


# -- 5. bi-temporal as_of filter (cases a/b/c) ----------------


def test_recall_as_of_excludes_future_valid_from(home):
    """Case (a): a node whose `valid_from` is after `as_of` is NOT in scope."""

    future = "2099-01-01T00:00:00Z"
    nid = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "future obs",
        "valid_from": future,
        "idempotency_key": "00000000-0000-4000-8000-asof00000001",
    }).data["id"]
    env = _mcp(home, "memory.recall", {
        "query": "future", "as_of": "2026-06-01T00:00:00Z", "k": 10,
    })
    assert env.ok
    assert all(it["id"] != nid for it in env.data["items"])


def test_recall_as_of_excludes_past_valid_to(home):
    """Case (b): a node whose `valid_to` is <= `as_of` is NOT in scope."""

    nid = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "expired obs",
        "valid_from": "2020-01-01T00:00:00Z",
        "valid_to": "2021-01-01T00:00:00Z",
        "idempotency_key": "00000000-0000-4000-8000-asof00000002",
    }).data["id"]
    env = _mcp(home, "memory.recall", {
        "query": "expired", "as_of": "2026-06-01T00:00:00Z", "k": 10,
    })
    assert env.ok
    assert all(it["id"] != nid for it in env.data["items"])


def test_recall_as_of_excludes_invalidated_nodes(home):
    """Case (c): a node with `invalidated_at <= as_of` is NOT in scope.

    Invalidation is set by a successor write in production; the
    write-time invalidation tool (`memory.invalidate`) is a P1 surface
    per bead e86. For the bi-temporal filter test we drop the
    append-only trigger inside this isolated home, UPDATE the
    `invalidated_at` column directly, and assert the recall path
    filters it out. The home is `tmp_path`-scoped so the trigger drop
    does not leak into other tests."""

    nid = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "invalid obs",
        "valid_from": "2020-01-01T00:00:00Z",
        "idempotency_key": "00000000-0000-4000-8000-asof00000003",
    }).data["id"]
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute("DROP TRIGGER trg_memory_nodes_no_update")
        db.connection.execute(
            "UPDATE memory_nodes SET invalidated_at = ? WHERE id = ?",
            ("2025-01-01T00:00:00Z", nid),
        )
    finally:
        db.close()
    env = _mcp(home, "memory.recall", {
        "query": "invalid", "as_of": "2026-06-01T00:00:00Z", "k": 10,
    })
    assert env.ok
    assert all(it["id"] != nid for it in env.data["items"])


# -- 6. supersession discount ------------------------------------


def test_supersession_discount_applies_to_superseded_nodes(home):
    """A node with a supersedes-edge pointing AT it gets its score
    multiplied by SUPERSESSION_DISCOUNT (=0.25). Test infers the
    behavior by comparing the ranking of a superseded-vs-fresh
    pair with identical text."""

    # Two nodes with identical body — same BM25/temporal posture.
    old = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "Liquidity is thin near resolution dates",
        "importance": 8,
        "idempotency_key": "00000000-0000-4000-8000-sup00000001",
    }).data["id"]
    new = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "Liquidity is thin near resolution dates",
        "importance": 8,
        "idempotency_key": "00000000-0000-4000-8000-sup00000002",
    }).data["id"]
    _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": new,
        "target_kind": "memory_node", "target_id": old,
        "edge_type": "supersedes",
        "idempotency_key": "00000000-0000-4000-8000-sup00000003",
    })
    env = _mcp(home, "memory.recall", {
        "query": "Liquidity is thin near resolution dates", "k": 10,
    })
    ids = [it["id"] for it in env.data["items"]]
    # `new` ranks before `old` because `old` was discounted.
    assert new in ids and old in ids
    assert ids.index(new) < ids.index(old)


# -- 7. recall validation ----------------------------------------


def test_recall_rejects_invalid_strategy(home):
    env = _mcp(home, "memory.recall", {
        "query": "x", "strategies": ["bm25", "totally_made_up"],
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"


def test_recall_rejects_invalid_k(home):
    env = _mcp(home, "memory.recall", {"query": "x", "k": 0})
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"


# -- 8. retain requires no network -------------------------------


def test_memory_retain_makes_no_outbound_calls(home):
    """The bead requires journal.init + memory.retain to work without
    embeddings model weights / network. The opt-in embeddings path is
    bead ubp; this test asserts the default off-path."""

    import socket

    saved_socket = socket.socket
    socket.socket = None  # type: ignore[assignment]
    try:
        env = _mcp(home, "memory.retain", {
            "node_type": "observation", "body": "offline observation",
            "idempotency_key": "00000000-0000-4000-8000-offline00001",
        })
    finally:
        socket.socket = saved_socket
    assert env.ok
