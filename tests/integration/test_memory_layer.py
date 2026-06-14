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
from trade_trace.tools import memory as memory_tools


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


def _seed_observation(home, body, key):
    return _mcp(home, "memory.retain", {
        "node_type": "observation", "body": body,
        "idempotency_key": key,
    }).data["id"]


def test_memory_reflect_writes_edge_sugar_edges(home):
    """memory-layer.md §10 edge-sugar (derived_from / supports /
    contradicts / supersedes) writes one typed edge from the reflection
    to each named memory-node, atomically with the reflection + about
    edge (bead trade-trace-qikt)."""

    seeds = _seed_decision(home)
    n_obs = _seed_observation(
        home, "Prior observation the reflection builds on",
        "00000000-0000-4000-8000-qikt00000001")
    n_other = _seed_observation(
        home, "A node this reflection supports",
        "00000000-0000-4000-8000-qikt00000002")
    n_old = _seed_observation(
        home, "An older reflection this one replaces",
        "00000000-0000-4000-8000-qikt00000003")
    n_wrong = _seed_observation(
        home, "A node this reflection contradicts",
        "00000000-0000-4000-8000-qikt00000004")

    env = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": "Multi-edge reflection in one call.",
        "derived_from": [n_obs],
        "supports": n_other,            # single-string form accepted
        "supersedes": [n_old],
        "contradicts": [n_wrong],
        "idempotency_key": "00000000-0000-4000-8000-qikt00000010",
    })
    assert env.ok, env
    node_id = env.data["id"]

    # Response echoes the written sugar edges.
    by_type = {(e["edge_type"], e["target_id"]) for e in env.data["edges"]}
    assert by_type == {
        ("derived_from", n_obs),
        ("supports", n_other),
        ("supersedes", n_old),
        ("contradicts", n_wrong),
    }

    db = open_database(db_path(home), create_parent=False)
    try:
        rows = db.connection.execute(
            "SELECT edge_type, target_kind, target_id FROM edges "
            "WHERE source_kind = 'memory_node' AND source_id = ? "
            "AND edge_type != 'about' ORDER BY edge_type",
            (node_id,),
        ).fetchall()
    finally:
        db.close()
    assert {(r[0], r[1], r[2]) for r in rows} == {
        ("derived_from", "memory_node", n_obs),
        ("supports", "memory_node", n_other),
        ("supersedes", "memory_node", n_old),
        ("contradicts", "memory_node", n_wrong),
    }
    # The about edge is still written alongside the sugar edges.
    db = open_database(db_path(home), create_parent=False)
    try:
        about = db.connection.execute(
            "SELECT target_kind, target_id FROM edges "
            "WHERE source_id = ? AND edge_type = 'about'", (node_id,),
        ).fetchone()
    finally:
        db.close()
    assert about == ("decision", seeds["decision"])


def test_memory_reflect_edge_sugar_missing_target_rolls_back(home):
    """A named sugar-edge target that does not exist returns NOT_FOUND
    and rolls back the entire reflect write (no orphaned node)."""

    seeds = _seed_decision(home)
    env = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": "should not persist",
        "supports": ["mem_does_not_exist"],
        "idempotency_key": "00000000-0000-4000-8000-qikt00000020",
    })
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details["edge_type"] == "supports"
    assert env.error.details["target_id"] == "mem_does_not_exist"

    db = open_database(db_path(home), create_parent=False)
    try:
        leaked = db.connection.execute(
            "SELECT COUNT(*) FROM memory_nodes WHERE body = ?",
            ("should not persist",),
        ).fetchone()[0]
    finally:
        db.close()
    assert leaked == 0, "failed sugar edge must roll back the reflection node"


def test_memory_reflect_edge_sugar_rejects_non_string_ids(home):
    seeds = _seed_decision(home)
    env = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": "bad shape",
        "supersedes": [123],
        "idempotency_key": "00000000-0000-4000-8000-qikt00000030",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "supersedes"


