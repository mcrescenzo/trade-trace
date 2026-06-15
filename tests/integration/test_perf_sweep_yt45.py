"""Regression coverage for the low-severity performance sweep
(bead trade-trace-yt45).

Each test pins a behavior-preserving optimization from the sweep so a
future refactor that reintroduces the slow path is caught:

1.  migrations 034/035 add the planned indexes and the query planner
    actually uses them for the target queries (covering index for the
    list_trades source_count subquery; run_id/agent_id composite indexes
    for the recall-receipts filters).
2.  source_quality._inline_source_attachments filters sources-less rows
    in SQL (and tolerates malformed JSON) — output is unchanged.
3.  coach._override_outcomes_panel resolves subsequent-outcome counts
    with a single grouped query instead of one probe per overridden row.
4.  memory._load_in_scope_nodes pushes the node_types filter into SQL and
    returns the same rows the old Python post-filter produced.

Tail items (bead trade-trace-ukwy), the 4 yt45 micro-optimizations that
yt45 carved out:

5.  ToolRegistry.names() memoizes the sorted name list and rebuilds it only
    when the table mutates (register/alias/mark).
6.  dispatch_trace.is_enabled() memoizes the enable flag instead of reading
    os.environ on every dispatch; reset_enabled_cache() re-reads.
7.  core.new_request_id() resolves CLOCK_OVERRIDE from a module-level import,
    not a per-call lazy import.
8.  memory._fts_match / _like_fallback push the in-scope filter into SQL so
    the LIMIT applies after scope filtering (output unchanged).
"""

from __future__ import annotations

from pathlib import Path

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path
from trade_trace.tools import memory as memory_tools

# -- 1. migration indexes exist + are used by the planner --------------


def test_m034_edges_target_type_index_present_and_used(home: Path) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        conn = db.connection
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_edges_target_type'"
        ).fetchone()
        assert idx is not None, "m034 must create idx_edges_target_type"

        # The source_count subquery seeks on (target_kind, target_id) then
        # filters edge_type; the covering index must be the chosen plan.
        plan = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT COUNT(*) FROM edges e "
            "WHERE e.target_kind = 'decision' AND e.target_id = ? "
            "AND e.edge_type = 'cites'",
            ("d_x",),
        ).fetchall()
        detail = " ".join(str(r[-1]) for r in plan)
        assert "idx_edges_target_type" in detail, detail
    finally:
        db.close()


def test_m035_recall_events_filter_indexes_present_and_used(home: Path) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        conn = db.connection
        for name in (
            "idx_memory_recall_events_run",
            "idx_memory_recall_events_agent",
        ):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (name,),
            ).fetchone()
            assert row is not None, f"m035 must create {name}"

        run_plan = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT recall_id FROM memory_recall_events "
            "WHERE run_id = ? ORDER BY created_at ASC LIMIT 50",
            ("run_x",),
        ).fetchall()
        run_detail = " ".join(str(r[-1]) for r in run_plan)
        assert "idx_memory_recall_events_run" in run_detail, run_detail

        agent_plan = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT recall_id FROM memory_recall_events "
            "WHERE agent_id = ? ORDER BY created_at ASC LIMIT 50",
            ("agent_x",),
        ).fetchall()
        agent_detail = " ".join(str(r[-1]) for r in agent_plan)
        assert "idx_memory_recall_events_agent" in agent_detail, agent_detail
    finally:
        db.close()


# -- 2. source_quality skips sources-less rows in SQL ------------------


