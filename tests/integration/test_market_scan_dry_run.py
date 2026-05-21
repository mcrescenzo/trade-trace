from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from trade_trace.cli import main as cli_main
from trade_trace.core import default_registry, dispatch
from trade_trace.mcp_server import mcp_call, mcp_tool_specs


def _bundle(action: str = "watch") -> dict:
    decision = {"action": action, "side": "yes", "reason": "caller chose action", "tags": ["market-scan"]}
    if action == "watch":
        decision["review_by"] = "2026-05-28T12:00:00Z"
    if action == "paper_enter":
        decision.update({"quantity": 10, "price": 0.52})
    return {
        "idempotency_key": "run-42:market-scan:pm:event-x:v1",
        "agent_id": "agent:research-bot",
        "venue": {"name": "Polymarket", "kind": "prediction_market", "external_id": "pm"},
        "instrument": {
            "asset_class": "prediction_market",
            "external_id": "event-x",
            "title": "Will event X happen?",
            "resolution_criteria_text": "Caller-supplied rules decide the outcome on the deadline.",
        },
        "snapshot": {
            "captured_at": "2026-05-21T12:00:00Z",
            "source": "manual",
            "source_url": "https://example.invalid/market",
            "price": 0.52,
            "bid": 0.50,
            "ask": 0.54,
            "mid": 0.52,
        },
        "sources": [{"kind": "url", "stance": "supports", "uri": "https://example.invalid/source", "title": "Evidence", "summary": "Caller supplied."}],
        "thesis": {"side": "yes", "body": "Caller thesis."},
        "forecast": {"kind": "binary", "resolution_rule_text": "Caller-supplied rules decide the outcome on the deadline.", "outcomes": [{"outcome_label": "YES", "probability": 0.57}, {"outcome_label": "NO", "probability": 0.43}]},
        "decision": decision,
        "attachments": {"attach_sources_to": ["thesis", "forecast", "decision"]},
        "current_time": "2026-05-21T13:00:00Z",
    }


def test_market_scan_dry_run_registered_cli_mcp_and_schema(capsys):
    reg = default_registry().get("market.scan.dry_run")
    assert reg.is_write is False
    assert reg.json_schema and reg.json_schema["examples"]
    assert "paper_enter" in reg.json_schema["properties"]["decision"]["properties"]["action"]["enum"]
    assert any(spec["name"] == "market.scan.dry_run" for spec in mcp_tool_specs())

    env = mcp_call("tool.schema", {"tool": "market.scan.dry_run"}, actor_id="agent:test")
    assert env.ok
    assert env.data["is_write"] is False
    assert env.data["json_schema"]["examples"]

    rc = cli_main(["market", "scan", "dry_run", "--idempotency-key", "cli-run", "--instrument-json", json.dumps({"asset_class": "prediction_market", "title": "T", "resolution_criteria_text": "Rules"}), "--decision-json", json.dumps({"action": "skip", "reason": "no edge"})])
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["data"]["normalized_action"] == "skip"


def test_market_scan_dry_run_watch_plan_keys_hash_and_primitive_arg_names():
    env = mcp_call("market.scan.dry_run", _bundle("watch"), actor_id="agent:test")
    assert env.ok
    data = env.data
    assert data["bundle_status"] == "ready_to_promote"
    assert data["promote_hash"].startswith("sha256:")
    assert data["promote_hash"] == mcp_call("market.scan.dry_run", _bundle("watch"), actor_id="agent:test").data["promote_hash"]
    assert [c["tool"] for c in data["ordered_calls"]] == [
        "venue.add", "instrument.add", "snapshot.add", "source.add", "thesis.add",
        "source.attach_to_thesis", "forecast.add", "source.attach_to_forecast",
        "decision.add", "source.attach_to_decision",
    ]
    decision = next(c for c in data["ordered_calls"] if c["tool"] == "decision.add")["args"]
    assert decision["type"] == "watch"
    assert "action" not in decision
    assert decision["review_by"] == "2026-05-28T12:00:00Z"
    assert data["child_idempotency_keys"]["decision:watch"] == "run-42:market-scan:pm:event-x:v1:decision:watch"
    assert data["child_idempotency_keys"]["source_attach:0:decision"].endswith(":source:0:attach:decision")


