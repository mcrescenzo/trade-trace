from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class RecallQualityFixtureIds:
    venue_id: str = "ven"
    instrument_id: str = "inst"
    thesis_id: str = "th"
    decision_id: str = "dec"
    review_id: str = "rev"
    recall_id: str = "recall-1"
    helpful_node_id: str = "mem-helpful"
    ignored_node_id: str = "mem-ignored"
    stale_node_id: str = "mem-stale"
    contradicted_node_id: str = "mem-contradicted"
    harmful_node_id: str = "mem-harmful"


RECALL_QUALITY_FIXTURE_IDS = RecallQualityFixtureIds()


def seed_recall_quality_fixture(conn: sqlite3.Connection) -> RecallQualityFixtureIds:
    """Seed deterministic local recall data covering memory-quality cases.

    Cases are intentionally encoded only in existing journal tables:
    helpful/used requires a downstream consumer->memory edge, ignored has no
    downstream edge, stale is expired without use evidence for the scoped
    decision, contradicted has explicit contradictory downstream evidence, and
    harmful has explicit violates downstream evidence. No receipt/materialized
    quality tables, embedding calls, network calls, or clocks are used.
    """

    ids = RECALL_QUALITY_FIXTURE_IDS
    ts = "2026-01-01T00:00:00Z"
    conn.execute("INSERT INTO venues VALUES (?,?,?,?,?,?)", (ids.venue_id, "Venue", "manual", "{}", ts, "actor"))
    conn.execute(
        "INSERT INTO instruments (id, venue_id, title, asset_class, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)",
        (ids.instrument_id, ids.venue_id, "Instrument", "equity", "{}", ts, "actor"),
    )
    conn.execute(
        "INSERT INTO theses (id, instrument_id, side, body, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)",
        (ids.thesis_id, ids.instrument_id, "long", "thesis", "{}", "2026-01-01T00:04:00Z", "actor"),
    )
    conn.execute(
        "INSERT INTO decisions (id, instrument_id, thesis_id, type, reason, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?)",
        (ids.decision_id, ids.instrument_id, ids.thesis_id, "paper_enter", "because", "{}", "2026-01-01T00:05:00Z", "actor"),
    )
    memory_rows = [
        (ids.helpful_node_id, "Helpful used", None, 1.0),
        (ids.ignored_node_id, "Ignored unused", None, 0.6),
        (ids.stale_node_id, "Stale expired", "2025-12-31T00:00:00Z", 0.7),
        (ids.contradicted_node_id, "Contradicted downstream", None, 1.0),
        (ids.harmful_node_id, "Harmful violates", None, 1.0),
    ]
    for node_id, title, valid_to, confidence in memory_rows:
        conn.execute(
            """
            INSERT INTO memory_nodes(id, node_type, title, body, meta_json, importance,
                                     confidence_base, valid_from, valid_to, created_at, actor_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (node_id, "observation", title, title, "{}", 5, confidence, "2025-01-01T00:00:00Z", valid_to, ts, "actor"),
        )
    conn.execute(
        """
        INSERT INTO memory_recall_events(recall_id, query, strategies_used, node_ids_returned,
                                         context_json, limit_k, as_of, created_at, actor_id,
                                         agent_id, model_id, environment, run_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ids.recall_id,
            "prior lessons",
            json.dumps(["bm25", "graph"]),
            json.dumps([
                ids.helpful_node_id,
                ids.ignored_node_id,
                ids.stale_node_id,
                ids.contradicted_node_id,
                ids.harmful_node_id,
            ]),
            json.dumps({"instrument_id": ids.instrument_id, "strategy_id": "strat"}, sort_keys=True),
            5,
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
        ("e-helpful-use", "decision", ids.decision_id, "memory_node", ids.helpful_node_id, "supports", "2026-01-01T00:06:00Z"),
        ("e-contradict", "thesis", ids.thesis_id, "memory_node", ids.contradicted_node_id, "contradicts", "2026-01-01T00:06:30Z"),
        ("e-harmful", "decision", ids.decision_id, "memory_node", ids.harmful_node_id, "violates", "2026-01-01T00:07:00Z"),
        ("e-source", "memory_node", ids.helpful_node_id, "source", "source-1", "about", "2026-01-01T00:06:00Z"),
    ]
    for edge_id, sk, sid, tk, tid, et, created_at in edges:
        conn.execute(
            "INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)",
            (edge_id, sk, sid, tk, tid, et, None, "{}", created_at, "actor"),
        )
    return ids