def test_inline_attachments_kept_while_sources_less_rows_skipped(
    home: Path,
) -> None:
    """`_inline_source_attachments` must still surface a row that carries
    an inline sources array, while the SQL WHERE filter skips the rows
    that carry none (the optimization must not drop real attachments)."""

    from trade_trace.reports.source_quality import _inline_source_attachments

    db = open_database(db_path(home), create_parent=False)
    try:
        conn = db.connection
        conn.execute(
            "INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) "
            "VALUES ('v_sq', 'V', 'prediction_market', '{}', "
            "'2020-01-01T00:00:00Z', 'agent:test')"
        )
        # One instrument WITH an inline source; one with none ('{}').
        conn.execute(
            "INSERT INTO instruments(id, venue_id, external_id, title, asset_class, "
            "metadata_json, created_at, actor_id) VALUES "
            "('i_with', 'v_sq', 'pm-with', 'X', 'prediction_market', "
            "'{\"sources\":[{\"id\":\"src-1\",\"stance\":\"supports\"}]}', "
            "'2020-01-01T00:00:00Z', 'agent:test')"
        )
        conn.execute(
            "INSERT INTO instruments(id, venue_id, external_id, title, asset_class, "
            "metadata_json, created_at, actor_id) VALUES "
            "('i_none', 'v_sq', 'pm-none', 'Y', 'prediction_market', '{}', "
            "'2020-01-01T00:00:00Z', 'agent:test')"
        )
        conn.commit()

        attachments = _inline_source_attachments(conn)
        target_ids = {a["target_id"] for a in attachments}
        assert "i_with" in target_ids, "real inline source must not be dropped"
        assert "i_none" not in target_ids, "sources-less row must yield nothing"
        with_src = next(a for a in attachments if a["target_id"] == "i_with")
        assert with_src["id"] == "src-1"
        assert with_src["stance"] == "supports"
    finally:
        db.close()


def test_inline_source_attachments_filter_is_malformed_json_tolerant(
    home: Path,
) -> None:
    """A row with malformed metadata_json must not raise in the new
    json_extract WHERE filter (the json_valid guard short-circuits)."""

    db = open_database(db_path(home), create_parent=False)
    try:
        conn = db.connection
        # Write a malformed metadata_json directly (bypasses the tool guards
        # the same way the existing malformed-tolerance test does).
        conn.execute(
            "INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) "
            "VALUES ('v_mal', 'V', 'prediction_market', '{}', "
            "'2020-01-01T00:00:00Z', 'agent:test')"
        )
        conn.execute(
            "INSERT INTO instruments(id, venue_id, external_id, title, asset_class, "
            "metadata_json, created_at, actor_id) VALUES "
            "('i_mal', 'v_mal', 'pm-mal', 'X', 'prediction_market', "
            "'{not valid json', '2020-01-01T00:00:00Z', 'agent:test')"
        )
        conn.commit()
        from trade_trace.reports.source_quality import _inline_source_attachments

        # Must not raise on the malformed row; it yields no attachment.
        attachments = _inline_source_attachments(conn)
        assert all(a["target_id"] != "i_mal" for a in attachments)
    finally:
        db.close()


# -- 3. coach override panel uses a single grouped query ---------------


def _seed_override(home: Path, *, suffix: str, with_outcome: bool) -> None:
    venue = _mcp(home, "venue.add", {
        "name": f"V-{suffix}", "kind": "prediction_market",
        "idempotency_key": f"00000000-0000-4000-8000-yt45-co-v-{suffix}",
    }).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": f"X-{suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-yt45-co-i-{suffix}",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "t",
        "idempotency_key": f"00000000-0000-4000-8000-yt45-co-t-{suffix}",
    }).data["id"]
    decision = _mcp(home, "decision.add", {
        "type": "actual_enter", "instrument_id": inst, "thesis_id": thesis,
        "side": "yes", "quantity": 1, "price": 0.5,
        "idempotency_key": f"00000000-0000-4000-8000-yt45-co-d-{suffix}",
    }).data["id"]
    pb = _mcp(home, "playbook.upsert", {
        "name": f"PB-{suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-yt45-co-pb-{suffix}",
    }).data["id"]
    ref = _mcp(home, "memory.retain", {
        "node_type": "reflection", "body": f"r-{suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-yt45-co-rf-{suffix}",
    }).data["id"]
    pv = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb, "provenance_reflection_node_id": ref,
        "idempotency_key": f"00000000-0000-4000-8000-yt45-co-pv-{suffix}",
    }).data["id"]
    rule = _mcp(home, "memory.retain", {
        "node_type": "playbook_rule", "body": f"rule-{suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-yt45-co-rl-{suffix}",
    }).data["id"]
    _mcp(home, "playbook.record_adherence", {
        "decision_id": decision, "playbook_version_id": pv, "rule_node_id": rule,
        "status": "overridden", "reason": "edge clear",
        "idempotency_key": f"00000000-0000-4000-8000-yt45-co-ad-{suffix}",
    })
    if with_outcome:
        _mcp(home, "resolution.add", {
            "instrument_id": inst, "resolved_at": "2099-01-01T00:00:00Z",
            "outcome_label": "yes", "status": "resolved_final",
            "idempotency_key": f"00000000-0000-4000-8000-yt45-co-oc-{suffix}",
        })