def test_market_scan_dry_run_skip_and_paper_enter_supported_with_matrix_checks():
    skip = mcp_call("market.scan.dry_run", _bundle("skip"), actor_id="agent:test")
    assert skip.ok
    skip_decision = next(c for c in skip.data["ordered_calls"] if c["tool"] == "decision.add")["args"]
    assert skip_decision["type"] == "skip"
    assert "review_by" not in skip_decision

    paper = mcp_call("market.scan.dry_run", _bundle("paper_enter"), actor_id="agent:test")
    assert paper.ok
    pdec = next(c for c in paper.data["ordered_calls"] if c["tool"] == "decision.add")["args"]
    assert pdec["type"] == "paper_enter"
    assert pdec["quantity"] == 10 and pdec["price"] == 0.52
    assert "paper_enter_is_journal_only" in {c["code"] for c in paper.data["checks"]}

    bad = _bundle("paper_enter")
    bad["decision"].pop("quantity")
    bad["decision"]["review_by"] = "2026-05-28T12:00:00Z"
    blocked = mcp_call("market.scan.dry_run", bad, actor_id="agent:test")
    assert blocked.ok
    assert blocked.data["bundle_status"] == "blocked"
    assert "decision_matrix_violation" in {c["code"] for c in blocked.data["checks"]}


def test_market_scan_dry_run_returns_required_warning_checks():
    args = _bundle("watch")
    args["sources"] = []
    args["forecast"] = None
    args["instrument"].pop("resolution_criteria_text")
    args["snapshot"] = {"captured_at": "2026-05-19T12:00:00Z", "source": "manual", "price": 0.50, "bid": 0.40, "ask": 0.60}
    args["decision"].pop("review_by")
    env = mcp_call("market.scan.dry_run", args, actor_id="agent:test")
    assert env.ok
    codes = {c["code"] for c in env.data["checks"]}
    assert {"missing_source", "missing_forecast", "missing_resolution_criteria", "missing_revisit_deadline", "wide_spread", "stale_snapshot", "caller_supplied_data_only"} <= codes

    args2 = _bundle("skip")
    args2["snapshot"] = {"captured_at": "2026-05-21T12:00:00Z", "price": 0.5}
    env2 = mcp_call("market.scan.dry_run", args2, actor_id="agent:test")
    assert "missing_bid_ask" in {c["code"] for c in env2.data["checks"]}


def test_market_scan_dry_run_blocks_timezone_naive_snapshot_captured_at_without_crashing():
    args = _bundle("watch")
    args["snapshot"]["captured_at"] = "2026-05-21T12:00:00"

    env = mcp_call("market.scan.dry_run", args, actor_id="agent:test")

    assert env.ok
    assert env.data["bundle_status"] == "blocked"
    assert any(
        c["severity"] == "blocking"
        and c["code"] == "invalid_timestamp"
        and c["field"] == "snapshot.captured_at"
        for c in env.data["checks"]
    )


def test_market_scan_dry_run_blocks_invalid_current_time():
    args = _bundle("watch")
    args["current_time"] = "not-a-timestamp"

    env = mcp_call("market.scan.dry_run", args, actor_id="agent:test")

    assert env.ok
    assert env.data["bundle_status"] == "blocked"
    assert any(
        c["severity"] == "blocking"
        and c["code"] == "invalid_timestamp"
        and c["field"] == "current_time"
        for c in env.data["checks"]
    )


def test_market_scan_dry_run_reports_snapshot_source_url_not_fetched_without_sources_url():
    args = _bundle("watch")
    args["sources"] = []
    args["snapshot"] = {"captured_at": "2026-05-21T12:00:00Z", "source_url": "https://example.invalid/market", "price": 0.52, "bid": 0.50, "ask": 0.54}

    env = mcp_call("market.scan.dry_run", args, actor_id="agent:test")

    assert env.ok
    assert any(
        c["severity"] == "info"
        and c["code"] == "source_url_not_fetched"
        and c["field"] == "snapshot.source_url"
        for c in env.data["checks"]
    )


def test_market_scan_dry_run_does_not_mutate_db(home: Path):
    db = home / "trade-trace.sqlite"
    before = sqlite3.connect(db).execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn = sqlite3.connect(db)
    before_counts = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for (name,) in before if not name.startswith("sqlite_")}
    conn.close()

    env = dispatch("market.scan.dry_run", {**_bundle("paper_enter"), "home": str(home)}, actor_id="agent:test")
    assert env.ok
    conn = sqlite3.connect(db)
    after_counts = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for (name,) in before if not name.startswith("sqlite_")}
    conn.close()
    assert after_counts == before_counts
