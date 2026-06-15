"""MVP retrieval constants locked per bead trade-trace-tem.

Verifies that the three recall constants ship at their committed
values and produce the expected behavior:

- `K_RRF = 60`  (reciprocal-rank-fusion denominator)
- `IMPORTANCE_BOOST_SLOPE = 0.05` (linear: importance=1 → 0.80, =5 → 1.00,
  =10 → 1.25)
- `SUPERSESSION_DISCOUNT = 0.25` (a superseded node's RRF score is
  multiplied by 0.25 before final ranking)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.tools._helpers import CLOCK_OVERRIDE
from trade_trace.tools.memory import (
    IMPORTANCE_BOOST_SLOPE,
    K_RRF,
    MIN_RECALL_RANKING_CANDIDATES,
    RECALL_RANKING_CANDIDATE_MULTIPLIER,
    SUPERSESSION_DISCOUNT,
    _recall_candidate_limit,
    _rrf_combine,
    _temporal_rank,
)

# -- 1. pinned constant values ------------------------------------


def test_k_rrf_locked_at_60():
    assert K_RRF == 60


def test_importance_boost_slope_locked():
    assert IMPORTANCE_BOOST_SLOPE == 0.05


def test_supersession_discount_locked_at_quarter():
    assert SUPERSESSION_DISCOUNT == 0.25


def test_recall_candidate_window_constants_locked():
    assert MIN_RECALL_RANKING_CANDIDATES == 100
    assert RECALL_RANKING_CANDIDATE_MULTIPLIER == 10
    assert _recall_candidate_limit(k=1, corpus_size=1000) == 100
    assert _recall_candidate_limit(k=25, corpus_size=1000) == 250
    assert _recall_candidate_limit(k=25, corpus_size=40) == 40


# -- 2. importance boost at boundaries ----------------------------


@pytest.mark.parametrize(
    "importance,expected",
    [(1, 0.80), (3, 0.90), (5, 1.00), (7, 1.10), (10, 1.25)],
)
def test_importance_boost_formula(importance, expected):
    """The boost is linear: 1.0 + (importance - 5) * 0.05.
    Pinning the three boundary points (1, 5, 10) is the contract."""

    boost = 1.0 + (importance - 5) * IMPORTANCE_BOOST_SLOPE
    assert boost == pytest.approx(expected)


# -- 3. RRF combination matches manual computation ----------------


def test_rrf_two_strategies_three_nodes_manual_check():
    """Two strategies rank three nodes (1, 2, 3) each:

      bm25:     [n1, n2, n3]
      temporal: [n3, n2, n1]

    RRF scores per node:
      n1: 1/(60+1) + 1/(60+3) = 1/61 + 1/63
      n2: 1/(60+2) + 1/(60+2) = 2/62
      n3: 1/(60+3) + 1/(60+1) = 1/63 + 1/61

    n1 and n3 tie; n2 sits between or alongside them depending on
    floating-point precision, but ordering is stable on tie via id.
    """

    rankings = {
        "bm25": ["n1", "n2", "n3"],
        "temporal": ["n3", "n2", "n1"],
    }
    combined = _rrf_combine(rankings)
    by_id = {nid: score for nid, score, _prov in combined}
    expected_n1 = 1.0 / (60 + 1) + 1.0 / (60 + 3)
    expected_n2 = 2.0 / (60 + 2)
    expected_n3 = 1.0 / (60 + 3) + 1.0 / (60 + 1)
    assert by_id["n1"] == pytest.approx(expected_n1)
    assert by_id["n2"] == pytest.approx(expected_n2)
    assert by_id["n3"] == pytest.approx(expected_n3)


def test_rrf_provenance_records_per_strategy_ranks():
    """The provenance dict carries the 1-indexed rank in each strategy
    so the agent can drill into why a node ranked where it did."""

    rankings = {
        "bm25": ["n1", "n2"],
        "graph": ["n2", "n1"],
    }
    combined = _rrf_combine(rankings)
    by_id = {nid: prov for nid, _score, prov in combined}
    assert by_id["n1"]["bm25"] == [1]
    assert by_id["n1"]["graph"] == [2]
    assert by_id["n2"]["bm25"] == [2]
    assert by_id["n2"]["graph"] == [1]


def test_rrf_combine_empty_rankings_returns_empty():
    """trade-trace-5eh3 / nyix(15): RRF over no strategies, and over strategies
    that all returned empty rankings, must produce an empty fused list — no
    accumulator keys, no provenance, no crash. This pins the degenerate path
    that runs whenever every strategy abstains (e.g. an empty corpus)."""

    assert _rrf_combine({}) == []
    assert _rrf_combine({"bm25": []}) == []
    assert _rrf_combine({"bm25": [], "temporal": [], "graph": []}) == []


def test_rrf_combine_limit_returns_deterministic_top_k():
    rankings = {
        "bm25": ["n1", "n2", "n3", "n4"],
        "temporal": ["n4", "n2", "n3", "n1"],
    }

    limited = _rrf_combine(rankings, limit=2)
    full = _rrf_combine(rankings)

    assert limited == full[:2]


def test_temporal_rank_limit_returns_deterministic_top_k():
    rows = {
        "old": {"created_at": "2026-01-01T00:00:00Z"},
        "near-b": {"created_at": "2026-01-03T00:00:00Z"},
        "near-a": {"created_at": "2026-01-03T00:00:00Z"},
        "future": {"created_at": "2026-01-05T00:00:00Z"},
    }

    ranked = _temporal_rank(rows, as_of="2026-01-03T00:00:00Z", limit=2)

    assert ranked == ["near-a", "near-b"]


# -- 4. supersession discount: relative score effect --------------


def test_supersession_discount_is_quarter():
    """A discounted score should be exactly 0.25× the pre-discount value."""

    base = 0.123456
    assert base * SUPERSESSION_DISCOUNT == pytest.approx(base * 0.25)


# -- 5. Final declarations cannot be mutated at type-check time ---


def test_constants_module_exports_pinned_values():
    """The constants module surfaces all three names with their pinned
    values so a tooling consumer can `from trade_trace.tools.memory
    import K_RRF, IMPORTANCE_BOOST_SLOPE, SUPERSESSION_DISCOUNT`."""

    from trade_trace.tools import memory

    assert memory.K_RRF == 60
    assert memory.IMPORTANCE_BOOST_SLOPE == 0.05
    assert memory.SUPERSESSION_DISCOUNT == 0.25


# -- 6. supersession discount is bi-temporally gated on as_of -----
#
# Regression for trade-trace-lhaf: _superseded_node_ids ignored the
# recall's `as_of`, so SUPERSESSION_DISCOUNT (0.25x) was applied to a
# node even on a historical recall whose point-in-time PRE-DATES the
# supersedes edge. _load_in_scope_nodes already gates valid_from /
# valid_to / invalidated_at on `as_of`; the supersedes-edge query must
# be symmetric.


def _retain_at(home, when, *, body, key):
    """memory.retain a node at a frozen clock with valid_from pinned to
    the same instant, so it is in-scope for any `as_of` >= `when`."""

    token = CLOCK_OVERRIDE.set(when)
    try:
        env = _mcp(home, "memory.retain", {
            "node_type": "observation", "body": body,
            "valid_from": when.isoformat(),
            "idempotency_key": key,
        })
    finally:
        CLOCK_OVERRIDE.reset(token)
    assert env.ok, env
    return env.data["id"]


def _supersedes_at(home, when, *, source_id, target_id, key):
    """Write a supersedes edge source->target at a frozen clock so the
    edge's `created_at` equals `when`."""

    token = CLOCK_OVERRIDE.set(when)
    try:
        env = _mcp(home, "memory.link", {
            "source_kind": "memory_node", "source_id": source_id,
            "target_kind": "memory_node", "target_id": target_id,
            "edge_type": "supersedes",
            "idempotency_key": key,
        })
    finally:
        CLOCK_OVERRIDE.reset(token)
    assert env.ok, env