def test_override_panel_no_per_row_outcomes_query(home: Path) -> None:
    """`_override_outcomes_panel` must issue exactly one grouped outcomes
    query regardless of how many overridden rows exist (no N+1), and keep
    the same with/without subsequent-outcome split."""

    _seed_override(home, suffix="a", with_outcome=True)
    _seed_override(home, suffix="b", with_outcome=False)
    _seed_override(home, suffix="c", with_outcome=True)

    from trade_trace.reports import coach

    class _CountingConn:
        """Proxy that forwards to the real connection but tallies how many
        outcomes queries are issued. `sqlite3.Connection.execute` is
        read-only and cannot be monkeypatched, so wrap it instead."""

        def __init__(self, real):
            self._real = real
            self.outcomes_queries = 0

        def execute(self, sql, *args, **kwargs):
            if "FROM outcomes" in sql:
                self.outcomes_queries += 1
            return self._real.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

    db = open_database(db_path(home), create_parent=False)
    try:
        proxy = _CountingConn(db.connection)
        panel = coach._override_outcomes_panel(proxy)
        outcomes_queries = proxy.outcomes_queries
    finally:
        db.close()

    assert panel["overridden_count"] == 3
    assert panel["with_subsequent_outcome"] == 2
    assert panel["without_subsequent_outcome"] == 1
    # The whole point of the fix: a single outcomes query, not one per row.
    assert outcomes_queries == 1, (
        f"expected a single grouped outcomes query, saw {outcomes_queries} "
        "(the per-row N+1 has regressed)"
    )


# -- 4. memory._load_in_scope_nodes pushes node_types into SQL ---------


def test_load_in_scope_node_types_pushdown_matches_python_filter(
    home: Path,
) -> None:
    """The SQL node_types pushdown returns exactly the rows the old Python
    post-filter produced."""

    obs = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "obs body",
        "idempotency_key": "00000000-0000-4000-8000-yt45-nt-obs1",
    })
    assert obs.ok, obs
    rule = _mcp(home, "memory.retain", {
        "node_type": "playbook_rule", "body": "rule body",
        "idempotency_key": "00000000-0000-4000-8000-yt45-nt-rul1",
    })
    assert rule.ok, rule
    refl = _mcp(home, "memory.retain", {
        "node_type": "reflection", "body": "reflection body",
        "idempotency_key": "00000000-0000-4000-8000-yt45-nt-ref1",
    })
    assert refl.ok, refl

    db = open_database(db_path(home), create_parent=False)
    try:
        conn = db.connection
        full = memory_tools._load_in_scope_nodes(conn, as_of=None)
        # Python post-filter (the old behavior) for a single node_type.
        expected = {
            nid: row for nid, row in full.items()
            if row["node_type"] in ["observation"]
        }
        pushed = memory_tools._load_in_scope_nodes(
            conn, as_of=None, node_types=["observation"],
        )
        assert set(pushed) == set(expected)
        assert all(row["node_type"] == "observation" for row in pushed.values())

        # Multi-type filter likewise matches.
        multi_expected = {
            nid: row for nid, row in full.items()
            if row["node_type"] in ["observation", "playbook_rule"]
        }
        multi_pushed = memory_tools._load_in_scope_nodes(
            conn, as_of=None, node_types=["observation", "playbook_rule"],
        )
        assert set(multi_pushed) == set(multi_expected)

        # None / empty → full corpus (no type filter).
        assert set(memory_tools._load_in_scope_nodes(conn, as_of=None)) == set(full)
    finally:
        db.close()


