from __future__ import annotations

import json
import sqlite3

from tests.integration.recall_quality_fixture import seed_recall_quality_fixture
from trade_trace.core import default_registry, dispatch
from trade_trace.reports.recall_receipts import report_recall_receipts
from trade_trace.storage.paths import db_path


def _conn(home):
    return sqlite3.connect(db_path(home))


def _seed(conn: sqlite3.Connection) -> None:
    seed_recall_quality_fixture(conn)


def test_computed_recall_receipts_classify_use_and_caveats_without_persistence(home):
    with _conn(home) as conn:
        _seed(conn)
        before = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        report = report_recall_receipts(conn, recall_id="recall-1", as_of="2026-01-02T00:00:00Z")
        after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert before == after
    assert "recall_receipts" not in after
    receipt = report["recall_receipts"][0]
    assert receipt["query"] == "prior lessons"
    assert receipt["context"] == {"instrument_id": "inst", "strategy_id": "strat"}
    assert receipt["strategies_used"] == ["bm25", "graph"]
    assert receipt["actor_id"] == "actor"
    assert receipt["agent_id"] == "agent"
    assert receipt["model_id"] == "model"
    assert receipt["run_id"] == "run"
    assert receipt["node_ids_returned"] == ["mem-helpful", "mem-ignored", "mem-stale", "mem-contradicted", "mem-harmful"]
    statuses = {item["id"]: item for item in receipt["items"]}
    assert statuses["mem-helpful"]["status"] == "cited_or_used"
    assert statuses["mem-helpful"]["attribution_status"] == "cited_or_used"
    assert statuses["mem-ignored"]["status"] == "ignored_or_unattributed"
    assert statuses["mem-ignored"]["attribution_status"] == "not_attributable"
    assert statuses["mem-stale"]["status"] == "ignored_or_unattributed"
    assert statuses["mem-stale"]["attribution_status"] == "stale"
    assert "STALE_OR_INVALIDATED_MEMORY" in statuses["mem-stale"]["caveat_codes"]
    assert statuses["mem-contradicted"]["attribution_status"] == "contradicted"
    assert "CONTRADICTED_DOWNSTREAM" in statuses["mem-contradicted"]["caveat_codes"]
    assert statuses["mem-harmful"]["status"] == "cited_or_used"
    assert "HARMFUL_DOWNSTREAM" in statuses["mem-harmful"]["caveat_codes"]
    assert statuses["mem-helpful"]["source_refs"] == [{"target_kind": "source", "target_id": "source-1", "edge_type": "about"}]
    assert "CONSUMER_INFERENCE_UNSCOPED" in receipt["caveat_codes"]
    assert report["attribution_conventions"]["use_link_direction"] == "consumer -> memory_node"
    assert report["attribution_conventions"]["source_reference_direction"] == "memory_node -> source (not downstream use evidence)"


def test_recall_receipts_is_in_default_public_catalog():
    """Bead trade-trace-8g7t: report.recall_receipts was unfrozen out of the
    experimental anchored-viewers cluster into the Phase-1 public catalog. It
    must be visible in the default catalog (no opt-in) and tagged public."""

    registry = default_registry()
    assert "report.recall_receipts" in set(registry.public_names())
    assert registry.get("report.recall_receipts").metadata()["catalog_visibility"] == "public"


def test_recall_receipts_tool_filters_by_context_and_consumer(home):
    with _conn(home) as conn:
        _seed(conn)
    registry = default_registry()
    result = dispatch(
        "report.recall_receipts",
        {"home": str(home), "instrument_id": "inst", "strategy_id": "strat", "consumer_kind": "decision", "consumer_id": "dec"},
        actor_id="agent:test",
        registry=registry,
    )
    dumped = result.model_dump(mode="json", exclude_none=True)
    assert dumped["ok"] is True, dumped
    receipts = dumped["data"]["recall_receipts"]
    assert [r["recall_id"] for r in receipts] == ["recall-1"]
    assert receipts[0]["node_ids_used"] == ["mem-helpful", "mem-harmful"]