def _recall_score(home, when, *, query, as_of, node_id):
    """Run memory.recall at frozen clock `when` and return node_id's
    item score (or None if it did not surface)."""

    token = CLOCK_OVERRIDE.set(when)
    try:
        env = _mcp(home, "memory.recall", {
            "query": query, "k": 25, "as_of": as_of,
            "strategies": ["bm25"],
        })
    finally:
        CLOCK_OVERRIDE.reset(token)
    assert env.ok, env
    for item in env.data["items"]:
        if item["id"] == node_id:
            return item["score"]
    return None


def test_supersession_discount_not_applied_before_supersedes_edge(home):
    """A historical `as_of` recall must NOT discount a node whose
    supersedes edge POST-DATES that point-in-time. The superseding node
    and the superseded node are both written in the past (in-scope), but
    the supersedes edge is written later; a recall as_of a moment BEFORE
    the edge sees the superseded node at full (undiscounted) score,
    while a recall as_of a moment AFTER the edge sees it discounted."""

    past = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    edge_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Shared keyword so both nodes surface via bm25; node_b is the
    # supersedes TARGET (the node that gets discounted once superseded).
    node_a = _retain_at(home, past, body="alpha quokka winning thesis newer", key="lhaf-node-a")
    node_b = _retain_at(home, past, body="alpha quokka winning thesis older", key="lhaf-node-b")
    _supersedes_at(home, edge_at, source_id=node_a, target_id=node_b, key="lhaf-supersedes-edge")

    # Recall AS OF a point BEFORE the supersedes edge: node_b is NOT yet
    # superseded, so no discount.
    score_before = _recall_score(
        home, now, query="quokka", as_of="2025-06-01T00:00:00Z", node_id=node_b,
    )
    # Recall AS OF a point AFTER the supersedes edge: node_b IS superseded,
    # so the 0.25x discount applies.
    score_after = _recall_score(
        home, now, query="quokka", as_of="2026-06-01T00:00:00Z", node_id=node_b,
    )

    assert score_before is not None, "node_b should be in-scope for the historical recall"
    assert score_after is not None, "node_b should be in-scope for the present recall"
    # The pre-edge recall must NOT discount; the post-edge recall must.
    # With identical bm25 ranking the only difference is the 0.25x factor,
    # so the discounted score is a quarter of the undiscounted one. The
    # item `score` is independently rounded to 6 decimals on each recall
    # (memory.py _shape_recall_items), so compare with a relative tolerance
    # rather than asserting bit-exact equality.
    assert score_after == pytest.approx(score_before * SUPERSESSION_DISCOUNT, rel=1e-4)
    assert score_before > score_after


