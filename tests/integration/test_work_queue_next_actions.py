from __future__ import annotations

import json
import sqlite3

from trade_trace.core import default_registry, dispatch
from trade_trace.storage.paths import db_path


def _conn(home):
    return sqlite3.connect(db_path(home))


def _seed_base(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO venues VALUES (?,?,?,?,?,?)", ("ven", "Venue", "manual", "{}", "2026-01-01T00:00:00Z", "test"))
    conn.execute(
        "INSERT INTO instruments (id, venue_id, title, asset_class, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)",
        ("inst", "ven", "Instrument", "equity", "{}", "2026-01-01T00:00:00Z", "test"),
    )
    conn.execute(
        "INSERT INTO theses (id, instrument_id, side, body, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)",
        ("th", "inst", "long", "body", "{}", "2026-01-01T00:01:00Z", "test"),
    )
    conn.execute(
        """
        INSERT INTO forecasts (id, thesis_id, kind, resolution_at, yes_label, resolution_rule_text,
                               scoring_support, scoring_state, metadata_json, created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        ("fc", "th", "binary", "2026-01-10T00:00:00Z", "yes", "caller supplies outcome", "supported", "pending", "{}", "2026-01-01T00:02:00Z", "test"),
    )
    conn.execute("INSERT INTO strategies(id, name, slug, status, created_at, updated_at, actor_id) VALUES (?,?,?,?,?,?,?)", ("strat-a", "Strategy A", "strat-a", "active", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "test"))


def _insert_decision(conn: sqlite3.Connection, decision_id: str, decision_type: str, created_at: str, *, review_by: str | None = None, forecast_id: str | None = None, playbook_version_id: str | None = None, strategy_id: str | None = "strat-a", run_id: str | None = "run-a") -> None:
    conn.execute(
        """
        INSERT INTO decisions (id, instrument_id, thesis_id, forecast_id, type, reason,
                               playbook_version_id, review_by, strategy_id, run_id, metadata_json, created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (decision_id, "inst", "th", forecast_id, decision_type, "because", playbook_version_id, review_by, strategy_id, run_id, json.dumps({}), created_at, "test"),
    )


def _call(tool: str, home, args: dict) -> dict:
    env = dispatch(tool, {"home": str(home), **args}, actor_id="agent:test", registry=default_registry()).model_dump(mode="json")
    assert env["ok"], env
    return env["data"]


def test_report_work_queue_contract_deterministic_filters_and_read_only(home):
    with _conn(home) as conn:
        _seed_base(conn)
        _insert_decision(conn, "d-watch-due", "watch", "2026-01-01T00:03:00Z", review_by="2026-01-05T00:00:00Z")
        _insert_decision(conn, "d-stale", "hold", "2026-01-01T00:04:00Z")
        _insert_decision(conn, "d-other-run", "watch", "2026-01-01T00:05:00Z", review_by="2026-01-05T00:00:00Z", run_id="run-b")
        before = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in ("decisions", "forecasts", "edges", "memory_nodes", "decision_playbook_rules")}

    args = {
        "as_of": "2026-01-20T00:00:00Z",
        "stale_threshold_days": 14,
        "filter": {"instrument": {"instrument_id": ["inst"]}, "strategy": {"strategy_id": "strat-a"}, "actors": {"run_id": ["run-a"]}},
    }
    data = _call("report.work_queue", home, args)
    data_again = _call("report.work_queue", home, args)
    assert data["work_queue"] == data_again["work_queue"]
    assert data["summary"]["caveats"]
    assert data["summary"]["metrics"]["item_count"] == 2
    assert {item["kind"] for item in data["work_queue"]} == {"review_due_watch", "review_stale_record"}

    required = {"kind", "priority", "caveat", "source_refs", "reason", "allowed_actions", "forbidden_actions", "closure_condition"}
    forbidden_terms = {"submitting_orders", "trading_execution", "fetch_market_data", "schedule_job", "assign_owner"}
    for item in data["work_queue"]:
        assert required <= set(item)
        assert item["source_refs"]
        assert item["closure_condition"]
        assert forbidden_terms <= set(item["forbidden_actions"])
        assert all("trade" not in action and "broker" not in action for action in item["allowed_actions"])
        assert {"kind": "run", "id": "run-b"} not in item["source_refs"]

    with _conn(home) as conn:
        after = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in before}
    assert after == before


def test_agent_next_actions_is_alias_projection_and_schema_registered(home):
    with _conn(home) as conn:
        _seed_base(conn)
        _insert_decision(conn, "d-watch-due", "watch", "2026-01-01T00:03:00Z", review_by="2026-01-05T00:00:00Z")

    args = {"as_of": "2026-01-20T00:00:00Z", "stale_threshold_days": 14, "kind": "review_due_watch"}
    work_queue = _call("report.work_queue", home, args)
    next_actions = _call("agent.next_actions", home, args)

    assert next_actions["summary"]["alias_of"] == "report.work_queue"
    assert next_actions["work_queue"] == work_queue["work_queue"]
    assert next_actions["next_actions"] == work_queue["next_actions"]
    assert [item["kind"] for item in next_actions["work_queue"]] == ["review_due_watch"]

    for tool in ("report.work_queue", "agent.next_actions"):
        schema_env = dispatch("tool.schema", {"tool": tool}, actor_id="agent:test", registry=default_registry()).model_dump(mode="json")
        assert schema_env["ok"], schema_env
        props = schema_env["data"]["json_schema"]["properties"]
        for key in ("filter", "as_of", "stale_threshold_days", "kinds", "kind"):
            assert key in props


def test_work_queue_boundary_language_has_no_scheduler_daemon_broker_execution_path(home):
    with _conn(home) as conn:
        _seed_base(conn)

    data = _call("agent.next_actions", home, {"as_of": "2026-01-20T00:00:00Z"})
    serialized = json.dumps(data).lower()
    assert "derived" in serialized
    assert "read_only" in serialized or "read-only" in serialized
    allowed_text = json.dumps([action for item in data["work_queue"] for action in item["allowed_actions"]]).lower()
    for forbidden in ("cron", "wallet", "webhook", "notify human", "broker truth", "profit", "best trade", "buy now", "sell now"):
        assert forbidden not in allowed_text
