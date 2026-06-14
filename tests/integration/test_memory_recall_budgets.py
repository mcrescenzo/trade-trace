"""memory.recall budget / provenance knobs per bead trade-trace-5n4.

Five filterable budget surfaces: k, max_chars, compact, include_body,
include_provenance, min_confidence. Each test exercises one knob and
asserts the documented effect.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.storage.paths import db_path

# A valid graph entrypoint (kind+id) that no seeded node is linked to.
# Per bead trade-trace-2iug the graph strategy abstains (returns []) when
# given no context, but with a context that has zero connected nodes it
# falls through to `rest = sorted(in_scope)` — i.e. the full in-scope
# corpus in deterministic id order. The budget/shaping tests below use this
# as a stable full-corpus fixture without depending on the no-context
# abstain path (trade-trace-2auq).
_GRAPH_CTX_NO_LINKS: dict[str, str] = {"kind": "instrument", "id": "ins_pz23_unlinked"}


def _seed_node(home: Path, node_id: str, body: str, *, confidence: float = 1.0) -> str:
    return _mcp(home, "memory.retain", {
        "id": node_id,
        "node_type": "observation",
        "body": body,
        "confidence_base": confidence,
        "idempotency_key": f"00000000-0000-4000-8000-{node_id[-12:]}",
    }).data["id"]


def _last_recall_node_ids(home: Path) -> list[str]:
    with sqlite3.connect(db_path(home)) as conn:
        row = conn.execute(
            "SELECT node_ids_returned FROM memory_recall_events ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    return json.loads(row[0])


def _stats_counts(home: Path) -> dict[str, int]:
    with sqlite3.connect(db_path(home)) as conn:
        return dict(conn.execute("SELECT node_id, recall_count FROM memory_node_stats").fetchall())


def _seed_n_nodes(home: Path, n: int, *, body_prefix: str = "obs",
                  confidence: float | None = None) -> list[str]:
    ids: list[str] = []
    for i in range(n):
        args: dict[str, object] = {
            "node_type": "observation",
            "body": f"{body_prefix} #{i} — earnings volatility pattern",
            "idempotency_key": f"00000000-0000-4000-8000-budget-{i:08d}",
        }
        if confidence is not None:
            args["confidence_base"] = confidence
        ids.append(_mcp(home, "memory.retain", args).data["id"])
    return ids


# -- k --------------------------------------------------------------


def test_k_limits_returned_items(home):
    _seed_n_nodes(home, 5)
    env = _mcp(home, "memory.recall", {"query": "earnings", "k": 3})
    assert env.ok
    assert len(env.data["items"]) <= 3


def test_k_rejects_out_of_range(home):
    env = _mcp(home, "memory.recall", {"query": "x", "k": 0})
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"


# -- max_chars + compact -------------------------------------------


def test_max_chars_truncates_response_aggregate(home):
    _seed_n_nodes(home, 5, body_prefix="this-is-a-fairly-long-body-fragment")
    env = _mcp(home, "memory.recall", {
        "query": "earnings", "k": 10, "max_chars": 50,
    })
    assert env.ok
    total = sum(len(it.get("body", "")) for it in env.data["items"])
    assert total <= 50


def test_compact_truncates_each_body(home):
    long_body = "X" * 500
    _mcp(home, "memory.retain", {
        "node_type": "observation", "body": long_body,
        "idempotency_key": "00000000-0000-4000-8000-compact-long",
    })
    env = _mcp(home, "memory.recall", {
        "query": "XX", "k": 1, "compact": True,
    })
    assert env.ok
    item = env.data["items"][0]
    assert len(item["body"]) <= 120


# -- include_body / include_provenance ----------------------------


def test_include_body_false_omits_body(home):
    _seed_n_nodes(home, 2)
    env = _mcp(home, "memory.recall", {
        "query": "earnings", "k": 2, "include_body": False,
    })
    assert env.ok
    for item in env.data["items"]:
        assert "body" not in item


def test_include_provenance_false_omits_strategy_provenance(home):
    _seed_n_nodes(home, 2)
    env = _mcp(home, "memory.recall", {
        "query": "earnings", "k": 2, "include_provenance": False,
    })
    assert env.ok
    for item in env.data["items"]:
        assert "strategy_provenance" not in item


# -- min_confidence -----------------------------------------------


def test_min_confidence_filters_below_threshold(home):
    high = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "high confidence observation",
        "confidence_base": 0.9,
        "idempotency_key": "00000000-0000-4000-8000-conf-high1",
    }).data["id"]
    low = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "low confidence observation",
        "confidence_base": 0.1,
        "idempotency_key": "00000000-0000-4000-8000-conf-low01",
    }).data["id"]
    env = _mcp(home, "memory.recall", {
        "query": "confidence observation", "k": 10, "min_confidence": 0.5,
    })
    assert env.ok
    ids = [it["id"] for it in env.data["items"]]
    assert high in ids
    assert low not in ids


def test_min_confidence_rejects_out_of_range(home):
    env = _mcp(home, "memory.recall", {
        "query": "x", "min_confidence": 1.5,
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"


# -- node_types filter ----------------------------------------------


def test_node_types_filter_narrows_to_subset(home):
    """`node_types=['playbook_rule']` should restrict recall to nodes
    of that type only — per memory-layer.md §7.4."""

    obs = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "observation about earnings",
        "idempotency_key": "00000000-0000-4000-8000-nt-obs01",
    }).data["id"]
    rule = _mcp(home, "memory.retain", {
        "node_type": "playbook_rule", "body": "rule about earnings",
        "idempotency_key": "00000000-0000-4000-8000-nt-rul01",
    }).data["id"]
    env = _mcp(home, "memory.recall", {
        "query": "earnings", "k": 10, "node_types": ["playbook_rule"],
    })
    assert env.ok
    ids = [it["id"] for it in env.data["items"]]
    assert rule in ids
    assert obs not in ids


def test_node_types_rejects_invalid_value(home):
    env = _mcp(home, "memory.recall", {
        "query": "x", "node_types": ["musing"],
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "node_types"


# -- mode='per_strategy' return shape ------------------------------


def test_mode_per_strategy_returns_per_strategy_lists(home):
    """`mode='per_strategy'` adds a `per_strategy` dict with one list
    per active retrieval strategy, capped at `k`."""

    _seed_n_nodes(home, 3, body_prefix="mode-test-body")
    env = _mcp(home, "memory.recall", {
        "query": "mode-test", "k": 5, "mode": "per_strategy",
    })
    assert env.ok
    assert env.data["mode"] == "per_strategy"
    assert "per_strategy" in env.data
    # Every requested strategy is keyed; values are lists of node ids.
    for strategy, ranked in env.data["per_strategy"].items():
        assert strategy in ("bm25", "temporal", "graph")
        assert isinstance(ranked, list)
        assert all(isinstance(nid, str) for nid in ranked)
        assert len(ranked) <= 5


def test_mode_fused_default_omits_per_strategy_block(home):
    _seed_n_nodes(home, 2, body_prefix="mode-default")
    env = _mcp(home, "memory.recall", {"query": "mode-default", "k": 3})
    assert env.ok
    assert env.data["mode"] == "fused"
    assert "per_strategy" not in env.data


# -- ordering characterizations for recall decomposition ------------

def test_min_confidence_applies_after_top_k_selection(home):
    _seed_node(home, "mem_pz23_conf_a", "alpha low confidence", confidence=0.1)
    _seed_node(home, "mem_pz23_conf_b", "beta high confidence", confidence=0.9)

    env = _mcp(home, "memory.recall", {
        "query": "", "strategies": ["graph"], "k": 1, "min_confidence": 0.5,
    })

    assert env.ok
    assert [it["id"] for it in env.data["items"]] == []


def test_compact_applies_before_max_chars(home):
    first = _seed_node(home, "mem_pz23_compact_a", "A" * 500)
    _seed_node(home, "mem_pz23_compact_b", "B" * 10)

    env = _mcp(home, "memory.recall", {
        "query": "", "strategies": ["graph"], "context": _GRAPH_CTX_NO_LINKS,
        "k": 2, "compact": True, "max_chars": 120,
    })

    assert env.ok
    assert [it["id"] for it in env.data["items"]] == [first]
    assert len(env.data["items"][0]["body"]) == 120


def test_max_chars_stops_at_first_overflow_without_skipping_later_smaller_items(home):
    first = _seed_node(home, "mem_pz23_overflow_a", "A" * 10)
    _seed_node(home, "mem_pz23_overflow_b", "B" * 500)
    _seed_node(home, "mem_pz23_overflow_c", "C" * 10)

    env = _mcp(home, "memory.recall", {
        "query": "", "strategies": ["graph"], "context": _GRAPH_CTX_NO_LINKS,
        "k": 3, "max_chars": 20,
    })

    assert env.ok
    assert [it["id"] for it in env.data["items"]] == [first]


def test_max_chars_applies_even_when_include_body_false(home):
    _seed_node(home, "mem_pz23_nobody_a", "A" * 500)
    _seed_node(home, "mem_pz23_nobody_b", "B" * 10)

    env = _mcp(home, "memory.recall", {
        "query": "", "strategies": ["graph"], "k": 2,
        "max_chars": 20, "include_body": False,
    })

    assert env.ok
    assert env.data["items"] == []


def test_per_strategy_lists_are_raw_and_not_confidence_or_budget_filtered(home):
    low = _seed_node(home, "mem_pz23_raw_a", "A" * 500, confidence=0.1)
    high = _seed_node(home, "mem_pz23_raw_b", "B" * 10, confidence=0.9)

    env = _mcp(home, "memory.recall", {
        "query": "", "strategies": ["graph"], "context": _GRAPH_CTX_NO_LINKS,
        "k": 2, "mode": "per_strategy",
        "min_confidence": 0.5, "max_chars": 5,
    })

    assert env.ok
    assert env.data["items"] == []
    assert env.data["per_strategy"] == {"graph": [low, high]}


def test_recall_events_and_stats_count_only_emitted_item_ids_after_filters(home):
    kept = _seed_node(home, "mem_pz23_stats_a", "A" * 10, confidence=0.9)
    _seed_node(home, "mem_pz23_stats_b", "B" * 500, confidence=0.9)
    _seed_node(home, "mem_pz23_stats_c", "C" * 10, confidence=0.9)

    env = _mcp(home, "memory.recall", {
        "query": "", "strategies": ["graph"], "context": _GRAPH_CTX_NO_LINKS,
        "k": 3, "max_chars": 20,
    })

    assert env.ok
    assert [it["id"] for it in env.data["items"]] == [kept]
    assert _last_recall_node_ids(home) == [kept]
    assert _stats_counts(home) == {kept: 1}


# -- batched source_refs (trade-trace-jd0x) -------------------------
#
# `_shape_recall_items` previously issued one `_source_refs_for` query
# per returned item (N+1, up to k=100 round-trips). It now collects the
# final node_ids and fetches every edge in a single `IN (...)` query via
# `_source_refs_batch`. These tests pin the batched helper's behavior
# (empty set, duplicate ids, no-edge nodes, byte-identical ordering vs.
# the per-node path) and assert the recall response is unchanged.


def _insert_edge(conn, *, edge_id, source_id, target_kind, target_id, edge_type, created_at):
    conn.execute(
        "INSERT INTO edges (id, source_kind, source_id, target_kind, target_id, "
        "edge_type, weight, metadata_json, created_at, actor_id) "
        "VALUES (?, 'memory_node', ?, ?, ?, ?, NULL, '{}', ?, 'actor')",
        (edge_id, source_id, target_kind, target_id, edge_type, created_at),
    )


def test_source_refs_batch_empty_input_returns_empty_dict(home):
    from trade_trace.tools.memory import _source_refs_batch

    with sqlite3.connect(db_path(home)) as conn:
        assert _source_refs_batch(conn, []) == {}


def test_source_refs_batch_seeds_every_id_even_with_no_edges(home):
    from trade_trace.tools.memory import _source_refs_batch

    with sqlite3.connect(db_path(home)) as conn:
        # No edges exist for these ids; every requested id must still map
        # to an empty list (so the recall item gets `source_refs: []`).
        assert _source_refs_batch(conn, ["mem_a", "mem_b"]) == {
            "mem_a": [],
            "mem_b": [],
        }


def test_source_refs_batch_dedupes_duplicate_node_ids(home):
    from trade_trace.tools.memory import _source_refs_batch

    with sqlite3.connect(db_path(home)) as conn:
        _insert_edge(
            conn, edge_id="e1", source_id="mem_dup", target_kind="source",
            target_id="src_1", edge_type="about", created_at="2026-01-01T00:00:00Z",
        )
        out = _source_refs_batch(conn, ["mem_dup", "mem_dup", "mem_dup"])

    # Duplicates collapse to a single key with a single (un-duplicated)
    # edge list — the IN-list params are de-duped before the query.
    assert out == {
        "mem_dup": [{"target_kind": "source", "target_id": "src_1", "edge_type": "about"}],
    }


def test_source_refs_batch_matches_per_node_helper_byte_for_byte(home):
    from trade_trace.tools.memory import _source_refs_batch, _source_refs_for

    with sqlite3.connect(db_path(home)) as conn:
        # Insert edges out of the final sort order to prove the batched
        # query's `ORDER BY source_id, edge_type, target_kind, target_id`
        # reproduces the per-node `edge_type, target_kind, target_id` order.
        _insert_edge(conn, edge_id="e1", source_id="mem_x", target_kind="thesis",
                     target_id="th_2", edge_type="supports", created_at="2026-01-01T00:00:03Z")
        _insert_edge(conn, edge_id="e2", source_id="mem_x", target_kind="source",
                     target_id="src_9", edge_type="about", created_at="2026-01-01T00:00:02Z")
        _insert_edge(conn, edge_id="e3", source_id="mem_x", target_kind="source",
                     target_id="src_1", edge_type="about", created_at="2026-01-01T00:00:01Z")
        _insert_edge(conn, edge_id="e4", source_id="mem_y", target_kind="decision",
                     target_id="dec_1", edge_type="violates", created_at="2026-01-01T00:00:04Z")

        node_ids = ["mem_x", "mem_y", "mem_empty"]
        batched = _source_refs_batch(conn, node_ids)
        per_node = {nid: _source_refs_for(conn, nid) for nid in node_ids}

    assert batched == per_node
    # Spell out the expected per-node ordering explicitly so a future
    # ORDER BY regression is caught here, not just by the equivalence.
    assert batched["mem_x"] == [
        {"target_kind": "source", "target_id": "src_1", "edge_type": "about"},
        {"target_kind": "source", "target_id": "src_9", "edge_type": "about"},
        {"target_kind": "thesis", "target_id": "th_2", "edge_type": "supports"},
    ]
    assert batched["mem_empty"] == []


def test_recall_source_refs_match_per_node_helper(home):
    """End-to-end: the recall response's per-item `source_refs` is
    byte-identical to what the per-node `_source_refs_for` helper would
    produce for each returned node (batched path equivalence)."""

    from trade_trace.tools.memory import _source_refs_for

    nid = _seed_node(home, "mem_pz23_refs_a", "earnings refs body")
    with sqlite3.connect(db_path(home)) as conn:
        _insert_edge(conn, edge_id="er1", source_id=nid, target_kind="source",
                     target_id="src_b", edge_type="about", created_at="2026-01-01T00:00:02Z")
        _insert_edge(conn, edge_id="er2", source_id=nid, target_kind="source",
                     target_id="src_a", edge_type="about", created_at="2026-01-01T00:00:01Z")
        conn.commit()
        expected = _source_refs_for(conn, nid)

    env = _mcp(home, "memory.recall", {"query": "earnings refs", "k": 5})
    assert env.ok
    item = next((it for it in env.data["items"] if it["id"] == nid), None)
    assert item is not None, env.data
    assert item["source_refs"] == expected
    # The edge_type/target ordering must be the deterministic batched order.
    assert item["source_refs"] == [
        {"target_kind": "source", "target_id": "src_a", "edge_type": "about"},
        {"target_kind": "source", "target_id": "src_b", "edge_type": "about"},
    ]


def test_shape_recall_items_issues_one_edges_query_regardless_of_k(home):
    """trade-trace-jb3q: `_shape_recall_items` must batch the per-item
    source_refs fetch into a SINGLE edges query, not one round-trip per
    returned node. The byte-for-byte parity tests above would still pass
    under the old N+1 loop (correctness is unchanged); this test is the
    regression guard that pins the *query count* so re-introducing the
    per-item `_source_refs_for` call inside the loop fails CI.

    We shape three items (each carrying its own provenance edges) against
    a trace-instrumented connection and assert exactly one `FROM edges`
    SELECT is issued. The old path would have fired three."""

    from trade_trace.tools.memory import (
        RecallOptions,
        _load_in_scope_nodes,
        _shape_recall_items,
    )

    node_ids = [
        _seed_node(home, "mem_pz23_qc_a", "earnings qc body a"),
        _seed_node(home, "mem_pz23_qc_b", "earnings qc body b"),
        _seed_node(home, "mem_pz23_qc_c", "earnings qc body c"),
    ]
    with sqlite3.connect(db_path(home)) as conn:
        # Every returned node has at least one outgoing edge, so the old
        # per-item path would issue one edges query per node (an N+1).
        for i, nid in enumerate(node_ids):
            _insert_edge(
                conn, edge_id=f"qce{i}", source_id=nid, target_kind="source",
                target_id=f"src_qc_{i}", edge_type="about",
                created_at=f"2026-01-01T00:00:0{i}Z",
            )
        conn.commit()

    options = RecallOptions(
        query="earnings qc", limit_k=10, max_chars=None, compact=False,
        include_body=True, include_provenance=True, min_confidence=None,
        node_types=None, mode="fused", as_of=None,
        requested_strategies=["bm25", "temporal", "graph"], context={},
    )

    edges_query_count = 0

    def _trace(sql: str) -> None:
        nonlocal edges_query_count
        if "from edges" in sql.lower():
            edges_query_count += 1

    with sqlite3.connect(db_path(home)) as conn:
        in_scope_rows = _load_in_scope_nodes(conn, as_of=options.as_of)
        scored_top = [(nid, 1.0 - idx * 0.01, {}) for idx, nid in enumerate(node_ids)]
        conn.set_trace_callback(_trace)
        items, _chars = _shape_recall_items(conn, scored_top, in_scope_rows, options)
        conn.set_trace_callback(None)

    # All three nodes shaped (sanity) and exactly ONE edges query for the
    # whole batch — a per-item path would have issued three.
    assert [it["id"] for it in items] == node_ids, items
    assert edges_query_count == 1, edges_query_count
    # The batched refs landed on each item (shape preserved).
    for i, it in enumerate(items):
        assert it["source_refs"] == [
            {"target_kind": "source", "target_id": f"src_qc_{i}", "edge_type": "about"},
        ], it