def test_supersession_discount_query_gates_on_created_at():
    """Unit-level guard on the gated query helper: with an explicit
    `as_of`, only supersedes edges whose `created_at <= as_of` count;
    `as_of=None` returns every supersedes target (current behavior)."""

    import sqlite3

    from trade_trace.tools.memory import _superseded_node_ids

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE edges (
            source_kind TEXT, source_id TEXT,
            target_kind TEXT, target_id TEXT,
            edge_type TEXT, created_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO edges VALUES ('memory_node','a','memory_node','b','supersedes','2026-01-01T00:00:00Z')",
    )

    # as_of BEFORE the edge: b is not yet superseded.
    assert _superseded_node_ids(conn, as_of="2025-06-01T00:00:00Z") == set()
    # as_of AFTER (or equal to) the edge: b is superseded.
    assert _superseded_node_ids(conn, as_of="2026-06-01T00:00:00Z") == {"b"}
    assert _superseded_node_ids(conn, as_of="2026-01-01T00:00:00Z") == {"b"}
    # as_of=None: every supersedes target counts (recall reflects "now").
    assert _superseded_node_ids(conn, as_of=None) == {"b"}
    assert _superseded_node_ids(conn) == {"b"}


# -- 7. decay_rate_per_day gates the min_confidence filter --------
#
# Contract for trade-trace-bino. memory-layer.md §6 specifies that at
# recall time a node's effective confidence is
#   confidence_base * exp(-decay_rate_per_day * age_days)
# and that the `min_confidence` filter compares against THIS decayed
# value, not the raw stored `confidence_base`. Previously
# `decay_rate_per_day` was stored and loaded but never read at query
# time, so `min_confidence` compared the raw base — a silent no-op for
# the field. These tests pin both halves of the contract: a high-decay
# node drops below the threshold once enough wall-clock time has
# elapsed, and a node with no decay (or sub-day age) retrieves with
# exactly its stored confidence_base.


def _retain_decay_at(home, when, *, body, key, confidence_base, decay_rate_per_day=None):
    """memory.retain a node at a frozen clock with valid_from pinned to
    the same instant, carrying an explicit confidence_base and optional
    decay_rate_per_day, so it is in-scope for any `as_of` >= `when`."""

    args = {
        "node_type": "observation", "body": body,
        "valid_from": when.isoformat(),
        "confidence_base": confidence_base,
        "idempotency_key": key,
    }
    if decay_rate_per_day is not None:
        args["decay_rate_per_day"] = decay_rate_per_day
    token = CLOCK_OVERRIDE.set(when)
    try:
        env = _mcp(home, "memory.retain", args)
    finally:
        CLOCK_OVERRIDE.reset(token)
    assert env.ok, env
    return env.data["id"]