def test_memory_reflect_edge_sugar_idempotent_retry_no_duplicates(home):
    """A same-key reflect retry reuses the existing sugar edges rather
    than inserting duplicates (co-idempotent with the about edge,
    trade-trace-5udu / -qikt)."""

    seeds = _seed_decision(home)
    n_obs = _seed_observation(
        home, "node referenced by an idempotent reflect",
        "00000000-0000-4000-8000-qikt00000041")
    args = {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": "idempotent multi-edge reflection",
        "derived_from": [n_obs],
        "idempotency_key": "00000000-0000-4000-8000-qikt00000040",
    }
    env_a = _mcp(home, "memory.reflect", args)
    assert env_a.ok, env_a
    env_b = _mcp(home, "memory.reflect", args)
    assert env_b.ok, env_b
    assert env_b.data["id"] == env_a.data["id"]
    assert env_b.data["edges"] == env_a.data["edges"]

    db = open_database(db_path(home), create_parent=False)
    try:
        edge_count = db.connection.execute(
            "SELECT COUNT(*) FROM edges WHERE source_id = ? "
            "AND edge_type = 'derived_from'", (env_a.data["id"],),
        ).fetchone()[0]
        events = db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'edge.created' "
            "AND json_extract(payload_json, '$.edge_type') = 'derived_from' "
            "AND json_extract(payload_json, '$.source_id') = ?",
            (env_a.data["id"],),
        ).fetchone()[0]
    finally:
        db.close()
    assert edge_count == 1, "retry must not duplicate the derived_from edge"
    assert events == 1, "retry must not re-emit edge.created for the sugar edge"


def test_memory_reflect_without_edge_sugar_omits_edges_key(home):
    """A plain reflect (no sugar fields) must not surface an empty
    `edges` key — the field appears only when sugar edges were written."""

    seeds = _seed_decision(home)
    env = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": seeds["decision"]},
        "insight": "plain reflection, no extra edges",
        "idempotency_key": "00000000-0000-4000-8000-qikt00000050",
    })
    assert env.ok, env
    assert "edges" not in env.data


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

    # Per bead trade-trace-5udu: the about-edge INSERT and edge.created
    # event used to run unconditionally after the retain replayed, so two
    # same-key reflect calls left two about-edges (and two edge.created
    # events) for the one (memory_node, target) pair. The edge is now
    # co-idempotent with the retain: exactly one about-edge survives.
    db = open_database(db_path(home), create_parent=False)
    try:
        edge_count = db.connection.execute(
            "SELECT COUNT(*) FROM edges WHERE source_id = ? "
            "AND edge_type = 'about'",
            (node_id,),
        ).fetchone()[0]
        edge_created_events = db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'edge.created' "
            "AND json_extract(payload_json, '$.source_id') = ?",
            (node_id,),
        ).fetchone()[0]
    finally:
        db.close()
    assert edge_count == 1, (
        "replay must reuse the existing about-edge, not insert a duplicate"
    )
    assert edge_created_events == 1, (
        "replay must not re-emit a second edge.created event"
    )
    assert env_b.data["edge_id"] == env_a.data["edge_id"], (
        "replay must return the original edge_id"
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


@pytest.mark.parametrize(
    "context",
    [{}, {"kind": "instrument"}, {"id": "ins_abc"}, {"kind": None, "id": "x"}],
    ids=["empty", "kind-only", "id-only", "null-kind"],
)
def test_graph_rank_abstains_without_entrypoint(home, context):
    """Per bead trade-trace-2iug: with no `{kind, id}` entrypoint the graph
    strategy has no connectivity signal, so _graph_rank returns an empty list
    instead of an alphabetical id-order sort of the whole corpus. This keeps
    the strategy from emitting N zero-signal ranks into RRF."""

    for i in range(3):
        _mcp(home, "memory.retain", {
            "node_type": "observation",
            "body": f"corpus node {i} for graph abstention",
            "idempotency_key": f"00000000-0000-4000-8000-graphabst{i:04d}",
        })
    db = open_database(db_path(home), create_parent=False)
    try:
        in_scope = memory_tools._load_in_scope_nodes(db.connection, as_of=None)
        assert len(in_scope) >= 3, "fixture should seed a multi-node corpus"
        ranked = memory_tools._graph_rank(
            db.connection, context=context, in_scope_rows=in_scope,
        )
    finally:
        db.close()
    assert ranked == [], (
        "no-entrypoint graph strategy must abstain (empty ranking), not sort "
        f"the corpus; got {ranked}"
    )


def test_graph_strategy_contributes_no_provenance_without_context(home):
    """No-context recall still lists `graph` among strategies_used (it remains a
    requested strategy), but because _graph_rank abstains the fused items carry
    NO `graph` entry in their provenance — RRF iterates only the ranks BM25 and
    temporal actually supply (bead trade-trace-2iug)."""

    for i in range(4):
        _mcp(home, "memory.retain", {
            "node_type": "observation",
            "body": f"spread liquidity compression note {i}",
            "idempotency_key": f"00000000-0000-4000-8000-graphprov{i:04d}",
        })
    env = _mcp(home, "memory.recall", {
        "query": "spread liquidity",
        "include_provenance": True,
        "k": 5,
    })
    assert env.ok, env
    # graph is still a requested/used strategy even though it abstained.
    assert "graph" in env.data["strategies_used"]
    items = env.data["items"]
    assert items, "expected lexical/temporal recall to surface items"
    for item in items:
        prov = item["strategy_provenance"]
        assert "graph" not in prov, (
            "abstaining graph strategy must not contribute provenance; got "
            f"{prov} for {item['id']}"
        )
        # Items are still surfaced by the other active strategies.
        assert prov.get("bm25") or prov.get("temporal"), prov


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


def test_recall_as_of_excludes_node_whose_valid_to_equals_as_of(home):
    """trade-trace-5eh3 / nyix(12): the bi-temporal validity window is
    half-open — `_load_in_scope_nodes` gates on `valid_from <= ? AND (valid_to
    IS NULL OR ? < valid_to)` (memory.py:1262-1263). The equality boundary
    `valid_to == as_of` must therefore EXCLUDE the node (the `<=` upper-bound
    semantics: a node valid until T is no longer in scope AT T). Only the
    strictly-past case (`valid_to < as_of`) was covered before; this pins the
    exact-equality edge so an off-by-one flip to `<=` in the SQL would fail."""

    boundary = "2026-06-01T00:00:00Z"
    nid = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "boundary obs at valid_to equals as_of",
        "valid_from": "2020-01-01T00:00:00Z",
        "valid_to": boundary,
        "idempotency_key": "00000000-0000-4000-8000-asof0000valt",
    }).data["id"]

    # as_of exactly equals valid_to -> excluded (half-open upper bound).
    at_boundary = _mcp(home, "memory.recall", {
        "query": "boundary", "as_of": boundary, "k": 10,
    })
    assert at_boundary.ok
    assert all(it["id"] != nid for it in at_boundary.data["items"]), (
        "node with valid_to == as_of must be out of scope (half-open window)"
    )

    # One instant before valid_to -> still in scope (sanity anchor that the
    # exclusion above is the boundary, not blanket suppression).
    before_boundary = _mcp(home, "memory.recall", {
        "query": "boundary", "as_of": "2026-05-31T23:59:59Z", "k": 10,
    })
    assert before_boundary.ok
    assert any(it["id"] == nid for it in before_boundary.data["items"]), (
        "node must still be in scope strictly before valid_to"
    )


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