def test_recall_receipts_applies_json_filters_before_limit(home):
    with _conn(home) as conn:
        _insert_memory_node(conn, node_id="mem-target", valid_to=None)
        for recall_id, node_ids, context, created_at in (
            ("recall-nonmatch-node", ["mem-other"], {"instrument_id": "other"}, "2026-01-01T00:01:00Z"),
            ("recall-nonmatch-context", ["mem-other"], {"instrument_id": "other"}, "2026-01-01T00:02:00Z"),
            (
                "recall-target",
                ["mem-target"],
                {"instrument_id": "inst-target", "strategy_id": "strat-target"},
                "2026-01-01T00:03:00Z",
            ),
        ):
            conn.execute(
                """
                INSERT INTO memory_recall_events(
                    recall_id, query, strategies_used, node_ids_returned,
                    context_json, limit_k, as_of, created_at, actor_id,
                    agent_id, model_id, environment, run_id
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    recall_id, "limit filter", '["bm25"]', json.dumps(node_ids),
                    json.dumps(context), 5, None, created_at, "actor",
                    "agent", "model", "paper", "run",
                ),
            )
        conn.commit()

        by_node = report_recall_receipts(conn, node_id="mem-target", limit=1)
        by_context = report_recall_receipts(
            conn,
            instrument_id="inst-target",
            strategy_id="strat-target",
            limit=1,
        )

    assert [r["recall_id"] for r in by_node["recall_receipts"]] == ["recall-target"]
    assert [r["recall_id"] for r in by_context["recall_receipts"]] == ["recall-target"]


def test_recall_receipts_require_consumer_scope_for_strong_attribution(home):
    with _conn(home) as conn:
        _seed(conn)
        report = report_recall_receipts(conn, recall_id="recall-1", consumer_kind="decision", consumer_id="dec")

    receipt = report["recall_receipts"][0]
    assert "CONSUMER_INFERENCE_UNSCOPED" not in receipt["caveat_codes"]
    assert receipt["node_ids_used"] == ["mem-helpful", "mem-harmful"]
    statuses = {item["id"]: item for item in receipt["items"]}
    assert statuses["mem-helpful"]["edge_evidence"] == [
        {
            "edge_id": "e-helpful-use",
            "consumer_kind": "decision",
            "consumer_id": "dec",
            "edge_type": "supports",
            "created_at": "2026-01-01T00:06:00Z",
        }
    ]
    assert statuses["mem-stale"]["edge_evidence"] == []
    assert statuses["mem-stale"]["attribution_status"] == "stale"


def test_recall_receipts_count_use_only_with_downstream_edge_evidence(home):
    with _conn(home) as conn:
        _seed(conn)
        report = report_recall_receipts(conn, recall_id="recall-1", consumer_kind="decision", consumer_id="dec")

    receipt = report["recall_receipts"][0]
    statuses = {item["id"]: item for item in receipt["items"]}
    assert statuses["mem-helpful"]["status"] == "cited_or_used"
    assert statuses["mem-helpful"]["edge_evidence"]
    assert statuses["mem-ignored"]["status"] == "ignored_or_unattributed"
    assert statuses["mem-ignored"]["edge_evidence"] == []
    assert statuses["mem-stale"]["status"] == "ignored_or_unattributed"
    assert statuses["mem-stale"]["edge_evidence"] == []
    assert "mem-ignored" not in receipt["node_ids_used"]
    assert "mem-stale" not in receipt["node_ids_used"]


def test_recall_receipts_do_not_treat_memory_source_refs_as_downstream_use(home):
    with _conn(home) as conn:
        _seed(conn)
        report = report_recall_receipts(conn, recall_id="recall-1", consumer_kind="review", consumer_id="missing-review")

    assert report["recall_receipts"] == []
    assert report["summary"]["sample_warning"] == "no_recall_events"


def _insert_corrupt_recall_event(
    conn: sqlite3.Connection,
    *,
    recall_id: str,
    strategies_used: str,
    node_ids_returned: str,
    context_json: str,
) -> None:
    conn.execute(
        """
        INSERT INTO memory_recall_events(
            recall_id, query, strategies_used, node_ids_returned,
            context_json, limit_k, as_of, created_at, actor_id,
            agent_id, model_id, environment, run_id
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            recall_id, "q",
            strategies_used, node_ids_returned, context_json,
            5, None,
            "2026-01-02T00:00:00Z", "actor",
            "agent", "model", "paper", "run",
        ),
    )