def _recall_returns(home, when, *, query, as_of, min_confidence, node_id):
    """Run memory.recall at frozen clock `when` with a min_confidence
    floor; return True iff `node_id` survives the filter."""

    token = CLOCK_OVERRIDE.set(when)
    try:
        env = _mcp(home, "memory.recall", {
            "query": query, "k": 25, "as_of": as_of,
            "strategies": ["bm25"], "min_confidence": min_confidence,
        })
    finally:
        CLOCK_OVERRIDE.reset(token)
    assert env.ok, env
    return any(item["id"] == node_id for item in env.data["items"])


def test_high_decay_node_drops_below_min_confidence_after_elapsed_time(home):
    """A node with a high decay_rate_per_day surfaces under min_confidence
    when freshly written but is filtered out once enough days elapse —
    while an otherwise-identical no-decay node with the same base stays
    above the floor. This proves decay is actually applied at query time."""

    born = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    # confidence_base 0.9, decay 0.1/day. min_confidence floor 0.5.
    # age 0  -> 0.9                       (>= 0.5, surfaces)
    # age 30 -> 0.9 * exp(-3.0) ~= 0.0448 (<  0.5, filtered)
    decaying = _retain_decay_at(
        home, born, body="kestrel mispricing thesis decaying",
        key="bino-decay-hi", confidence_base=0.9, decay_rate_per_day=0.1,
    )
    durable = _retain_decay_at(
        home, born, body="kestrel mispricing thesis durable",
        key="bino-decay-zero", confidence_base=0.9, decay_rate_per_day=0.0,
    )

    fresh = datetime(2026, 1, 1, 18, 0, 0, tzinfo=UTC)   # same day
    later = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)   # ~59 days later

    # Same-day recall: high-decay node is essentially undecayed and clears
    # the floor.
    assert _recall_returns(
        home, fresh, query="kestrel", as_of=fresh.isoformat(),
        min_confidence=0.5, node_id=decaying,
    ), "high-decay node should clear min_confidence while still fresh"

    # ~59 days later: high-decay node has decayed below the floor and is
    # filtered out, while the no-decay node with the same base remains.
    assert not _recall_returns(
        home, later, query="kestrel", as_of=later.isoformat(),
        min_confidence=0.5, node_id=decaying,
    ), "high-decay node should fall below min_confidence after elapsed time"
    assert _recall_returns(
        home, later, query="kestrel", as_of=later.isoformat(),
        min_confidence=0.5, node_id=durable,
    ), "no-decay node with the same base must NOT be filtered by elapsed time"


def test_no_decay_node_retrieves_at_stored_confidence_base(home):
    """Pin the no-decay path: a node with decay_rate_per_day=0.0 retrieves
    at exactly its stored confidence_base regardless of elapsed time. A
    min_confidence floor at the base passes; a floor just above it fails —
    decay does not nudge the effective confidence in either direction."""

    born = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    node = _retain_decay_at(
        home, born, body="osprey durable belief no decay",
        key="bino-nodecay", confidence_base=0.6, decay_rate_per_day=0.0,
    )

    # Years later, with a min_confidence floor AT the stored base, the node
    # still surfaces — no decay has eroded its confidence.
    way_later = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    assert _recall_returns(
        home, way_later, query="osprey", as_of=way_later.isoformat(),
        min_confidence=0.6, node_id=node,
    ), "no-decay node must retrieve at exactly its stored confidence_base"
    # A floor just above the stored base filters it — confirming the gate
    # compares against 0.6 exactly, not a value perturbed by elapsed time.
    assert not _recall_returns(
        home, way_later, query="osprey", as_of=way_later.isoformat(),
        min_confidence=0.61, node_id=node,
    ), "no-decay node's effective confidence is its stored base, unchanged by time"