def test_chained_supersession_discounts_old_and_mid_not_newest(home):
    """trade-trace-5eh3 / nyix(14): chained supersession A<-B, C<-A (mid
    supersedes old, new supersedes mid). `_superseded_node_ids` returns the
    set of all TARGET ids of supersedes edges (memory.py:1633), so BOTH `old`
    and `mid` are targets and each takes the 0.25 discount; `new` is never a
    target and keeps full score. With identical body text the ranking must put
    `new` first and both discounted nodes after it. Only a 2-node chain was
    covered before; this pins the transitive (3-node) case."""

    body = "Resolution-window liquidity compresses on prediction markets"
    old = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": body, "importance": 8,
        "idempotency_key": "00000000-0000-4000-8000-chain00000001",
    }).data["id"]
    mid = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": body, "importance": 8,
        "idempotency_key": "00000000-0000-4000-8000-chain00000002",
    }).data["id"]
    new = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": body, "importance": 8,
        "idempotency_key": "00000000-0000-4000-8000-chain00000003",
    }).data["id"]
    # mid supersedes old
    _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": mid,
        "target_kind": "memory_node", "target_id": old,
        "edge_type": "supersedes",
        "idempotency_key": "00000000-0000-4000-8000-chain00000004",
    })
    # new supersedes mid
    _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": new,
        "target_kind": "memory_node", "target_id": mid,
        "edge_type": "supersedes",
        "idempotency_key": "00000000-0000-4000-8000-chain00000005",
    })

    env = _mcp(home, "memory.recall", {"query": body, "k": 10})
    ids = [it["id"] for it in env.data["items"]]
    assert {old, mid, new} <= set(ids), ids
    # `new` (undiscounted) ranks ahead of both discounted predecessors.
    assert ids.index(new) < ids.index(old)
    assert ids.index(new) < ids.index(mid)


