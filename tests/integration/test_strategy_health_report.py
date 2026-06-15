from __future__ import annotations

import json
import re
import socket
import sqlite3
import urllib.request

from tests._direct_sql_builders import insert_instrument, insert_venue
from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.core import default_registry
from trade_trace.reports.strategy_health import report_strategy_health
from trade_trace.storage.paths import db_path


class _QueryTrace:
    """Capture every SQL statement a connection executes so a test can assert
    the per-strategy fan-out is gone (trade-trace-oupw)."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, sql: str) -> None:
        self.statements.append(" ".join(sql.split()))

    def count_substr(self, needle: str) -> int:
        return sum(1 for s in self.statements if needle in s)


def _assert_no_advice_profit_ranking_text(payload: object, *, description: str = "") -> None:
    text = (json.dumps(payload, sort_keys=True) + " " + description).lower()
    forbidden = re.compile(
        r"\b(buy recommendation|sell recommendation|trade recommendation|recommended trade|"
        r"best strategy|trade more|profitable|profit ranking|ranked by profit|"
        r"guaranteed profit|buy now|sell now)\b"
    )
    assert forbidden.findall(text) == []


def test_strategy_health_registered_and_schema():
    tool = default_registry().get("report.strategy_health")
    assert tool is not None
    assert tool.json_schema is not None
    assert set(tool.json_schema["properties"]) >= {"filter", "status", "as_of", "min_sample"}
    text = json.dumps(tool.json_schema) + " " + tool.description
    for phrase in ("best strategy", "trade more", "profitable"):
        assert phrase not in text.lower()


def test_strategy_health_does_not_open_network_and_keeps_low_n_skip_watch_local(home, monkeypatch):
    active_env = _mcp(home, "strategy.upsert", {"name": "Local Health", "slug": "local-health", "idempotency_key": "00000000-0000-4000-8000-health-net"})
    assert active_env.ok
    active = active_env.data["id"]
    conn = sqlite3.connect(db_path(home))
    try:
        insert_venue(conn, venue_id="vh_net")
        insert_instrument(conn, instrument_id="ih_net", venue_id="vh_net")
        conn.execute("INSERT INTO decisions(id, instrument_id, type, strategy_id, review_by, created_at, actor_id) VALUES ('dh_skip','ih_net','skip',?,NULL,'2026-01-02T00:00:00Z','actor-a')", (active,))
        conn.execute("INSERT INTO decisions(id, instrument_id, type, strategy_id, review_by, created_at, actor_id) VALUES ('dh_watch','ih_net','watch',?,'2026-01-05T00:00:00Z','2026-01-03T00:00:00Z','actor-a')", (active,))
        conn.execute("INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id) VALUES ('th_missing_ref','ih_net','yes','missing local source ref',?,'2026-01-01T00:00:00Z','actor-a')", (active,))
        conn.commit()
    finally:
        conn.close()

    def fail_network(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("strategy health must not fetch live data")

    monkeypatch.setattr(socket, "socket", fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)
    env = _mcp(home, "report.strategy_health", {"as_of": "2026-01-10T00:00:00Z", "min_sample": 5})
    assert env.ok, env
    group = env.data["groups"][0]
    assert group["key"] == active
    assert group["sections"]["decisions"]["record_ids"] == ["dh_skip", "dh_watch"]
    assert group["sections"]["review_due"]["record_ids"] == ["dh_watch"]
    assert group["sections"]["source_quality_issues"]["record_ids"] == ["th_missing_ref"]
    assert "low_n_decisions" in group["caveats"]
    assert "thesis_source_coverage_only_missing_refs" in group["caveats"]
    tool = default_registry().get("report.strategy_health")
    _assert_no_advice_profit_ranking_text(env.data, description=tool.description)


def test_strategy_health_surfaces_process_signals_and_filters(home):
    active_env = _mcp(home, "strategy.upsert", {"name": "Alpha", "slug": "alpha-health", "idempotency_key": "00000000-0000-4000-8000-health-a"})
    archived_env = _mcp(home, "strategy.upsert", {"name": "Bravo", "slug": "bravo-health", "status": "archived", "idempotency_key": "00000000-0000-4000-8000-health-b"})
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
    active_env = _mcp(home, "strategy.upsert", {"name": "Charlie", "slug": "charlie-health", "idempotency_key": "00000000-0000-4000-8000-health-c"})
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


def _seed_strategies(home, count: int, *, ns: str = "a") -> list[str]:
    """Create `count` active strategies, each with one decision, one thesis with
    a missing source ref, one open forecast, and a single (non-repeated) override.

    `ns` namespaces every fixed-id row so the helper can be called more than once
    against the same journal without colliding on shared ids. Returns the new
    strategy ids in creation order."""

    ids: list[str] = []
    for i in range(count):
        env = _mcp(home, "strategy.upsert", {
            "name": f"Fan {ns} {i}", "slug": f"fan-{ns}-{i:03d}",
            "idempotency_key": f"00000000-0000-4000-8000-fan{ns}{i:05d}",
        })
        assert env.ok, env
        ids.append(env.data["id"])

    conn = sqlite3.connect(db_path(home))
    try:
        insert_venue(conn, venue_id=f"vf_{ns}")
        insert_instrument(conn, instrument_id=f"if_{ns}", venue_id=f"vf_{ns}")
        conn.execute("INSERT INTO memory_nodes(id, node_type, title, body, valid_from, created_at, actor_id) VALUES (?,?,?,?,?,?,?)", (f"mn_fr_{ns}", "playbook_rule", "rule", "b", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "actor-a"))
        conn.execute("INSERT INTO memory_nodes(id, node_type, title, body, valid_from, created_at, actor_id) VALUES (?,?,?,?,?,?,?)", (f"mn_fref_{ns}", "reflection", "ref", "b", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "actor-a"))
        conn.execute("INSERT INTO playbooks(id, name, created_at, actor_id) VALUES (?,?,?,?)", (f"pb_f_{ns}", f"PB {ns}", "2026-01-01T00:00:00Z", "actor-a"))
        conn.execute("INSERT INTO playbook_versions(id, playbook_id, version, provenance_reflection_node_id, created_at, actor_id) VALUES (?,?,?,?,?,?)", (f"pbv_f_{ns}", f"pb_f_{ns}", 1, f"mn_fref_{ns}", "2026-01-01T00:00:00Z", "actor-a"))
        for i, sid in enumerate(ids):
            conn.execute("INSERT INTO decisions(id, instrument_id, type, review_by, strategy_id, created_at, actor_id) VALUES (?,?,?,?,?,?,?)", (f"df_{ns}_{i}", f"if_{ns}", "watch", "2026-01-05T00:00:00Z", sid, "2026-01-02T00:00:00Z", "actor-a"))
            conn.execute("INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id) VALUES (?,?,?,?,?,?,?)", (f"tf_{ns}_{i}", f"if_{ns}", "yes", "missing ref", sid, "2026-01-01T00:00:00Z", "actor-a"))
            conn.execute("INSERT INTO forecasts(id, thesis_id, kind, scoring_state, created_at, actor_id) VALUES (?,?,?,?,?,?)", (f"ff_{ns}_{i}", f"tf_{ns}_{i}", "binary", "pending", "2026-01-02T00:00:00Z", "actor-a"))
            conn.execute("INSERT INTO decision_playbook_rules(id, decision_id, playbook_version_id, rule_node_id, status, created_at, actor_id) VALUES (?,?,?,?,?,?,?)", (f"dpr_f_{ns}_{i}", f"df_{ns}_{i}", f"pbv_f_{ns}", f"mn_fr_{ns}", "overridden", "2026-01-03T00:00:00Z", "actor-a"))
        conn.commit()
    finally:
        conn.close()
    return ids


def _signal_query_count(trace: _QueryTrace) -> int:
    """Count statements that scan a per-strategy signal table. Each of these
    should fire exactly once across all strategies, not once per strategy."""

    return (
        trace.count_substr("FROM decisions d")
        + trace.count_substr("FROM theses t")
        + trace.count_substr("FROM forecasts f")
    )


def test_strategy_health_query_count_is_constant_in_strategy_count(home):
    """The per-strategy 5-query fan-out is replaced by a constant number of
    batch queries: doubling the strategy count must not change the number of
    signal-table scans (trade-trace-oupw)."""

    _seed_strategies(home, 3, ns="a")
    with sqlite3.connect(db_path(home)) as conn:
        small = _QueryTrace()
        conn.set_trace_callback(small)
        report_strategy_health(conn, as_of="2026-01-10T00:00:00Z")
        conn.set_trace_callback(None)

    _seed_strategies(home, 9, ns="b")  # now 12 active strategies
    with sqlite3.connect(db_path(home)) as conn:
        big = _QueryTrace()
        conn.set_trace_callback(big)
        data = report_strategy_health(conn, as_of="2026-01-10T00:00:00Z")
        conn.set_trace_callback(None)

    assert data["summary"]["metrics"]["strategy_count"] == 12
    # Five signal scans regardless of strategy count (decisions x3 incl. the
    # override join, theses x1, forecasts x1) — and stable across populations.
    assert _signal_query_count(small) == _signal_query_count(big)
    assert _signal_query_count(big) == 5
    # No per-strategy `WHERE d.strategy_id = ?` style scoping survives; the
    # batch path scopes with `strategy_id IN (...)` instead.
    assert big.count_substr("d.strategy_id IN (") >= 1


def test_strategy_health_multi_strategy_output_matches_per_strategy(home):
    """Batch partitioning must yield identical per-group output to running the
    report scoped to one strategy at a time."""

    ids = _seed_strategies(home, 4)

    combined = report_strategy_health(home_conn := sqlite3.connect(db_path(home)), as_of="2026-01-10T00:00:00Z")
    home_conn.close()

    by_key = {g["key"]: g for g in combined["groups"]}
    assert set(by_key) == set(ids)

    for sid in ids:
        scoped_conn = sqlite3.connect(db_path(home))
        scoped = report_strategy_health(
            scoped_conn,
            raw_filter={"strategy": {"strategy_id": sid}},
            as_of="2026-01-10T00:00:00Z",
        )
        scoped_conn.close()
        assert len(scoped["groups"]) == 1
        # Identical group payload whether the strategy was reported alone or as
        # part of the multi-strategy batch. The per-group `filter` echo
        # legitimately differs (the scoped run records the strategy_id it was
        # filtered to), so compare everything else.
        scoped_group = {k: v for k, v in scoped["groups"][0].items() if k != "filter"}
        combined_group = {k: v for k, v in by_key[sid].items() if k != "filter"}
        assert scoped_group == combined_group
