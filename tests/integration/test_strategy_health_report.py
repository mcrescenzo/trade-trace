from __future__ import annotations

import json
import sqlite3

from tests._direct_sql_builders import insert_instrument, insert_venue
from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.core import default_registry
from trade_trace.storage.paths import db_path


def test_strategy_health_registered_and_schema():
    tool = default_registry().get("report.strategy_health")
    assert tool is not None
    assert tool.json_schema is not None
    assert set(tool.json_schema["properties"]) >= {"filter", "status", "as_of", "min_sample"}
    text = json.dumps(tool.json_schema) + " " + tool.description
    for phrase in ("best strategy", "trade more", "profitable"):
        assert phrase not in text.lower()


def test_strategy_health_surfaces_process_signals_and_filters(home):
    active_env = _mcp(home, "strategy.create", {"name": "Alpha", "slug": "alpha-health", "idempotency_key": "00000000-0000-4000-8000-health-a"})
    archived_env = _mcp(home, "strategy.create", {"name": "Bravo", "slug": "bravo-health", "status": "archived", "idempotency_key": "00000000-0000-4000-8000-health-b"})
    assert active_env.ok and archived_env.ok
    active = active_env.data["id"]
    archived = archived_env.data["id"]
    conn = sqlite3.connect(db_path(home))
    try:
        insert_venue(conn, venue_id="vh")
        insert_instrument(conn, instrument_id="ih", venue_id="vh")
        conn.execute("INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id, run_id, model_id) VALUES ('th_active','ih','yes','body',?, '2026-01-01T00:00:00Z','actor-a','run-a','model-a')", (active,))
        conn.execute("INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id, run_id, model_id) VALUES ('th_other_actor','ih','yes','body',?, '2026-01-01T00:00:00Z','actor-b','run-a','model-a')", (active,))
        conn.execute("INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id, run_id, model_id) VALUES ('th_other_run','ih','yes','body',?, '2026-01-01T00:00:00Z','actor-a','run-b','model-a')", (active,))
        conn.execute("INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id, run_id, model_id) VALUES ('th_other_model','ih','yes','body',?, '2026-01-01T00:00:00Z','actor-a','run-a','model-b')", (active,))
        conn.execute("INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id, run_id, model_id) VALUES ('th_other_created','ih','yes','body',?, '2025-12-31T00:00:00Z','actor-a','run-a','model-a')", (active,))
        conn.execute("INSERT INTO forecasts(id, thesis_id, kind, scoring_state, run_id, model_id, created_at, actor_id) VALUES ('fh_open','th_active','binary','pending','run-a','model-a','2026-01-02T00:00:00Z','actor-a')")
        for i in range(2):
            conn.execute("INSERT INTO decisions(id, instrument_id, type, review_by, strategy_id, run_id, model_id, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?,?)", (f"dh_{i}", "ih", "watch", "2026-01-05T00:00:00Z", active, "run-a", "model-a", f"2026-01-0{i+2}T00:00:00Z", "actor-a"))
        conn.execute("INSERT INTO memory_nodes(id, node_type, title, body, valid_from, created_at, actor_id) VALUES ('mn_rule','playbook_rule','rule','body','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','actor-a')")
        conn.execute("INSERT INTO memory_nodes(id, node_type, title, body, valid_from, created_at, actor_id) VALUES ('mn_ref','reflection','reflection','body','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','actor-a')")
        conn.execute("INSERT INTO playbooks(id, name, created_at, actor_id) VALUES ('pb_h','PB','2026-01-01T00:00:00Z','actor-a')")
        conn.execute("INSERT INTO playbook_versions(id, playbook_id, version, provenance_reflection_node_id, created_at, actor_id) VALUES ('pbv_h','pb_h',1,'mn_ref','2026-01-01T00:00:00Z','actor-a')")
        for i in range(2):
            conn.execute("INSERT INTO decision_playbook_rules(id, decision_id, playbook_version_id, rule_node_id, status, created_at, actor_id) VALUES (?,?,?,?,?,?,?)", (f"dpr_h_{i}", f"dh_{i}", "pbv_h", "mn_rule", "overridden", "2026-01-03T00:00:00Z", "actor-a"))
        conn.execute("INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id) VALUES ('th_arch','ih','yes','body',?, '2026-01-01T00:00:00Z','actor-a')", (archived,))
        conn.commit()
    finally:
        conn.close()

    env = _mcp(home, "report.strategy_health", {"as_of": "2026-01-10T00:00:00Z", "filter": {"actors": {"actor_id": ["actor-a"], "run_id": ["run-a"], "model_id": ["model-a"]}, "time_window": {"created_at_gte": "2026-01-01T00:00:00Z"}}})
    assert env.ok, env
    data = env.data
    assert data["summary"]["metrics"]["strategy_count"] == 1
    group = data["groups"][0]
    assert group["key"] == active
    assert group["sections"]["review_due"]["record_ids"] == ["dh_0", "dh_1"]
    assert group["sections"]["open_unresolved_forecasts"]["record_ids"] == ["fh_open"]
    assert group["sections"]["source_quality_issues"]["record_ids"] == ["th_active"]
    assert group["sections"]["repeated_overrides"]["record_ids"] == ["dh_0", "dh_1"]
    assert group["sections"]["policy_candidates"]["count"] == 0
    assert "policy_candidates_unsupported_local_surface" in group["caveats"]
    assert "low_n_decisions" in group["caveats"]
    assert "bravo-health" not in json.dumps(data)
    for phrase in ("best strategy", "trade more", "profitable"):
        assert phrase not in json.dumps(data).lower()

    archived_env = _mcp(home, "report.strategy_health", {"status": "archived", "as_of": "2026-01-10T00:00:00Z"})
    assert archived_env.ok
    assert archived_env.data["groups"][0]["key"] == archived