# -- 8. _semantic_rank pushes in_scope into the DB scan -----------
#
# Regression for trade-trace-zsi8: _semantic_rank's SELECT on
# memory_node_embeddings was `WHERE provider = ?` with no in_scope
# predicate, so every stored embedding blob for the provider was
# transferred into Python and out-of-scope rows were discarded by an
# `if node_id not in in_scope: continue` guard. For 10k nodes with
# 384-dim float32 embeddings that is ~15 MB of blobs materialized even
# when only a handful are in scope. The fix pushes in_scope into the
# scan via `node_id IN (...)`; these tests pin that out-of-scope blobs
# are never fetched AND that ranking results are unchanged.


def _embedding_blob(vec):
    import struct

    return struct.pack(f"<{len(vec)}f", *vec)


def _semantic_rank_test_db():
    """In-memory DB with a memory_node_embeddings table and three local
    embeddings: two in-scope (a, b) and one out-of-scope (z)."""

    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE memory_node_embeddings (
            node_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            dim INTEGER NOT NULL,
            model_id TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (node_id, provider, model_id)
        )
        """
    )
    dim, model_id = 3, "bge-small-en-v1.5"
    rows = {
        # node_id -> embedding vector (dim 3, already L2-friendly)
        "a": [1.0, 0.0, 0.0],   # in-scope, aligned with the query (cos 1.0)
        "b": [0.0, 1.0, 0.0],   # in-scope, orthogonal to the query (cos 0.0)
        "z": [1.0, 0.0, 0.0],   # OUT of scope — must never be materialized
    }
    for node_id, vec in rows.items():
        conn.execute(
            "INSERT INTO memory_node_embeddings VALUES (?,?,?,?,?,?)",
            (node_id, "local", dim, model_id, _embedding_blob(vec),
             "2026-01-01T00:00:00Z"),
        )
    return conn, dim, model_id


class _RecordingConn:
    """Connection proxy that records every node_id returned by the
    embeddings SELECT, so a test can prove out-of-scope blobs were never
    transferred into Python."""

    def __init__(self, conn):
        self._conn = conn
        self.returned_node_ids: list[str] = []

    def execute(self, sql, params=()):
        cur = self._conn.execute(sql, params)
        if "FROM memory_node_embeddings" in sql:
            fetched = cur.fetchall()
            self.returned_node_ids.extend(row[0] for row in fetched)

            class _Static:
                def __init__(self, rows):
                    self._rows = rows

                def fetchall(self):
                    return self._rows

            return _Static(fetched)
        return cur


def test_semantic_rank_does_not_materialize_out_of_scope_embeddings(monkeypatch):
    """The embeddings SELECT must return ONLY in-scope node_ids — the
    out-of-scope node's blob is never transferred to Python (trade-trace-zsi8)."""

    from trade_trace.tools import memory

    conn, dim, model_id = _semantic_rank_test_db()
    recorder = _RecordingConn(conn)

    # Avoid the ONNX dependency: the query vector is fixed and aligned
    # with node 'a' so cosine(a) = 1.0 > 0 and cosine(b) = 0.0 (dropped).
    monkeypatch.setattr(
        memory, "_query_embedding",
        lambda query, *, dim, provider, model_id: [1.0, 0.0, 0.0],
    )

    in_scope = {"a": {}, "b": {}}  # 'z' is deliberately excluded
    ranked = memory._semantic_rank(recorder, "q", "local", in_scope)

    # The out-of-scope node 'z' shares 'a's vector; if it had been
    # materialized and (wrongly) scored it would surface here. It must not.
    assert "z" not in recorder.returned_node_ids, (
        "out-of-scope embedding blob was transferred to Python"
    )
    assert set(recorder.returned_node_ids) <= {"a", "b"}
    # Ranking is unchanged: 'a' (cos 1.0) ranks; 'b' (cos 0.0) is dropped by
    # the score > 0.0 filter; 'z' never appears.
    assert ranked == ["a"]


def test_semantic_rank_results_identical_with_pushed_down_filter(monkeypatch):
    """Pushing the in_scope predicate into the scan yields exactly the same
    ranking the Python-side guard produced — same nodes, same order."""

    from trade_trace.tools import memory

    conn, dim, model_id = _semantic_rank_test_db()
    # Add a second in-scope node 'c' that partially aligns with the query so
    # we exercise ordering, not just membership.
    conn.execute(
        "INSERT INTO memory_node_embeddings VALUES (?,?,?,?,?,?)",
        ("c", "local", dim, model_id, _embedding_blob([0.6, 0.8, 0.0]),
         "2026-01-01T00:00:00Z"),
    )

    monkeypatch.setattr(
        memory, "_query_embedding",
        lambda query, *, dim, provider, model_id: [1.0, 0.0, 0.0],
    )

    in_scope = {"a": {}, "b": {}, "c": {}}  # 'z' excluded
    ranked = memory._semantic_rank(conn, "q", "local", in_scope)

    # cos(a)=1.0, cos(c)=0.6, cos(b)=0.0 (dropped). 'z' excluded from scope.
    assert ranked == ["a", "c"]