def _insert_memory_node(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    valid_to: str | None,
    invalidated_at: str | None = None,
    confidence: float = 0.7,
) -> None:
    conn.execute(
        """
        INSERT INTO memory_nodes(id, node_type, title, body, meta_json, importance,
                                 confidence_base, valid_from, valid_to, invalidated_at,
                                 created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            node_id, "observation", node_id, node_id, "{}", 5,
            confidence, "2025-01-01T00:00:00Z", valid_to, invalidated_at,
            "2026-01-01T00:00:00Z", "actor",
        ),
    )


def _insert_recall_event(
    conn: sqlite3.Connection, *, recall_id: str, node_ids: list[str], as_of: str | None
) -> None:
    import json

    conn.execute(
        """
        INSERT INTO memory_recall_events(recall_id, query, strategies_used, node_ids_returned,
                                         context_json, limit_k, as_of, created_at, actor_id,
                                         agent_id, model_id, environment, run_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            recall_id, "future window", json.dumps(["bm25"]), json.dumps(node_ids),
            json.dumps({}), 5, as_of, "2026-01-01T00:03:00Z", "actor",
            "agent", "model", "test", "run",
        ),
    )


def test_recall_receipts_future_valid_to_is_not_stale(home):
    """trade-trace-uycm: a memory node with a future valid_to is not stale — it
    simply carries a planned expiry. The STALE_OR_INVALIDATED_MEMORY caveat must
    NOT fire, attribution_status must be 'not_attributable' (not 'stale'), and it
    must not inflate stale_count in the memory_usefulness diagnostic."""
    from trade_trace.reports.memory_usefulness import report_memory_usefulness

    as_of = "2026-01-02T00:00:00Z"
    with _conn(home) as conn:
        # A node whose validity window extends well past the effective time.
        _insert_memory_node(conn, node_id="mem-future", valid_to="2030-01-01T00:00:00Z")
        # A genuinely expired node as a positive control for the stale path.
        _insert_memory_node(conn, node_id="mem-expired", valid_to="2025-12-31T00:00:00Z")
        _insert_recall_event(
            conn, recall_id="recall-future", node_ids=["mem-future", "mem-expired"], as_of=as_of
        )
        conn.commit()

        report = report_recall_receipts(conn, recall_id="recall-future", as_of=as_of)
        usefulness = report_memory_usefulness(conn, recall_id="recall-future", as_of=as_of)

    receipt = report["recall_receipts"][0]
    items = {item["id"]: item for item in receipt["items"]}

    future = items["mem-future"]
    assert future["attribution_status"] == "not_attributable"
    assert "STALE_OR_INVALIDATED_MEMORY" not in future["caveat_codes"]
    assert "STALE_AS_OF_RECEIPT" not in future["caveat_codes"]

    # The genuinely expired node still trips the caveat and is classified stale.
    expired = items["mem-expired"]
    assert expired["attribution_status"] == "stale"
    assert "STALE_OR_INVALIDATED_MEMORY" in expired["caveat_codes"]

    # Only the expired node contributes to stale_count, not the future-window one.
    assert usefulness["summary"]["metrics"]["stale_count"] == 1
    diagnostics = {d["node_id"]: d for d in usefulness["memory_diagnostics"]}
    assert diagnostics["mem-future"]["stale"] is False
    assert diagnostics["mem-expired"]["stale"] is True


def test_recall_receipts_future_valid_to_without_as_of_uses_now(home):
    """trade-trace-uycm: with no as_of supplied, the effective time defaults to
    now_iso(); a far-future valid_to (2030) is still in the future relative to
    'now' in tests, so the node must not be flagged stale."""
    with _conn(home) as conn:
        _insert_memory_node(conn, node_id="mem-future-now", valid_to="2030-01-01T00:00:00Z")
        _insert_recall_event(
            conn, recall_id="recall-future-now", node_ids=["mem-future-now"], as_of=None
        )
        conn.commit()
        report = report_recall_receipts(conn, recall_id="recall-future-now")

    item = report["recall_receipts"][0]["items"][0]
    assert item["attribution_status"] == "not_attributable"
    assert "STALE_OR_INVALIDATED_MEMORY" not in item["caveat_codes"]