# -- 6b. bm25 multi-word OR fallback (trade-trace-95ry) ----------


def test_bm25_multiword_query_surfaces_partial_match_via_or_fallback(home):
    """Per trade-trace-95ry: FTS5 MATCH is implicit-AND, so a natural-language
    multi-word query whose tokens do NOT all co-occur in one node previously
    returned zero bm25 rows and silently degraded to temporal/graph. The OR
    token fallback must surface the best lexical match WITH bm25 provenance."""

    target = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "instrument snapshot reading trap: mid sampled before bid populated",
        "idempotency_key": "00000000-0000-4000-8000-bm25or00000001",
    }).data["id"]
    # Distractor so the index isn't single-node trivial.
    _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "Unrelated liquidity note about expiration spreads",
        "idempotency_key": "00000000-0000-4000-8000-bm25or00000002",
    })

    # 'ordering' is absent from the target -> strict implicit-AND yields zero.
    env = _mcp(home, "memory.recall", {
        "query": "instrument snapshot ordering trap",
        "strategies": ["bm25"],
        "k": 5,
    })
    assert env.ok, env
    ids = [it["id"] for it in env.data["items"]]
    assert target in ids, f"OR fallback should surface partial match; got {ids}"
    item = next(it for it in env.data["items"] if it["id"] == target)
    assert 1 in item["strategy_provenance"].get("bm25", []) or item["strategy_provenance"].get("bm25"), item


def test_bm25_multiword_query_with_dotted_and_snake_tokens(home):
    """Dotted (forecast.add) and snake_case (instrument_id) identifiers plus a
    word that only indexes joined (not_found) — implicit-AND fails; OR fallback
    surfaces the node because forecast.add/instrument_id/market.bind each hit."""

    target = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "forecast.add failed: instrument_id NOT_FOUND, call market.bind first",
        "idempotency_key": "00000000-0000-4000-8000-bm25or00000003",
    }).data["id"]

    env = _mcp(home, "memory.recall", {
        "query": "forecast.add instrument_id not found market.bind",
        "strategies": ["bm25"],
        "k": 5,
    })
    assert env.ok, env
    ids = [it["id"] for it in env.data["items"]]
    assert target in ids, f"OR fallback should surface dotted/snake match; got {ids}"


def test_bm25_single_malformed_token_surfaces_via_like_fallback(home):
    """trade-trace-5eh3 / nyix(13): a SINGLE dotted/hyphenated identifier
    (e.g. `forecast.add`) is an FTS5 syntax error, so `_fts_match` returns None
    (malformed), AND `_or_token_query` returns None because there is only one
    token — so the OR retry never fires. The last net is `_like_fallback`
    (memory.py:1335), a substring LIKE over body/title. The existing
    dotted/snake test uses a MULTI-word query, which exercises the OR path
    instead; this pins the single-token LIKE path that nothing else reaches.

    Because a single dotted token can ONLY surface a node through
    `_like_fallback` (the strict FTS and OR paths both yield None), the node
    appearing at all in a bm25-only recall is itself proof the LIKE net fired."""

    target = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "calling forecast.add before market.bind returns NOT_FOUND",
        "idempotency_key": "00000000-0000-4000-8000-bm25like000001",
    }).data["id"]
    # Distractor lacking the dotted token so LIKE is non-trivial.
    _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "unrelated note about liquidity near expiration",
        "idempotency_key": "00000000-0000-4000-8000-bm25like000002",
    })

    env = _mcp(home, "memory.recall", {
        "query": "forecast.add",  # single malformed token: FTS None, OR None.
        "strategies": ["bm25"],
        "k": 5,
    })
    assert env.ok, env
    ids = [it["id"] for it in env.data["items"]]
    assert target in ids, f"single-token LIKE fallback should surface match; got {ids}"
    item = next(it for it in env.data["items"] if it["id"] == target)
    assert item["strategy_provenance"].get("bm25"), item