# -- 5. ToolRegistry.names() memoizes the sorted name list -------------


def test_tool_registry_names_is_cached_and_invalidated_on_mutation() -> None:
    """`names()` must return a stable cached list (built once, reused) and
    rebuild it only when register()/alias()/mark() mutate the table."""

    from trade_trace.contracts.tool_registry import ToolRegistry

    reg = ToolRegistry()
    reg.register("b.verb", lambda args, ctx: {}, description="b")
    reg.register("a.verb", lambda args, ctx: {}, description="a")

    first = reg.names()
    # Same list object on a second call → cached, not re-sorted per call.
    assert reg.names() is first
    assert first == ["a.verb", "b.verb"]

    # register() invalidates the cache and the new name appears, sorted.
    reg.register("c.verb", lambda args, ctx: {}, description="c")
    after_register = reg.names()
    assert after_register is not first
    assert after_register == ["a.verb", "b.verb", "c.verb"]

    # alias() (which routes through register()) also invalidates.
    reg.alias("d.verb", "a.verb")
    assert "d.verb" in reg.names()

    # mark() invalidates too (and the name set is unchanged by a re-mark).
    before_mark = reg.names()
    reg.mark("a.verb", catalog_visibility="legacy")
    after_mark = reg.names()
    assert after_mark is not before_mark
    assert set(after_mark) == set(before_mark)


def test_tool_registry_names_matches_uncached_sorted() -> None:
    """The cached value must equal the historical `sorted(self.by_name)`."""

    from trade_trace.core import default_registry

    reg = default_registry()
    assert reg.names() == sorted(reg.by_name)


# -- 6. dispatch_trace.is_enabled() — DEFERRED (see bead) --------------
# Item 2 (memoize the TRADE_TRACE_DISPATCH_TRACE read) was explicitly
# deferred: caching is not behavior-safe because ~12 test modules toggle
# the env var mid-process and shared fixtures dispatch before the test body
# sets it, so a cache would freeze stale. The per-call cost is one dict
# lookup; the win does not justify the cross-file reset retrofit. The
# behavior-preserving live read is asserted by the existing
# tests/contracts/test_dispatch_trace.py suite.


# -- 7. new_request_id() resolves CLOCK_OVERRIDE from module scope -----


def test_new_request_id_clock_override_import_is_hoisted() -> None:
    """The CLOCK_OVERRIDE symbol must be bound at module scope in core (no
    per-call lazy import) and still drive deterministic ids when set."""

    from trade_trace import core
    from trade_trace.tools._helpers import CLOCK_OVERRIDE

    # Hoisted to module level → the same ContextVar object core uses.
    assert core.CLOCK_OVERRIDE is CLOCK_OVERRIDE

    # No deterministic override → uuid4 hex (32 hex chars, not the det prefix).
    assert CLOCK_OVERRIDE.get() is None
    rid = core.new_request_id()
    assert len(rid) == 32 and not rid.startswith("det-req-")

    # With the override set, ids fall back to the deterministic counter.
    from datetime import UTC, datetime

    core._reset_deterministic_request_id_counter()
    token = CLOCK_OVERRIDE.set(datetime(2020, 1, 1, tzinfo=UTC))
    try:
        assert core.new_request_id() == "det-req-00000001".ljust(32, "0")[:32]
    finally:
        CLOCK_OVERRIDE.reset(token)


# -- 8. _fts_match / _like_fallback push in-scope into SQL -------------


