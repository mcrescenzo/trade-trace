from __future__ import annotations

import socket
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from trade_trace.core import dispatch

# Recent, run-relative timestamps so the snapshot/source never age past the
# journal.bundle.status stale_source_days (default 14d) threshold that
# market.scan.promote's final_check applies with a wall clock. Hardcoded past
# dates made this e2e a time-bomb: once the fixed source captured_at crossed
# 14 days old, source_attached flipped to "weak" and the "== ok" assertions
# failed on a clock tick rather than a code change. Computed once at import so
# it is stable across the dry_run + double-promote replay within a run.
_NOW = datetime.now(UTC)
_SNAPSHOT_AT = (_NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
_SOURCE_AT = (_NOW - timedelta(minutes=55)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bundle(action: str, key: str) -> dict[str, Any]:
    decision: dict[str, Any] = {
        "action": action,
        "side": "yes",
        "reason": f"Caller-selected {action} for deterministic e2e coverage.",
        "metadata_json": {"test": "market_scan_guided_e2e", "action": action},
    }
    if action == "watch":
        decision["review_by"] = "2026-05-28T12:00:00Z"
    if action == "paper_enter":
        decision.update({"quantity": 7, "price": 0.52, "fees": 0, "slippage": 0})
    return {
        "idempotency_key": key,
        "agent_id": "agent:e2e-market-scan",
        "model_id": "model:test",
        "environment": "pytest",
        "run_id": f"run-{action}",
        "venue": {"name": f"Guided PM {action}", "kind": "prediction_market", "external_id": f"pm-{action}"},
        "instrument": {
            "asset_class": "prediction_market",
            "external_id": f"event-{action}",
            "title": f"Guided market-scan {action} market",
            "resolution_criteria_text": "Caller-supplied resolution criteria; no fetching required.",
        },
        "snapshot": {
            "captured_at": _SNAPSHOT_AT,
            "source": "manual",
            "source_url": f"https://example.invalid/market/{action}",
            "price": 0.52,
            "bid": 0.51,
            "ask": 0.53,
            "mid": 0.52,
        },
        "sources": [
            {
                "kind": "url",
                "stance": "supports",
                "uri": f"https://example.invalid/research/{action}",
                "title": f"Caller supplied evidence for {action}",
                "summary": "Stored as provenance only; tests forbid network access.",
                "captured_at": _SOURCE_AT,
            }
        ],
        "thesis": {
            "side": "yes",
            "body": f"Caller-authored thesis for {action}.",
            "falsification_criteria": "A contrary settlement source would falsify this thesis.",
        },
        "forecast": {
            "kind": "binary",
            "resolution_rule_text": "Caller-supplied resolution criteria; no fetching required.",
            "yes_label": "YES",
            "outcomes": [
                {"outcome_label": "YES", "probability": 0.57},
                {"outcome_label": "NO", "probability": 0.43},
            ],
        },
        "decision": decision,
        "attachments": {"attach_sources_to": ["thesis", "forecast", "decision"]},
        "current_time": "2026-05-21T13:00:00Z",
    }


def _forbid_network(monkeypatch) -> None:
    def blocked(*args, **kwargs):  # pragma: no cover - failure path message matters
        raise AssertionError(f"network call attempted: args={args!r} kwargs={kwargs!r}")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "socket", blocked)


def _one(conn: sqlite3.Connection, table: str, row_id: str) -> sqlite3.Row:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    assert row is not None, f"missing {table} row {row_id}"
    return row


def _assert_db_links(home: Path, data: dict[str, Any], action: str) -> None:
    conn = sqlite3.connect(home / "trade-trace.sqlite")
    conn.row_factory = sqlite3.Row
    try:
        ids = data["ids"]
        venue = _one(conn, "venues", ids["venue_id"])
        instrument = _one(conn, "instruments", ids["instrument_id"])
        snapshot = _one(conn, "snapshots", ids["snapshot_id"])
        source = _one(conn, "sources", ids["source:0"])
        thesis = _one(conn, "theses", ids["thesis_id"])
        forecast = _one(conn, "forecasts", ids["forecast_id"])
        decision = _one(conn, "decisions", ids["decision_id"])

        assert venue["kind"] == "prediction_market"
        assert instrument["venue_id"] == ids["venue_id"]
        assert snapshot["instrument_id"] == ids["instrument_id"]
        assert source["uri"] == f"https://example.invalid/research/{action}"
        assert thesis["instrument_id"] == ids["instrument_id"]
        assert forecast["thesis_id"] == ids["thesis_id"]
        assert decision["type"] == action
        assert decision["instrument_id"] == ids["instrument_id"]
        assert decision["snapshot_id"] == ids["snapshot_id"]
        assert decision["thesis_id"] == ids["thesis_id"]
        assert decision["forecast_id"] == ids["forecast_id"]

        edge_targets = {
            (row["target_kind"], row["target_id"])
            for row in conn.execute(
                "SELECT target_kind, target_id FROM edges WHERE source_kind = 'source' AND source_id = ?",
                (ids["source:0"],),
            ).fetchall()
        }
        assert {
            ("thesis", ids["thesis_id"]),
            ("forecast", ids["forecast_id"]),
            ("decision", ids["decision_id"]),
        } <= edge_targets
    finally:
        conn.close()


def test_guided_market_scan_dry_run_is_local_only_and_covers_all_actions(home: Path, monkeypatch):
    _forbid_network(monkeypatch)

    for action in ("watch", "skip", "paper_enter"):
        args = {**_bundle(action, f"e2e-dry-run-{action}"), "home": str(home)}
        before = sqlite3.connect(home / "trade-trace.sqlite")
        before_counts = {
            name: before.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for (name,) in before.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        }
        before.close()

        env = dispatch("market.scan.dry_run", args, actor_id="agent:e2e-test")

        assert env.ok, env.error if not env.ok else None
        assert env.data["normalized_action"] == action
        assert env.data["bundle_status"] == "ready_to_promote"
        assert env.data["no_advice_boundary"] == {
            "external_fetch_performed": False,
            "trade_execution_performed": False,
            "advice_generated": False,
        }
        assert any(c["code"] == "source_url_not_fetched" for c in env.data["checks"])
        decision_step = next(step for step in env.data["ordered_calls"] if step["tool"] == "decision.add")
        assert decision_step["args"]["snapshot_id"] == "<snapshot_id>"
        assert decision_step["args"]["thesis_id"] == "<thesis_id>"
        assert decision_step["args"]["forecast_id"] == "<forecast_id>"

        after = sqlite3.connect(home / "trade-trace.sqlite")
        after_counts = {name: after.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in before_counts}
        after.close()
        assert after_counts == before_counts


def test_guided_market_scan_promote_materializes_links_status_and_replays(home: Path, monkeypatch):
    _forbid_network(monkeypatch)

    for action in ("watch", "skip", "paper_enter"):
        args = {**_bundle(action, f"e2e-promote-{action}"), "home": str(home)}
        dry = dispatch("market.scan.dry_run", args, actor_id="agent:e2e-test")
        assert dry.ok, dry.error if not dry.ok else None
        args["promote_hash"] = dry.data["promote_hash"]

        first = dispatch("market.scan.promote", args, actor_id="agent:e2e-test")
        second = dispatch("market.scan.promote", args, actor_id="agent:e2e-test")

        assert first.ok, first.error if not first.ok else None
        assert second.ok, second.error if not second.ok else None
        assert first.data["normalized_action"] == action
        assert first.data["ids"] == second.data["ids"]
        assert first.data["created_ids"]
        assert first.data["reused_ids"] == {}
        assert second.data["created_ids"] == {}
        assert second.data["reused_ids"]
        assert second.data["reused_ids"]["decision_id"] == first.data["ids"]["decision_id"]
        assert second.data["reused_ids"]["forecast_id"] == first.data["ids"]["forecast_id"]
        assert second.data["reused_ids"]["source_attach:0:decision"] == first.data["ids"]["source_attach:0:decision"]

        final_check = first.data["final_check"]
        assert first.data["bundle_status"] == final_check["status"]
        assert final_check["status"] in {"complete", "complete_enough", "needs_enrichment"}
        checks = {item["step"]: item for item in final_check["checklist"]}
        for step in ("venue_recorded", "instrument_recorded", "snapshot_recorded", "source_attached", "thesis_recorded", "forecast_recorded", "decision_recorded"):
            assert checks[step]["status"] == "ok"
        if action == "paper_enter":
            assert final_check["status"] == "complete_enough"
        else:
            assert final_check["status"] in {"needs_enrichment", "complete", "complete_enough"}

        _assert_db_links(home, first.data, action)


def test_guided_market_scan_promote_threads_current_time_into_final_check(home: Path, monkeypatch):
    """Per trade-trace-efmq: promote forwards current_time + stale_source_days
    into its terminal journal.bundle.status hop, so final_check.source_attached
    is reproducible under a pinned clock instead of flipping with wall time.

    Uses a FIXED source captured_at (not run-relative) and proves both the
    fresh and stale outcomes are selectable purely by current_time."""

    _forbid_network(monkeypatch)

    def _fixed_bundle(key: str, current_time: str) -> dict[str, Any]:
        bundle = _bundle("watch", key)
        bundle["snapshot"]["captured_at"] = "2026-05-21T12:00:00Z"
        bundle["sources"][0]["captured_at"] = "2026-05-21T12:00:00Z"
        bundle["current_time"] = current_time
        bundle["stale_snapshot_hours"] = 87600  # keep snapshot non-blocking under any clock
        bundle["home"] = str(home)
        return bundle

    # current_time 5 days after the fixed source -> inside 14d window -> ok.
    fresh_args = _fixed_bundle("efmq-fresh", "2026-05-26T12:00:00Z")
    dry = dispatch("market.scan.dry_run", fresh_args, actor_id="agent:efmq")
    assert dry.ok, dry.error if not dry.ok else None
    fresh_args["promote_hash"] = dry.data["promote_hash"]
    fresh = dispatch("market.scan.promote", fresh_args, actor_id="agent:efmq")
    assert fresh.ok, fresh.error if not fresh.ok else None
    fresh_checks = {c["step"]: c for c in fresh.data["final_check"]["checklist"]}
    assert fresh_checks["source_attached"]["status"] == "ok", fresh_checks["source_attached"]

    # Same bundle materialized once; a later status read with a far-future
    # clock flips the SAME source to weak -> determinism is caller-controlled.
    stale_status = dispatch(
        "journal.bundle.status",
        {"decision_id": fresh.data["ids"]["decision_id"], "stale_source_days": 14,
         "current_time": "2026-07-01T12:00:00Z", "home": str(home)},
        actor_id="agent:efmq",
    )
    assert stale_status.ok, stale_status.error if not stale_status.ok else None
    stale_checks = {c["step"]: c for c in stale_status.data["checklist"]}
    assert stale_checks["source_attached"]["status"] == "weak", stale_checks["source_attached"]