def _count_table_queries(conn: sqlite3.Connection) -> dict[str, int]:
    """Install a trace callback that counts executed SELECTs against the
    two tables report.recall_receipts reads per node. Returns the live
    dict (mutated as queries run)."""

    counts = {"memory_nodes": 0, "edges": 0}

    def _trace(sql: str) -> None:
        lowered = sql.lower()
        # Only count read queries against the per-node tables; ignore the
        # schema-introspection SELECTs the tests themselves issue.
        if "from memory_nodes" in lowered:
            counts["memory_nodes"] += 1
        if "from edges" in lowered:
            counts["edges"] += 1

    conn.set_trace_callback(_trace)
    return counts


def test_recall_receipts_batches_per_node_lookups_no_n_plus_one(home):
    """trade-trace-qf78: report.recall_receipts must not issue 3 SQL queries
    per returned node. The fixture returns 5 nodes in one recall event; the
    batched read path issues exactly one memory_nodes IN-query and exactly
    two edges queries (incoming evidence + outgoing source_refs), independent
    of the node count."""
    with _conn(home) as conn:
        _seed(conn)
        counts = _count_table_queries(conn)
        report = report_recall_receipts(conn, recall_id="recall-1", as_of="2026-01-02T00:00:00Z")
        conn.set_trace_callback(None)

    # Five returned nodes — a per-node path would issue 5 memory_nodes
    # queries and 10 edges queries (2 per node). The batched path is fixed.
    assert counts["memory_nodes"] == 1, counts
    assert counts["edges"] == 2, counts
    # Result still has all five items in returned order (shape unchanged).
    receipt = report["recall_receipts"][0]
    assert [item["id"] for item in receipt["items"]] == [
        "mem-helpful", "mem-ignored", "mem-stale", "mem-contradicted", "mem-harmful",
    ]


def test_recall_receipts_query_count_constant_across_node_count(home):
    """The per-table query count is independent of how many nodes are
    returned: adding a second recall event with more nodes must NOT add
    queries (cross-event batching), proving the N+1 is gone."""
    with _conn(home) as conn:
        _seed(conn)
        # A second event returning the same nodes again plus reusing them.
        _insert_recall_event(
            conn,
            recall_id="recall-extra",
            node_ids=["mem-helpful", "mem-ignored", "mem-stale", "mem-contradicted", "mem-harmful"],
            as_of=None,
        )
        conn.commit()
        counts = _count_table_queries(conn)
        report = report_recall_receipts(conn, as_of="2026-01-02T00:00:00Z")
        conn.set_trace_callback(None)

    # Two events, ten total returned node slots — still exactly the three
    # batched queries (1 memory_nodes + 2 edges), not 3-per-node.
    assert counts["memory_nodes"] == 1, counts
    assert counts["edges"] == 2, counts
    assert {r["recall_id"] for r in report["recall_receipts"]} == {"recall-1", "recall-extra"}


def test_recall_receipts_handles_corrupt_json_payload(home):
    """trade-trace-m9k4: a malformed JSON column in memory_recall_events used to
    crash the entire report. Now it degrades to safe defaults and the report
    still returns for the other valid rows."""
    with _conn(home) as conn:
        _seed(conn)
        # Two corrupt rows: one with garbage JSON, one with valid JSON of the
        # wrong shape (string instead of list/object).
        _insert_corrupt_recall_event(
            conn, recall_id="recall-bad-json",
            strategies_used="not valid json {",
            node_ids_returned='["mem-helpful"',
            context_json="bare string not object",
        )
        _insert_corrupt_recall_event(
            conn, recall_id="recall-wrong-shape",
            strategies_used='"a string, not a list"',
            node_ids_returned='42',
            context_json='"not an object"',
        )
        conn.commit()
        report = report_recall_receipts(conn)

    by_id = {r["recall_id"]: r for r in report["recall_receipts"]}
    assert "recall-1" in by_id, list(by_id)
    assert by_id["recall-bad-json"]["strategies_used"] == []
    assert by_id["recall-bad-json"]["node_ids_returned"] == []
    assert by_id["recall-bad-json"]["context"] == {}
    assert by_id["recall-wrong-shape"]["strategies_used"] == []
    assert by_id["recall-wrong-shape"]["node_ids_returned"] == []
    assert by_id["recall-wrong-shape"]["context"] == {}