def test_strategy_health_repeated_overrides_requires_two(home):
    active_env = _mcp(home, "strategy.create", {"name": "Charlie", "slug": "charlie-health", "idempotency_key": "00000000-0000-4000-8000-health-c"})
    assert active_env.ok
    active = active_env.data["id"]
    conn = sqlite3.connect(db_path(home))
    try:
        insert_venue(conn, venue_id="vh2")
        insert_instrument(conn, instrument_id="ih2", venue_id="vh2")
        conn.execute("INSERT INTO decisions(id, instrument_id, type, strategy_id, created_at, actor_id) VALUES ('dh_single','ih2','watch',?,'2026-01-02T00:00:00Z','actor-a')", (active,))
        conn.execute("INSERT INTO memory_nodes(id, node_type, title, body, valid_from, created_at, actor_id) VALUES ('mn_rule2','playbook_rule','rule','body','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','actor-a')")
        conn.execute("INSERT INTO memory_nodes(id, node_type, title, body, valid_from, created_at, actor_id) VALUES ('mn_ref2','reflection','reflection','body','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','actor-a')")
        conn.execute("INSERT INTO playbooks(id, name, created_at, actor_id) VALUES ('pb_h2','PB','2026-01-01T00:00:00Z','actor-a')")
        conn.execute("INSERT INTO playbook_versions(id, playbook_id, version, provenance_reflection_node_id, created_at, actor_id) VALUES ('pbv_h2','pb_h2',1,'mn_ref2','2026-01-01T00:00:00Z','actor-a')")
        conn.execute("INSERT INTO decision_playbook_rules(id, decision_id, playbook_version_id, rule_node_id, status, created_at, actor_id) VALUES ('dpr_single','dh_single','pbv_h2','mn_rule2','overridden','2026-01-03T00:00:00Z','actor-a')")
        conn.commit()
    finally:
        conn.close()

    env = _mcp(home, "report.strategy_health", {"as_of": "2026-01-10T00:00:00Z"})
    assert env.ok, env
    group = env.data["groups"][0]
    assert group["sections"]["repeated_overrides"]["count"] == 0
    assert group["sections"]["repeated_overrides"]["record_ids"] == []
    assert env.data["summary"]["metrics"]["repeated_overrides"] == 0

    conn = sqlite3.connect(db_path(home))
    try:
        conn.execute("INSERT INTO decisions(id, instrument_id, type, strategy_id, created_at, actor_id) VALUES ('dh_second','ih2','watch',?,'2026-01-03T00:00:00Z','actor-a')", (active,))
        conn.execute("INSERT INTO decision_playbook_rules(id, decision_id, playbook_version_id, rule_node_id, status, created_at, actor_id) VALUES ('dpr_second','dh_second','pbv_h2','mn_rule2','overridden','2026-01-04T00:00:00Z','actor-a')")
        conn.commit()
    finally:
        conn.close()

    env = _mcp(home, "report.strategy_health", {"as_of": "2026-01-10T00:00:00Z"})
    assert env.ok, env
    group = env.data["groups"][0]
    assert group["sections"]["repeated_overrides"]["count"] == 2
    assert group["sections"]["repeated_overrides"]["record_ids"] == ["dh_single", "dh_second"]
    assert env.data["summary"]["metrics"]["repeated_overrides"] == 2