def test_like_fallback_unit_substring_over_body_and_title(home):
    """Direct unit coverage of `_like_fallback` (memory.py:1335): it must match
    a raw substring against body OR title and ignore non-matching rows. This
    isolates the function the integration test reaches only indirectly."""

    body_hit = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "the dotted token forecast.add appears in this body only",
        "idempotency_key": "00000000-0000-4000-8000-likeunit000001",
    }).data["id"]
    title_hit = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "title": "forecast.add in the title",
        "body": "body without the marker",
        "idempotency_key": "00000000-0000-4000-8000-likeunit000002",
    }).data["id"]
    _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "wholly unrelated content",
        "idempotency_key": "00000000-0000-4000-8000-likeunit000003",
    })

    db = open_database(db_path(home), create_parent=False)
    try:
        hits = set(memory_tools._like_fallback(db.connection, "forecast.add"))
    finally:
        db.close()
    assert body_hit in hits
    assert title_hit in hits
    assert len(hits) == 2, hits


def test_like_fallback_orders_recency_first_deterministically(home):
    """trade-trace-1k5d: the LIKE fallback has no bm25 relevance signal, so it
    must impose a deterministic ORDER BY (created_at DESC, id ASC) instead of
    relying on indeterminate SQLite row order. Insert three matching nodes with
    explicit distinct created_at; the fallback must return them newest-first and
    reproducibly."""

    # Seed one node via the tool so the schema/FTS are exercised, then insert
    # rows with EXPLICIT distinct created_at so the recency assertion is
    # deterministic (wall-clock now_iso() could collide on microseconds).
    db = open_database(db_path(home), create_parent=False)
    try:
        rows = [
            ("ln_old", "2026-01-01T00:00:00.000Z"),
            ("ln_mid", "2026-02-01T00:00:00.000Z"),
            ("ln_new", "2026-03-01T00:00:00.000Z"),
        ]
        for node_id, created_at in rows:
            db.connection.execute(
                "INSERT INTO memory_nodes(id, node_type, body, valid_from, "
                "created_at, actor_id) VALUES (?, 'observation', "
                "'shared-marker token', ?, ?, 'agent:test')",
                (node_id, created_at, created_at),
            )
        db.connection.commit()
        first = memory_tools._like_fallback(db.connection, "shared-marker")
        second = memory_tools._like_fallback(db.connection, "shared-marker")
    finally:
        db.close()

    # newest created_at first, id ASC as the tiebreaker; reproducible.
    assert first == ["ln_new", "ln_mid", "ln_old"]
    assert first == second


def test_bm25_strict_and_still_wins_when_all_tokens_co_occur(home):
    """Regression: when every token co-occurs in one node, the precise
    implicit-AND path returns it and the OR fallback never fires — precision
    is preserved for queries that already worked."""

    both = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "compression near resolution mispriced on prediction markets",
        "idempotency_key": "00000000-0000-4000-8000-bm25and0000001",
    }).data["id"]
    _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "compression alone without the other keyword",
        "idempotency_key": "00000000-0000-4000-8000-bm25and0000002",
    })

    env = _mcp(home, "memory.recall", {
        "query": "compression resolution",
        "strategies": ["bm25"],
        "k": 5,
    })
    assert env.ok, env
    assert env.data["items"], "expected the conjunctive match"
    assert env.data["items"][0]["id"] == both


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


# -- 9. recall-quality regression gate (trade-trace-l1uk) ------------
#
# Definition-of-Done criterion 3 (product-scope-v002.md §3): "Memory
# recall reliably surfaces relevant past observations and reflections
# when a new thesis is being formed on a similar market, event type,
# or scenario."
#
# The tests above assert recall runs and returns well-shaped items
# (structural correctness). They do NOT measure recall *quality* — that
# the relevant nodes for a market type actually win the top-K over
# off-topic distractors. The gate below seeds a fixed two-domain corpus
# (crypto price-ladder markets vs. political/election markets), runs a
# fixed query set with a known relevant set per query, and asserts
# precision/recall floors on both the live default stack (BM25 +
# temporal + graph fused) and the strict lexical (BM25-only) stack. A
# ranking regression that lets distractors crowd out the relevant nodes
# trips these assertions.

