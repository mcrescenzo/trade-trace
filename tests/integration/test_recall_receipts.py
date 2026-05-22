from __future__ import annotations

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
    assert not any("receipt" in table and table != "memory_recall_events" for table in after)
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