def test_semantic_rank_chunks_large_in_scope(monkeypatch):
    """in_scope larger than the IN-clause chunk size still ranks correctly —
    the chunked queries union to the full in-scope result and stay under
    SQLite's bound-parameter ceiling (trade-trace-zsi8)."""

    from trade_trace.tools import memory

    conn, dim, model_id = _semantic_rank_test_db()
    # Replace the fixture rows with a large aligned set so chunking triggers.
    conn.execute("DELETE FROM memory_node_embeddings")
    n = memory._EMBEDDING_IN_CLAUSE_CHUNK + 50  # forces >1 chunk
    for i in range(n):
        conn.execute(
            "INSERT INTO memory_node_embeddings VALUES (?,?,?,?,?,?)",
            (f"n{i:05d}", "local", dim, model_id,
             _embedding_blob([1.0, 0.0, 0.0]), "2026-01-01T00:00:00Z"),
        )

    monkeypatch.setattr(
        memory, "_query_embedding",
        lambda query, *, dim, provider, model_id: [1.0, 0.0, 0.0],
    )

    in_scope = {f"n{i:05d}": {} for i in range(n)}
    ranked = memory._semantic_rank(conn, "q", "local", in_scope)

    # All n nodes are aligned (cos 1.0) and in-scope; all must surface.
    assert len(ranked) == n
    assert set(ranked) == set(in_scope)


def test_effective_confidence_unit_formula():
    """Unit guard on `_effective_confidence`: null/zero decay is a no-op
    (returns stored base), positive decay folds in exp(-rate*age_days)
    measured from created_at to as_of, and the result is clamped to
    [0, 1]. Recalls earlier than created_at clamp to age 0 (no increase)."""

    import math as _math

    from trade_trace.tools.memory import _effective_confidence

    # No decay rate set -> stored base, regardless of age.
    row_none = {"confidence_base": 0.8, "decay_rate_per_day": None,
                "created_at": "2025-01-01T00:00:00.000Z"}
    assert _effective_confidence(row_none, as_of_iso="2026-01-01T00:00:00.000Z") == 0.8

    # Zero decay rate -> stored base.
    row_zero = {"confidence_base": 0.8, "decay_rate_per_day": 0.0,
                "created_at": "2025-01-01T00:00:00.000Z"}
    assert _effective_confidence(row_zero, as_of_iso="2026-01-01T00:00:00.000Z") == 0.8

    # Null confidence_base defaults to 1.0 (schema default).
    row_default = {"confidence_base": None, "decay_rate_per_day": 0.0,
                   "created_at": "2025-01-01T00:00:00.000Z"}
    assert _effective_confidence(row_default, as_of_iso="2025-01-01T00:00:00.000Z") == 1.0

    # Positive decay over exactly 10 days -> base * exp(-rate*10).
    row_decay = {"confidence_base": 1.0, "decay_rate_per_day": 0.05,
                 "created_at": "2026-01-01T00:00:00.000Z"}
    got = _effective_confidence(row_decay, as_of_iso="2026-01-11T00:00:00.000Z")
    assert got == pytest.approx(_math.exp(-0.05 * 10.0), rel=1e-9)

    # Recall BEFORE created_at clamps to age 0 -> no decay applied.
    assert _effective_confidence(
        row_decay, as_of_iso="2025-06-01T00:00:00.000Z",
    ) == pytest.approx(1.0, rel=1e-9)

    # Clamp to [0, 1]: huge decay drives effective toward 0, never negative.
    row_huge = {"confidence_base": 1.0, "decay_rate_per_day": 100.0,
                "created_at": "2026-01-01T00:00:00.000Z"}
    out = _effective_confidence(row_huge, as_of_iso="2026-12-31T00:00:00.000Z")
    assert 0.0 <= out <= 1.0
    assert out == pytest.approx(0.0, abs=1e-9)