# Fixed corpus. Each domain has three observations; the relevant set
# for a same-domain query is exactly that domain's three node ids. The
# bodies are written so every node in a domain shares the domain's
# anchor vocabulary, so a domain query lexically separates the domains.
_RECALL_CORPUS_CRYPTO: tuple[str, ...] = (
    "BTC strike ladder: liquidity thins above the round-number strike as "
    "the BTC ladder nears resolution",
    "BTC strike ladder funding flips negative when the BTC price ladder "
    "compresses toward the strike at expiry",
    "BTC strike ladder shows a wide gap between adjacent strike buckets "
    "on the BTC ladder at low volume",
)
_RECALL_CORPUS_ELECTION: tuple[str, ...] = (
    "Election vote count: presidential market repriced after the debate "
    "shifted the polling average before the election vote count",
    "Election vote count: senate race resolution hinges on the certified "
    "election vote count in the contested county",
    "Election vote count: primary market repriced once the frontrunner "
    "clinched the nomination after the election vote count",
)

# (query, relevant-domain-key). Each query is the anchor phrase that
# every same-domain node shares, so the relevant set separates cleanly
# from the off-domain distractors under the live fusion.
_RECALL_QUERIES: tuple[tuple[str, str], ...] = (
    ("BTC strike ladder", "crypto"),
    ("election vote count", "election"),
)


def _seed_recall_corpus(home: Path) -> dict[str, set[str]]:
    """Retain the fixed two-domain corpus; return {domain: {node_ids}}."""

    domains: dict[str, set[str]] = {"crypto": set(), "election": set()}
    for i, body in enumerate(_RECALL_CORPUS_CRYPTO):
        nid = _mcp(home, "memory.retain", {
            "node_type": "observation", "body": body,
            "idempotency_key": f"00000000-0000-4000-8000-rqcry{i:07d}",
        }).data["id"]
        domains["crypto"].add(nid)
    for i, body in enumerate(_RECALL_CORPUS_ELECTION):
        nid = _mcp(home, "memory.retain", {
            "node_type": "observation", "body": body,
            "idempotency_key": f"00000000-0000-4000-8000-rqele{i:07d}",
        }).data["id"]
        domains["election"].add(nid)
    return domains


def test_recall_quality_top_match_is_same_domain_default_stack(home):
    """For each same-domain query the single best (rank-0) result on the
    LIVE default stack (bm25+temporal+graph fused) is a relevant node.
    This is the floor of criterion 3: the most-surfaced memory when
    forming a thesis on market type X is itself about market type X."""

    domains = _seed_recall_corpus(home)
    for query, domain_key in _RECALL_QUERIES:
        env = _mcp(home, "memory.recall", {"query": query, "k": 5})
        assert env.ok, env
        items = env.data["items"]
        assert items, f"no recall items for {query!r}"
        relevant = domains[domain_key]
        assert items[0]["id"] in relevant, (
            f"rank-0 recall for {query!r} is off-domain: got "
            f"{items[0]['id']}, relevant set {sorted(relevant)}"
        )


def test_recall_quality_relevant_set_dominates_top_k_default_stack(home):
    """On the live default stack, a query for market type X surfaces a
    MAJORITY of type-X nodes in the top-K (recall@k floor). A fusion or
    ranking regression that lets the off-domain distractors crowd the
    top-K below this floor fails the gate."""

    domains = _seed_recall_corpus(home)
    for query, domain_key in _RECALL_QUERIES:
        relevant = domains[domain_key]
        k = len(relevant)  # top-3 == size of the relevant set
        env = _mcp(home, "memory.recall", {"query": query, "k": k})
        assert env.ok, env
        returned = [it["id"] for it in env.data["items"]]
        hits = sum(1 for nid in returned if nid in relevant)
        # Strict majority of the top-K must be on-domain. With 3 relevant
        # vs 3 distractors this means >=2 of 3.
        assert hits >= (k // 2) + 1, (
            f"recall@{k} for {query!r} surfaced only {hits}/{k} on-domain "
            f"nodes; returned {returned}, relevant {sorted(relevant)}"
        )


