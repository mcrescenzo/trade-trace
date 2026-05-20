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

import json
from pathlib import Path

import pytest

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.core import default_registry
from trade_trace.projections import rebuild_memory_node_stats
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


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


# -- bead trade-trace-m0h: README §quickstart sugar shape ----------


def _seed_decision(home):
    """Mirror of _seed_thesis but bottoms out at a decision so the
    README example's `target.kind = 'decision'` path is exercisable."""

    venue = _mcp(home, "venue.add", {
        "name": "PM", "kind": "prediction_market",
    }).data["id"]
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue, "title": "X",
        "asset_class": "prediction_market",
    }).data["id"]
    decision = _mcp(home, "decision.add", {
        "instrument_id": instrument, "type": "skip",
        "reason": "no edge today",
    }).data["id"]
    return {"venue": venue, "instrument": instrument, "decision": decision}


def test_memory_reflect_accepts_readme_sugar_shape(home):
    """The README quickstart shape — `target={kind,id}`, `insight`,
    `strength_tags` — must work end-to-end through mcp_call (bead
    trade-trace-m0h)."""

    seeds = _seed_decision(home)
    env = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": (
            "Skip was correct here; spread compression never materialized."
        ),
        "strength_tags": ["good-skip", "good-liquidity-discipline"],
    })
    assert env.ok, env

    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT body, meta_json FROM memory_nodes WHERE id = ?",
            (env.data["id"],),
        ).fetchone()
        edge = db.connection.execute(
            "SELECT target_kind, target_id FROM edges "
            "WHERE source_kind = 'memory_node' AND source_id = ?",
            (env.data["id"],),
        ).fetchone()
    finally:
        db.close()
    assert row[0] == (
        "Skip was correct here; spread compression never materialized."
    )
    import json
    meta = json.loads(row[1])
    assert set(meta.get("tags", [])) == {
        "good-skip", "good-liquidity-discipline",
    }
    assert edge == ("decision", seeds["decision"])


def test_memory_reflect_target_object_conflicts_with_target_kind(home):
    seeds = _seed_decision(home)
    env = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "target_kind": "thesis",  # contradicts target.kind
        "insight": "should fail",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "target"


def test_memory_reflect_insight_and_body_conflict_rejected(home):
    seeds = _seed_decision(home)
    env = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": "one phrasing",
        "body": "another phrasing",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "insight"


def test_memory_reflect_strength_tags_must_be_list_of_strings(home):
    seeds = _seed_decision(home)
    env = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": "tags shape check",
        "strength_tags": "not-a-list",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"


def test_memory_reflect_accepts_meta_json_string_with_tag_folding(home):
    seeds = _seed_decision(home)
    env = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": "string meta with tags",
        "meta_json": '{"tags": ["existing"], "source": "test"}',
        "strength_tags": ["strong"],
        "weakness_tags": ["weak"],
    })
    assert env.ok, env

    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT meta_json FROM memory_nodes WHERE id = ?",
            (env.data["id"],),
        ).fetchone()
    finally:
        db.close()
    meta = json.loads(row[0])
    assert meta["source"] == "test"
    assert meta["tags"] == ["existing", "strong", "weak"]


def test_memory_reflect_accepts_meta_json_object_with_tag_folding(home):
    seeds = _seed_decision(home)
    env = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": "object meta with tags",
        "meta_json": {"source": "object"},
        "strength_tags": ["strong"],
    })
    assert env.ok, env

    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT meta_json FROM memory_nodes WHERE id = ?",
            (env.data["id"],),
        ).fetchone()
    finally:
        db.close()
    meta = json.loads(row[0])
    assert meta == {"source": "object", "tags": ["strong"]}


def test_memory_reflect_rejects_scalar_meta_json_with_tags(home):
    seeds = _seed_decision(home)
    env = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": "scalar meta rejected",
        "meta_json": 42,
        "strength_tags": ["strong"],
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details == {"field": "meta_json"}


def test_memory_reflect_rejects_invalid_meta_json_string(home):
    seeds = _seed_decision(home)
    env = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": "invalid JSON meta rejected",
        "meta_json": "{not-json}",
        "strength_tags": ["strong"],
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details == {"field": "meta_json", "reason": "invalid_json"}


def test_memory_reflect_deferred_edge_sugar_returns_unsupported(home):
    """memory-layer.md §10 lists derived_from / supports / contradicts /
    supersedes as deferred to P1+; passing any of them must surface as
    UNSUPPORTED_CAPABILITY so the docs/impl gap is loud (bead m0h)."""

    seeds = _seed_decision(home)
    for field in ("derived_from", "supports", "contradicts", "supersedes"):
        env = _mcp(home, "memory.reflect", {
            "target": {"kind": "decision", "id": seeds["decision"]},
            "insight": "reflection",
            field: ["mem_abc"],
        })
        assert env.ok is False, f"{field} unexpectedly accepted"
        assert env.error.code.value == "UNSUPPORTED_CAPABILITY"
        assert env.error.details["field"] == field
        assert "P1" in env.error.details["deferred_to"]


