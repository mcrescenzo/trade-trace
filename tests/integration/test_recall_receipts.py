from __future__ import annotations

import json
import sqlite3

from trade_trace.core import default_registry, dispatch
from trade_trace.reports.recall_receipts import report_recall_receipts
from trade_trace.storage.paths import db_path


def _conn(home):
    return sqlite3.connect(db_path(home))


def _seed(conn: sqlite3.Connection) -> None:
    ts = "2026-01-01T00:00:00Z"
    conn.execute("INSERT INTO venues VALUES (?,?,?,?,?,?)", ("ven", "Venue", "manual", "{}", ts, "actor"))
    conn.execute(
        "INSERT INTO instruments (id, venue_id, title, asset_class, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)",
        ("inst", "ven", "Instrument", "equity", "{}", ts, "actor"),
    )
    conn.execute(
        "INSERT INTO theses (id, instrument_id, side, body, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)",
        ("th", "inst", "long", "thesis", "{}", "2026-01-01T00:04:00Z", "actor"),
    )
    conn.execute(
        "INSERT INTO decisions (id, instrument_id, thesis_id, type, reason, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?)",
        ("dec", "inst", "th", "paper_enter", "because", "{}", "2026-01-01T00:05:00Z", "actor"),
    )
    for node_id, title, valid_to in (
        ("mem-used", "Used", None),
        ("mem-ignored", "Ignored", None),
        ("mem-stale", "Stale", "2025-12-31T00:00:00Z"),
    ):
        conn.execute(
            """
            INSERT INTO memory_nodes(id, node_type, title, body, meta_json, importance,
                                     confidence_base, valid_from, valid_to, created_at, actor_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (node_id, "observation", title, title, "{}", 5, 1.0, "2025-01-01T00:00:00Z", valid_to, ts, "actor"),
        )
    conn.execute(
        """
        INSERT INTO memory_recall_events(recall_id, query, strategies_used, node_ids_returned,
                                         context_json, limit_k, as_of, created_at, actor_id,
                                         agent_id, model_id, environment, run_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "recall-1",
            "prior lessons",
            json.dumps(["bm25", "graph"]),
            json.dumps(["mem-used", "mem-ignored", "mem-stale"]),
            json.dumps({"instrument_id": "inst", "strategy_id": "strat"}, sort_keys=True),
            3,
            "2026-01-01T00:03:00Z",
            "2026-01-01T00:03:00Z",
            "actor",
            "agent",
            "model",
            "test",
            "run",
        ),
    )
    edges = [
        ("e-use", "decision", "dec", "memory_node", "mem-used", "supports"),
        ("e-contradict", "thesis", "th", "memory_node", "mem-stale", "contradicts"),
        ("e-source", "memory_node", "mem-used", "source", "source-1", "about"),
    ]
    for edge_id, sk, sid, tk, tid, et in edges:
        conn.execute(
            "INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)",
            (edge_id, sk, sid, tk, tid, et, None, "{}", "2026-01-01T00:06:00Z", "actor"),
        )


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
    assert receipt["node_ids_returned"] == ["mem-used", "mem-ignored", "mem-stale"]
    statuses = {item["id"]: item for item in receipt["items"]}
    assert statuses["mem-used"]["status"] == "cited_or_used"
    assert statuses["mem-ignored"]["status"] == "ignored_or_unattributed"
    assert statuses["mem-stale"]["status"] == "ignored_or_unattributed"
    assert "STALE_OR_INVALIDATED_MEMORY" in statuses["mem-stale"]["caveat_codes"]
    assert "CONTRADICTED_DOWNSTREAM" in statuses["mem-stale"]["caveat_codes"]
    assert statuses["mem-used"]["source_refs"] == [{"target_kind": "source", "target_id": "source-1", "edge_type": "about"}]


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
    assert receipts[0]["node_ids_used"] == ["mem-used"]