def test_recall_quality_bm25_strict_lexical_precision(home):
    """On the strict lexical (BM25-only) stack, the top-N results (N =
    size of the relevant set) for a same-domain query are ALL relevant —
    no off-domain node outranks an on-domain one within the leading
    block. This pins precision of the lexical core that the default
    stack fuses; if BM25 ranking regresses, this trips even when the
    temporal/graph fallbacks would otherwise mask it."""

    domains = _seed_recall_corpus(home)
    for query, domain_key in _RECALL_QUERIES:
        relevant = domains[domain_key]
        n = len(relevant)
        env = _mcp(home, "memory.recall", {
            "query": query, "strategies": ["bm25"], "k": n,
        })
        assert env.ok, env
        returned = [it["id"] for it in env.data["items"]]
        assert len(returned) == n, (
            f"bm25 returned {len(returned)} items for {query!r}, expected {n}"
        )
        off_domain = [nid for nid in returned if nid not in relevant]
        assert not off_domain, (
            f"bm25 top-{n} for {query!r} leaked off-domain nodes "
            f"{off_domain}; returned {returned}, relevant {sorted(relevant)}"
        )


def test_recall_quality_mrr_floor_across_query_set(home):
    """Aggregate mean reciprocal rank over the fixed query set on the
    live default stack must meet a floor. MRR collapses the per-query
    'where does the first relevant node land' signal into one number; a
    broad recall regression (relevant nodes sinking deeper in every
    query) drops MRR below the floor and fails the gate even if no
    single per-query assertion above happens to catch it."""

    domains = _seed_recall_corpus(home)
    reciprocal_ranks: list[float] = []
    for query, domain_key in _RECALL_QUERIES:
        relevant = domains[domain_key]
        env = _mcp(home, "memory.recall", {"query": query, "k": 10})
        assert env.ok, env
        rank_of_first_relevant = None
        for rank, item in enumerate(env.data["items"], start=1):
            if item["id"] in relevant:
                rank_of_first_relevant = rank
                break
        assert rank_of_first_relevant is not None, (
            f"no relevant node anywhere in recall for {query!r}"
        )
        reciprocal_ranks.append(1.0 / rank_of_first_relevant)
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    # Every query currently lands a relevant node at rank 1 (MRR == 1.0);
    # the floor leaves headroom for a single query slipping to rank 2
    # before the gate trips, so the gate is a regression signal, not a
    # brittle exact-match.
    assert mrr >= 0.75, (
        f"recall-quality MRR {mrr:.3f} fell below the 0.75 floor; "
        f"per-query reciprocal ranks {reciprocal_ranks}"
    )


# --- Semantic cosine hoist (trade-trace-4xg1) ---------------------------------


def _cosine_reference(a: list[float], b: list[float]) -> float:
    """Pre-hoist `_cosine` formula, recomputing both norms every call.

    This is the exact arithmetic the loop used before the query-norm hoist;
    the new code must stay numerically equivalent to it.
    """

    if len(a) != len(b) or not a:
        return 0.0
    denom_a = sum(v * v for v in a) ** 0.5
    denom_b = sum(v * v for v in b) ** 0.5
    if denom_a == 0.0 or denom_b == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / (denom_a * denom_b)


_COSINE_CASES = [
    ([1.0, 0.0], [1.0, 0.0]),           # unit query, identical doc
    ([1.0, 0.0], [0.0, 1.0]),           # unit query, orthogonal doc
    ([0.6, 0.8], [0.8, 0.6]),           # unit query (norm 1), non-axis doc
    ([0.6, 0.8], [3.0, 4.0]),           # unit query, non-unit doc
    ([3.0, 4.0], [0.6, 0.8]),           # non-unit query (norm 5) safety case
    ([0.0, 0.0], [1.0, 1.0]),           # zero query -> 0.0
    ([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]),  # higher dim, both non-unit
]


@pytest.mark.parametrize(("query", "doc"), _COSINE_CASES)
def test_cosine_with_query_norm_matches_pre_hoist_formula(query, doc):
    expected = _cosine_reference(query, doc)
    norm = memory_tools._l2_norm(query)
    got = memory_tools._cosine_with_query_norm(query, norm, doc)
    assert got == expected
    # Public _cosine now delegates to the hoisted helper; it must be identical.
    assert memory_tools._cosine(query, doc) == expected


