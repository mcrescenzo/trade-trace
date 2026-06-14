"""Unit tests for report.rule_lineage's query path (bead trade-trace-a5dy).

These exercise the report function directly against seeded SQL so the
multi-version bridge fan-out and deterministic edge ordering are pinned without
the full tool/event machinery.
"""

from __future__ import annotations

import sqlite3

import pytest

from trade_trace.reports.rule_lineage import report_rule_lineage
from trade_trace.storage.database import open_database
from trade_trace.storage.paths import db_path

NOW = "2026-01-01T00:00:00Z"


@pytest.fixture
def conn(initialized_home):
    db = open_database(db_path(initialized_home))
    try:
        _seed(db.connection)
        db.connection.commit()
        yield db.connection
    finally:
        db.close()


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO venues(id, name, kind, created_at, actor_id) "
        "VALUES ('ven-1', 'Manual', 'prediction_market', ?, 'test')",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id) "
        "VALUES ('ins-1', 'ven-1', 'Instrument', 'prediction_market', ?, 'test')",
        (NOW,),
    )
    for did in ("dec-1", "dec-2"):
        conn.execute(
            "INSERT INTO decisions(id, instrument_id, type, created_at, actor_id) "
            "VALUES (?, 'ins-1', 'actual_enter', ?, 'test')",
            (did, NOW),
        )
    # One reflection, used as provenance for two versions.
    conn.execute(
        "INSERT INTO memory_nodes(id, node_type, body, valid_from, created_at, actor_id) "
        "VALUES ('ref-1', 'reflection', 'reflection body', ?, ?, 'test')",
        (NOW, NOW),
    )
    # One rule node recorded against BOTH versions (the bridge fan-out).
    conn.execute(
        "INSERT INTO memory_nodes(id, node_type, body, valid_from, created_at, actor_id) "
        "VALUES ('rule-1', 'playbook_rule', 'rule body', ?, ?, 'test')",
        (NOW, NOW),
    )
    conn.execute(
        "INSERT INTO playbooks(id, name, created_at, actor_id) "
        "VALUES ('pb-1', 'PB', ?, 'test')",
        (NOW,),
    )
    for vid, vnum in (("pv-1", 1), ("pv-2", 2)):
        conn.execute(
            "INSERT INTO playbook_versions(id, playbook_id, version, "
            "provenance_reflection_node_id, created_at, actor_id) "
            "VALUES (?, 'pb-1', ?, 'ref-1', ?, 'test')",
            (vid, vnum, NOW),
        )
    # Adherence: rule-1 on pv-1 (dec-1) and pv-2 (dec-2).
    conn.execute(
        "INSERT INTO decision_playbook_rules(id, decision_id, playbook_version_id, "
        "rule_node_id, status, created_at, actor_id) "
        "VALUES ('adh-1', 'dec-1', 'pv-1', 'rule-1', 'followed', ?, 'test')",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO decision_playbook_rules(id, decision_id, playbook_version_id, "
        "rule_node_id, status, created_at, actor_id) "
        "VALUES ('adh-2', 'dec-2', 'pv-2', 'rule-1', 'overridden', ?, 'test')",
        (NOW,),
    )
    # Reflection downstream edges (deliberately inserted out of order so the
    # report's ORDER BY is what produces deterministic output).
    edges = [
        ("e-supports", "supports", "decision", "dec-2"),
        ("e-about", "about", "decision", "dec-1"),
        ("e-derived", "derived_from", "outcome", "out-x"),
    ]
    for eid, etype, tkind, tid in edges:
        conn.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
            "edge_type, created_at, actor_id) "
            "VALUES (?, 'memory_node', 'ref-1', ?, ?, ?, ?, 'test')",
            (eid, tkind, tid, etype, NOW),
        )
    # Consumer-use edges INTO the reflection (decision used it).
    conn.execute(
        "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
        "edge_type, created_at, actor_id) "
        "VALUES ('e-use', 'decision', 'dec-1', 'memory_node', 'ref-1', "
        "'supports', ?, 'test')",
        (NOW,),
    )


def test_rule_anchor_fans_out_to_all_linked_versions(conn):
    data = report_rule_lineage(conn, rule_node_id="rule-1")
    assert data["summary"]["anchor"]["version_ids"] == ["pv-1", "pv-2"]
    assert data["summary"]["metrics"]["version_count"] == 2
    chains = {c["playbook_version_id"]: c for c in data["chains"]}
    # Anchored at the rule: each version's adherence is filtered to rule-1.
    assert [r["status"] for r in chains["pv-1"]["adherence_rows"]] == ["followed"]
    assert [r["status"] for r in chains["pv-2"]["adherence_rows"]] == ["overridden"]


def test_downstream_edges_are_grouped_and_deterministically_ordered(conn):
    data = report_rule_lineage(conn, playbook_version_id="pv-1")
    chain = data["chains"][0]
    grouped = chain["downstream_edges"]
    # Grouped by edge_type; the about edge points at dec-1.
    assert [e["target_id"] for e in grouped["about"]] == ["dec-1"]
    assert [e["target_id"] for e in grouped["supports"]] == ["dec-2"]
    assert [e["target_id"] for e in grouped["derived_from"]] == ["out-x"]
    # downstream_edge_count is the flat total across groups.
    assert chain["downstream_edge_count"] == 3


def test_record_ids_union_downstream_consumer_and_adherence(conn):
    data = report_rule_lineage(conn, playbook_version_id="pv-1")
    rec = data["chains"][0]["record_ids"]
    # dec-1 appears via about edge, adherence row, AND consumer-use edge —
    # deduped into a single sorted entry.
    assert rec["decisions"] == ["dec-1", "dec-2"]
    assert rec["outcomes"] == ["out-x"]
    assert rec["reflection_nodes"] == ["ref-1"]
    assert rec["rule_nodes"] == ["rule-1"]


def test_exactly_one_anchor_required(conn):
    with pytest.raises(ValueError, match="exactly one"):
        report_rule_lineage(conn)
    with pytest.raises(ValueError, match="exactly one"):
        report_rule_lineage(conn, rule_node_id="rule-1", playbook_version_id="pv-1")
