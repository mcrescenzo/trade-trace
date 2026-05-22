from __future__ import annotations

import json
import sqlite3

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.mcp_server import mcp_call
from trade_trace.reports.policy_candidates import report_policy_candidates
from trade_trace.storage.paths import db_path

NOW = "2026-01-10T00:00:00Z"


def _init_home(tmp_path):
    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}).model_dump(mode="json")["ok"] is True
    return home


def _insert_candidate(conn: sqlite3.Connection, node_id: str, pc: dict, *, valid_from: str = NOW, valid_to: str | None = None, invalidated_at: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO memory_nodes(id, node_type, title, body, meta_json, valid_from, valid_to, invalidated_at, created_at, actor_id)
        VALUES (?, 'reflection', ?, ?, ?, ?, ?, ?, ?, 'tester')
        """,
        (node_id, f"title {node_id}", pc.get("candidate_statement", "body"), json.dumps({"policy_candidate": pc}), valid_from, valid_to, invalidated_at, NOW),
    )


def test_policy_candidates_positive_source_backed_report(tmp_path):
    home = _init_home(tmp_path)
    conn = sqlite3.connect(db_path(home))
    try:
        _insert_candidate(conn, "mem-c1", {"status": "candidate", "candidate_statement": "Require two independent sources before promotion.", "scope": {"strategy_id": "strat-a", "playbook_id": "pb-a"}, "support": [{"source_id": "src-1"}], "contradictions": [{"source_id": "src-2"}], "missing_evidence": ["more replay coverage"], "replay_cases": ["case-1"], "recall_refs": ["recall-1"], "adherence_refs": ["adh-1"], "why_not_promoted": ["insufficient contradiction review"]})
        conn.commit()
        result = report_policy_candidates(conn)
    finally:
        conn.close()
    assert result["summary"]["metrics"]["candidate_count"] == 1
    item = result["policy_candidates"][0]
    assert item["node_id"] == "mem-c1"
    assert item["source_refs"] == ["src-1", "src-2"]
    assert item["evidence_counts"] == {"support": 1, "contradiction": 1}
    assert item["missing_evidence"] == ["more replay coverage"]
    assert item["replay_cases"] == ["case-1"]
    assert "NOT_PROMOTED_POLICY" in result["summary"]["caveat_codes"]
    assert result["groups"][0]["record_ids"]["memory_nodes"] == ["mem-c1"]


def test_policy_candidates_rejected_superseded_missing_evidence_and_ordering(tmp_path):
    home = _init_home(tmp_path)
    conn = sqlite3.connect(db_path(home))
    try:
        _insert_candidate(conn, "mem-a", {"lifecycle_status": "rejected", "candidate_statement": "A", "scope": {"strategy_id": "s1"}, "rejection_reason": "contradicted by src-x", "superseded_by": "mem-b", "evidence_gaps": ["no replay"]}, valid_from="2026-01-01T00:00:00Z")
        _insert_candidate(conn, "mem-b", {"lifecycle_status": "superseded", "candidate_statement": "B", "scope": {"strategy_id": "s1"}, "source_refs": ["src-b"]}, valid_from="2026-01-02T00:00:00Z")
        conn.commit()
        result = report_policy_candidates(conn, strategy_id="s1")
    finally:
        conn.close()
    assert [i["node_id"] for i in result["policy_candidates"]] == ["mem-a", "mem-b"]
    assert result["policy_candidates"][0]["why_not_promoted"] == ["contradicted by src-x"]
    assert result["policy_candidates"][0]["superseded_by"] == "mem-b"
    assert result["summary"]["metrics"]["missing_evidence_count"] == 1


def test_policy_candidates_filters_as_of_limit_and_mcp_read_only(tmp_path):
    home = _init_home(tmp_path)
    conn = sqlite3.connect(db_path(home))
    try:
        _insert_candidate(conn, "mem-old", {"status": "candidate", "scope": {"strategy_id": "s-old", "playbook_id": "pb"}}, valid_from="2026-01-01T00:00:00Z", valid_to="2026-01-05T00:00:00Z")
        _insert_candidate(conn, "mem-new", {"status": "candidate", "scope": {"strategy_id": "s-new", "playbook_id": "pb"}, "source_refs": ["src-new"]}, valid_from="2026-01-06T00:00:00Z")
        before_playbooks = conn.execute("SELECT COUNT(*) FROM playbook_versions").fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    envelope = _envelope(home, "report.policy_candidates", {"playbook_id": "pb", "as_of": "2026-01-07T00:00:00Z", "limit": 1})
    out = envelope["data"]
    assert out["summary"]["metrics"]["candidate_count"] == 1
    assert out["policy_candidates"][0]["node_id"] == "mem-new"
    assert out["truncated"] is False

    conn = sqlite3.connect(db_path(home))
    try:
        after_playbooks = conn.execute("SELECT COUNT(*) FROM playbook_versions").fetchone()[0]
        assert after_playbooks == before_playbooks
    finally:
        conn.close()
