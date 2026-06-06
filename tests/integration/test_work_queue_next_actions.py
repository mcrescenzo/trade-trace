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


def test_open_forecast_with_null_resolution_at_surfaces_as_resolve_due(home):
    # trade-trace-ptyi: an open binary forecast whose resolution_at is null can
    # never become due by clock, but it must still appear in the work_queue as a
    # resolve obligation so a work_queue-driven agent loop learns to act on it.
    with _conn(home) as conn:
        _seed_base(conn)
        conn.execute(
            """
            INSERT INTO forecasts (id, thesis_id, kind, resolution_at, yes_label, resolution_rule_text,
                                   scoring_support, scoring_state, metadata_json, created_at, actor_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("fc-null", "th", "binary", None, "yes", "caller supplies outcome", "supported", "pending", "{}", "2026-01-01T00:03:00Z", "test"),
        )

    data = _call("report.work_queue", home, {"as_of": "2026-01-20T00:00:00Z"})
    null_items = [
        item
        for item in data["work_queue"]
        if item["kind"] == "resolve_due_forecast"
        and {"kind": "forecast", "id": "fc-null"} in item["source_refs"]
    ]
    assert len(null_items) == 1, data["work_queue"]
    item = null_items[0]
    assert item["priority"] == "due"
    assert item["required_external_input"] is True
    assert item["due_at"] is None
    assert "resolution_at_missing" in item["trigger_evidence"]["reason_codes"]


def _insert_open_market(conn: sqlite3.Connection, market_id: str, close_at: str | None, state: str = "open") -> None:
    # markets.id is the instrument_id (snapshots/decisions/outcomes key on it).
    conn.execute(
        """
        INSERT INTO markets (id, source, external_id, title, question, url, state, mechanism,
                             bound_via, opened_at, close_at, venue_metadata_json, metadata_json,
                             created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (market_id, "polymarket", market_id, "m", "m?", "http://x", state, "clob", "adapter",
         "2026-01-01T00:00:00Z", close_at, "{}", "{}", "2026-01-01T00:00:00Z", "test"),
    )


def test_null_resolution_at_on_demonstrably_live_market_does_not_surface_as_resolve_due(home):
    # trade-trace-fe2f (inverse of trade-trace-ptyi): a forecast on a market that
    # is still trading (latest market row state='open', close_at in the future)
    # must NOT be flagged as a 'due' resolve obligation purely because its
    # resolution_at is null — there is no outcome to fetch yet. The forecast stays
    # 'open' (still visible in bootstrap unresolved_forecasts) rather than becoming
    # a spurious resolve_due_forecast.
    with _conn(home) as conn:
        _seed_base(conn)
        # Bind a live, future-dated open market on the seeded instrument `inst`.
        _insert_open_market(conn, "inst", close_at="2026-07-31T00:00:00Z", state="open")
        conn.execute(
            """
            INSERT INTO forecasts (id, thesis_id, kind, resolution_at, yes_label, resolution_rule_text,
                                   scoring_support, scoring_state, metadata_json, created_at, actor_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("fc-live-null", "th", "binary", None, "yes", "caller supplies outcome", "supported", "pending", "{}", "2026-01-01T00:03:00Z", "test"),
        )

    data = _call("report.work_queue", home, {"as_of": "2026-01-20T00:00:00Z"})
    resolve_items = [
        item
        for item in data["work_queue"]
        if item["kind"] == "resolve_due_forecast"
        and {"kind": "forecast", "id": "fc-live-null"} in item["source_refs"]
    ]
    assert resolve_items == [], data["work_queue"]


def test_null_resolution_at_on_closed_market_still_surfaces_as_resolve_due(home):
    # Guard the suppression boundary: when the linked market is no longer 'open'
    # (e.g. resolving) the missing-horizon resolve obligation must still surface,
    # preserving the trade-trace-ptyi guarantee for actually-resolvable markets.
    with _conn(home) as conn:
        _seed_base(conn)
        _insert_open_market(conn, "inst", close_at="2026-07-31T00:00:00Z", state="resolving")
        conn.execute(
            """
            INSERT INTO forecasts (id, thesis_id, kind, resolution_at, yes_label, resolution_rule_text,
                                   scoring_support, scoring_state, metadata_json, created_at, actor_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("fc-resolving-null", "th", "binary", None, "yes", "caller supplies outcome", "supported", "pending", "{}", "2026-01-01T00:03:00Z", "test"),
        )

    data = _call("report.work_queue", home, {"as_of": "2026-01-20T00:00:00Z"})
    resolve_items = [
        item
        for item in data["work_queue"]
        if item["kind"] == "resolve_due_forecast"
        and {"kind": "forecast", "id": "fc-resolving-null"} in item["source_refs"]
    ]
    assert len(resolve_items) == 1, data["work_queue"]
    assert "resolution_at_missing" in resolve_items[0]["trigger_evidence"]["reason_codes"]


def _insert_forecast(conn: sqlite3.Connection, forecast_id: str, resolution_at: str | None, created_at: str) -> None:
    conn.execute(
        """
        INSERT INTO forecasts (id, thesis_id, kind, resolution_at, yes_label, resolution_rule_text,
                               scoring_support, scoring_state, metadata_json, created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (forecast_id, "th", "binary", resolution_at, "yes", "caller supplies outcome", "supported", "pending", "{}", created_at, "test"),
    )


def test_report_work_queue_paginates_with_limit_and_stable_cursor(home):
    """trade-trace-1y9s: report.work_queue must page (limit + cursor + next_cursor,
    mirroring report.lifecycle) so a populated journal stays under the MCP token
    cap, while summary metrics report full-set totals and the per-obligation
    triple-serialization (per-group filter echo + work_queue + next_actions) no
    longer re-echoes the full filter per group."""
    with _conn(home) as conn:
        _seed_base(conn)  # seeds forecast `fc` (resolution_at 2026-01-10, due) -> 1 obligation
        for i in range(5):
            _insert_forecast(conn, f"fc-{i}", "2026-01-05T00:00:00Z", f"2026-01-01T01:0{i}:00Z")

    # Six total resolve_due obligations: seeded `fc` + five `fc-*`.
    first = _call("report.work_queue", home, {"as_of": "2026-01-20T00:00:00Z", "limit": 2})
    assert first["summary"]["metrics"]["item_count"] == 6  # full-set total, not page
    assert first["summary"]["metrics"]["returned_count"] == 2
    assert len(first["work_queue"]) == 2
    assert len(first["next_actions"]) == 2
    assert len(first["groups"]) == 2
    assert first["truncated"] is True
    assert first["next_cursor"]

    # The per-group filter echo (the triple-serialization bloat 1y9s flagged) is
    # gone; the normalized filter lives once in summary.filter.
    assert "filter" not in first["groups"][0]
    assert "filter" in first["summary"]

    # Walk the cursor: each page is disjoint and stable; the union covers all.
    seen = [item["item_id"] for item in first["work_queue"]]
    cursor = first["next_cursor"]
    pages = 1
    while cursor:
        nxt = _call("report.work_queue", home, {"as_of": "2026-01-20T00:00:00Z", "limit": 2, "cursor": cursor})
        page_ids = [item["item_id"] for item in nxt["work_queue"]]
        assert not set(page_ids) & set(seen)  # no overlap across pages
        seen.extend(page_ids)
        cursor = nxt["next_cursor"]
        pages += 1
        assert pages <= 6  # guard against cursor non-advance
    assert len(seen) == 6

    # The cursor walk reproduces the report's own stable emission order exactly
    # (a single large-limit pull returns the same sequence the pages concatenate
    # to), i.e. paging is order-stable and lossless.
    whole = _call("report.work_queue", home, {"as_of": "2026-01-20T00:00:00Z", "limit": 500})
    assert [item["item_id"] for item in whole["work_queue"]] == seen


def test_report_work_queue_rejects_invalid_limit_and_cursor(home):
    with _conn(home) as conn:
        _seed_base(conn)

    bad_limit = dispatch("report.work_queue", {"home": str(home), "limit": 0}, actor_id="agent:test", registry=default_registry()).model_dump(mode="json")
    assert bad_limit["ok"] is False
    assert "limit" in bad_limit["error"]["message"]

    bad_cursor = dispatch("report.work_queue", {"home": str(home), "cursor": "!!not-base64!!"}, actor_id="agent:test", registry=default_registry()).model_dump(mode="json")
    assert bad_cursor["ok"] is False


def test_bootstrap_suggested_call_path_recoverable_with_thirteen_obligations(home):
    """trade-trace-1y9s: the #1 bootstrap-suggested orientation calls — report.work_queue
    (call_001) and its safe alias agent.next_actions (call_002), both with args_template {} —
    must stay under the MCP token cap on a journal with 13+ obligations, where the un-paginated
    triple-serializing version overflowed (~60.5KB). The default-bounded transport surface keeps
    each call recoverable and the full backlog walkable via the cursor."""
    with _conn(home) as conn:
        _seed_base(conn)  # 1 due forecast
        for i in range(13):
            _insert_forecast(conn, f"fc-due-{i:02d}", "2026-01-05T00:00:00Z", f"2026-01-02T00:{i:02d}:00Z")

    # The MCP token cap is ~25k tokens; serialized result must stay well under it.
    # The pre-fix overflow at N=13 was ~60.5KB of JSON; assert a hard byte ceiling
    # that the un-paginated version blew past.
    MCP_BYTE_CEILING = 40_000

    for tool, args_template in (("report.work_queue", {}), ("agent.next_actions", {})):
        env = dispatch(tool, {"home": str(home), **args_template}, actor_id="agent:test", registry=default_registry()).model_dump(mode="json")
        assert env["ok"], env
        data = env["data"]
        # Default page is bounded; full backlog total is still reported honestly.
        assert data["summary"]["metrics"]["item_count"] == 14
        assert data["summary"]["metrics"]["returned_count"] < 14  # paged, not the whole backlog
        assert data["truncated"] is True
        assert data["next_cursor"]
        assert len(json.dumps(env)) < MCP_BYTE_CEILING, f"{tool} serialized result too large"

    # The whole 14-item backlog is recoverable by walking the cursor from call_001.
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        args = {"as_of": None, "limit": 5}
        if cursor:
            args["cursor"] = cursor
        page = _call("report.work_queue", home, {k: v for k, v in args.items() if v is not None})
        seen.extend(item["item_id"] for item in page["work_queue"])
        cursor = page["next_cursor"]
        pages += 1
        if not cursor:
            break
        assert pages <= 14
    assert len(seen) == 14
    assert len(set(seen)) == 14  # no duplicates across pages


def test_agent_next_actions_alias_paginates_with_cursor(home):
    """The safe alias must share the same limit/cursor pagination so call_002 is
    bounded exactly like call_001 (trade-trace-1y9s)."""
    with _conn(home) as conn:
        _seed_base(conn)
        for i in range(4):
            _insert_forecast(conn, f"fc-{i}", "2026-01-05T00:00:00Z", f"2026-01-01T01:0{i}:00Z")

    first = _call("agent.next_actions", home, {"as_of": "2026-01-20T00:00:00Z", "limit": 2})
    assert first["summary"]["alias_of"] == "report.work_queue"
    assert first["summary"]["metrics"]["item_count"] == 5
    assert len(first["work_queue"]) == 2
    assert first["truncated"] is True
    second = _call("agent.next_actions", home, {"as_of": "2026-01-20T00:00:00Z", "limit": 2, "cursor": first["next_cursor"]})
    assert not {i["item_id"] for i in second["work_queue"]} & {i["item_id"] for i in first["work_queue"]}


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