def test_cosine_with_query_norm_length_mismatch_is_zero():
    assert memory_tools._cosine_with_query_norm([1.0, 0.0], 1.0, [1.0]) == 0.0
    assert memory_tools._cosine_with_query_norm([], 0.0, [1.0]) == 0.0


def test_unit_query_cosine_reduces_to_dot_over_doc_norm():
    # For a unit query vector the score is exactly dot(query, doc) / ||doc||.
    query = [0.6, 0.8]  # ||query|| == 1.0
    doc = [3.0, 4.0]
    norm = memory_tools._l2_norm(query)
    assert norm == 1.0
    dot = sum(x * y for x, y in zip(query, doc, strict=True))
    expected = dot / memory_tools._l2_norm(doc)
    assert memory_tools._cosine_with_query_norm(query, norm, doc) == expected


def _semantic_rank_setup(monkeypatch, tmp_path: Path, docs, query_vec):
    """Seed two embeddings and return (_semantic_rank order, expected order
    under the pre-hoist cosine formula)."""

    from trade_trace.mcp_server import mcp_call

    home = tmp_path / "home"
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok, init

    ids: list[str] = []
    for i, _vec in enumerate(docs):
        env = mcp_call("memory.retain", {
            "home": str(home), "node_type": "observation",
            "body": f"doc {i}", "id": f"mem_doc_{i}",
            "idempotency_key": f"test:retain-doc-{i}",
        })
        assert env.ok, env
        ids.append(env.data["id"])

    dim = len(query_vec)
    monkeypatch.setattr(
        "trade_trace.storage.database.load_sqlite_vec_extension", lambda conn: None
    )
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            "INSERT INTO config(key, value, updated_at) VALUES "
            "('embeddings.provider', 'local', '2026-01-01T00:00:00Z') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        for node_id, vec in zip(ids, docs, strict=True):
            db.connection.execute(
                "INSERT INTO memory_node_embeddings"
                "(node_id, provider, dim, model_id, embedding, created_at) "
                "VALUES (?, 'local', ?, 'test-model', ?, '2026-01-01T00:00:00Z')",
                (node_id, dim, memory_tools._float32_blob(vec)),
            )
        db.connection.commit()
        monkeypatch.setattr(
            memory_tools, "_query_embedding", lambda *a, **k: list(query_vec)
        )
        in_scope = {node_id: {} for node_id in ids}
        ranked = memory_tools._semantic_rank(db.connection, "q", "local", in_scope)

        # Recompute expected order with the pre-hoist reference cosine on the
        # exact stored vectors (round-tripped through the blob, as the code does).
        reference_scored = [
            (
                node_id,
                _cosine_reference(
                    list(query_vec),
                    memory_tools._blob_to_float32(
                        memory_tools._float32_blob(vec), dim
                    ),
                ),
            )
            for node_id, vec in zip(ids, docs, strict=True)
        ]
    finally:
        db.close()

    reference_scored.sort(key=lambda r: (-r[1], r[0]))
    expected = [node_id for node_id, score in reference_scored if score > 0.0]
    return ranked, expected


def test_semantic_rank_equivalent_to_pre_hoist_cosine(monkeypatch, tmp_path: Path):
    # Three docs with distinct cosine similarities to a unit query vector; the
    # hoisted-norm ranking must match the pre-hoist per-call-norm ranking.
    query_vec = [0.6, 0.8]  # unit vector
    docs = [
        [0.0, 1.0],   # cos ~0.8
        [1.0, 0.0],   # cos ~0.6
        [0.6, 0.8],   # cos 1.0 (identical)
    ]
    ranked, expected = _semantic_rank_setup(monkeypatch, tmp_path, docs, query_vec)
    assert ranked == expected
    assert len(ranked) == 3  # all positive cosine


def test_semantic_rank_drops_non_positive_scores(monkeypatch, tmp_path: Path):
    # An orthogonal doc scores 0.0 and must be excluded, matching the reference.
    query_vec = [1.0, 0.0]
    docs = [
        [1.0, 0.0],   # cos 1.0
        [0.0, 1.0],   # cos 0.0 -> dropped
    ]
    ranked, expected = _semantic_rank_setup(monkeypatch, tmp_path, docs, query_vec)
    assert ranked == expected
    assert len(ranked) == 1