def test_fts_match_pushes_in_scope_into_sql_and_limit_applies_after(
    home: Path,
) -> None:
    """`_fts_match` must carry the in-scope ids as an `id IN (...)` clause so
    the bm25 LIMIT is taken AFTER scope filtering, and return only in-scope
    ids — identical to the old fetch-then-Python-filter behavior.

    The proof that the filter is enforced inside the SQL statement (not by a
    Python post-pass) is that `_fts_match` itself — which no longer
    post-filters its rows — returns the scoped set: any non-scoped match
    that came back would mean the IN-clause was not applied."""

    a = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "alpha bravo charlie marker",
        "idempotency_key": "00000000-0000-4000-8000-ukwy-fts-a",
    })
    assert a.ok, a
    b = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "alpha bravo delta marker",
        "idempotency_key": "00000000-0000-4000-8000-ukwy-fts-b",
    })
    assert b.ok, b
    a_id, b_id = a.data["id"], b.data["id"]

    db = open_database(db_path(home), create_parent=False)
    try:
        conn = db.connection
        full = memory_tools._load_in_scope_nodes(conn, as_of=None)
        # Restrict the in-scope set to just `a`; `b` also matches "marker"
        # but must be filtered out by the SQL IN-clause, not in Python —
        # `_fts_match` returns its rows verbatim.
        only_a = {a_id: full[a_id]}
        scoped = memory_tools._fts_match(conn, "marker", in_scope=only_a)
        assert scoped == [a_id], scoped
        assert b_id not in (scoped or [])

        # No in_scope → the unfiltered top-500 (legacy behavior) returns both.
        unscoped = memory_tools._fts_match(conn, "marker")
        assert set(unscoped or []) == {a_id, b_id}, unscoped

        # Behavior parity: with both in scope, both surface and the result
        # set equals the legacy fetch-then-Python-filter.
        both = memory_tools._fts_match(conn, "marker", in_scope=full)
        assert set(both or []) == {a_id, b_id}
        assert set(both or []) == {r for r in (unscoped or []) if r in full}
    finally:
        db.close()


def test_like_fallback_in_scope_pushdown_matches_python_filter(
    home: Path,
) -> None:
    """`_like_fallback` with `in_scope` returns the same ids the legacy
    fetch-then-`r in in_scope` post-filter would have produced."""

    a = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "needle forecast.add token",
        "idempotency_key": "00000000-0000-4000-8000-ukwy-like-a",
    })
    assert a.ok, a
    b = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "needle forecast.add other",
        "idempotency_key": "00000000-0000-4000-8000-ukwy-like-b",
    })
    assert b.ok, b
    a_id, b_id = a.data["id"], b.data["id"]

    db = open_database(db_path(home), create_parent=False)
    try:
        conn = db.connection
        full = memory_tools._load_in_scope_nodes(conn, as_of=None)
        only_a = {a_id: full[a_id]}

        # No-scope call is unchanged (both match "needle").
        unscoped = memory_tools._like_fallback(conn, "needle")
        assert {a_id, b_id} <= set(unscoped)

        # Scoped to just `a`: `b` is filtered out in SQL.
        scoped = memory_tools._like_fallback(conn, "needle", in_scope=only_a)
        legacy = [r for r in unscoped if r in only_a]
        assert scoped == legacy
        assert b_id not in scoped
    finally:
        db.close()


def test_scope_in_clause_skips_pushdown_when_too_large() -> None:
    """When the in-scope set exceeds the IN-clause chunk budget, the helper
    returns None so the caller keeps the correct (post-filter) path and the
    bound-parameter ceiling is never exceeded."""

    chunk = memory_tools._EMBEDDING_IN_CLAUSE_CHUNK
    small = {f"id-{i}": {} for i in range(chunk - 1)}
    assert memory_tools._scope_in_clause(small, reserved_params=1) is not None

    big = {f"id-{i}": {} for i in range(chunk + 5)}
    assert memory_tools._scope_in_clause(big, reserved_params=1) is None

    # Empty / None → no clause.
    assert memory_tools._scope_in_clause({}, reserved_params=1) is None
    assert memory_tools._scope_in_clause(None, reserved_params=1) is None