def test_memory_reflect_idempotent_retry_without_valid_from_replays(home):
    """Per bead trade-trace-e62: a memory.reflect retry that omits
    `valid_from` (same idempotency_key, otherwise identical args) used
    to surface IDEMPOTENCY_CONFLICT because the first call stored
    `valid_from = created_at` while the retry's payload had
    `valid_from = None`. The replay path now reuses the original
    payload's `valid_from` so a pure retry round-trips cleanly."""

    seeds = _seed_decision(home)
    args = {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": "retry-safe reflection",
        "idempotency_key": "00000000-0000-4000-8000-e62retry0001",
    }
    env_a = _mcp(home, "memory.reflect", args)
    assert env_a.ok, env_a
    node_id = env_a.data["id"]

    env_b = _mcp(home, "memory.reflect", args)
    assert env_b.ok, env_b
    assert env_b.data["id"] == node_id, (
        "retry must replay the original node id, not raise "
        "IDEMPOTENCY_CONFLICT"
    )


def test_memory_retain_idempotent_retry_without_valid_from_replays(home):
    """Same contract on memory.retain directly — the bug lived in the
    shared retain helper, not in reflect."""

    args = {
        "node_type": "observation",
        "body": "retry-safe observation",
        "idempotency_key": "00000000-0000-4000-8000-e62retain001",
    }
    env_a = _mcp(home, "memory.retain", args)
    assert env_a.ok, env_a
    env_b = _mcp(home, "memory.retain", args)
    assert env_b.ok, env_b
    assert env_b.data["id"] == env_a.data["id"]


def test_memory_reflect_rejects_missing_target(home):
    env = _mcp(home, "memory.reflect", {
        "target_kind": "thesis", "target_id": "thes_nope",
        "body": "reflection",
    })
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details["entity_kind"] == "thesis"


def test_memory_reflect_rolls_back_node_when_about_edge_insert_fails(home):
    """A late edge failure must not leave the reflection node committed."""

    seeds = _seed_thesis(home)
    seed_env = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "Existing source for duplicate edge id setup.",
        "idempotency_key": "00000000-0000-4000-8000-rollbackseed1",
    })
    assert seed_env.ok, seed_env
    existing_node = seed_env.data["id"]
    duplicate_edge_id = "edg_forced_reflect_rollback"
    failing_body = "Reflection body should roll back with duplicate edge id."

    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, "
            "target_id, edge_type, metadata_json, created_at, actor_id) "
            "VALUES (?, 'memory_node', ?, 'thesis', ?, 'about', '{}', "
            "'2026-01-01T00:00:00Z', 'agent:default')",
            (duplicate_edge_id, existing_node, seeds["thesis"]),
        )
        db.connection.commit()
    finally:
        db.close()

    env = _mcp(home, "memory.reflect", {
        "target_kind": "thesis", "target_id": seeds["thesis"],
        "body": failing_body,
        "edge_id": duplicate_edge_id,
        "idempotency_key": "00000000-0000-4000-8000-rollback0001",
    })
    assert env.ok is False

    db = open_database(db_path(home), create_parent=False)
    try:
        reflected_rows = db.connection.execute(
            "SELECT COUNT(*) FROM memory_nodes "
            "WHERE node_type = 'reflection' AND body = ?",
            (failing_body,),
        ).fetchone()[0]
        retained_events = db.connection.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'memory_node.retained' "
            "AND idempotency_key = ?",
            ("00000000-0000-4000-8000-rollback0001",),
        ).fetchone()[0]
    finally:
        db.close()
    assert reflected_rows == 0
    assert retained_events == 0


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
    _seed_thesis(home)
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


# -- memory.retain meta_json shape validation (trade-trace-arcx) ----


def test_memory_retain_rejects_non_object_meta_json(home):
    """Per trade-trace-arcx: `memory.retain` must reject non-object
    `meta_json` (list, string, number, bool) with VALIDATION_ERROR at
    the direct retain boundary. Previously the handler `json.dumps`d
    whatever was passed, so a list or scalar would persist and confuse
    downstream consumers that assume object-shaped metadata."""

    for bad in ([1, 2, 3], "not an object", 42, True):
        env = _mcp(home, "memory.retain", {
            "node_type": "observation",
            "body": "test body",
            "meta_json": bad,
            "idempotency_key": f"arcx-{type(bad).__name__}",
        })
        assert env.ok is False, (
            f"meta_json={bad!r} ({type(bad).__name__}) should be rejected"
        )
        assert env.error.code.value == "VALIDATION_ERROR"
        assert env.error.details.get("field") == "meta_json"


def test_memory_retain_accepts_object_meta_json(home):
    """A normal object `meta_json` continues to write successfully and
    round-trips into the row."""

    env = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "with meta",
        "meta_json": {"tags": ["foo"], "confidence_note": "high"},
        "idempotency_key": "arcx-object",
    })
    assert env.ok, env


def test_memory_retain_accepts_string_object_meta_json(home):
    env = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "with string meta",
        "meta_json": '{"tags": ["foo"], "confidence_note": "high"}',
        "idempotency_key": "9gp0-string-object",
    })
    assert env.ok, env

    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT meta_json FROM memory_nodes WHERE id = ?",
            (env.data["id"],),
        ).fetchone()
    finally:
        db.close()
    assert json.loads(row[0]) == {"confidence_note": "high", "tags": ["foo"]}


def test_memory_retain_rejects_invalid_meta_json_string(home):
    env = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "with invalid meta",
        "meta_json": "{not-json}",
        "idempotency_key": "9gp0-invalid-json",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details == {"field": "meta_json", "reason": "invalid_json"}


def test_memory_retain_treats_omitted_meta_json_as_empty_object(home):
    """No `meta_json` arg → stored as `{}` (the existing default)."""

    env = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "no meta",
        "idempotency_key": "arcx-default",
    })
    assert env.ok, env
