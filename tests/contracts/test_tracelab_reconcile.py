from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tools.tracelab.reconcile import reconcile
from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.core import dispatch
from trade_trace.dispatch_trace import ENABLE_ENV, PATH_ENV, REPLAY_SECRET_ENV
from trade_trace.replay_fingerprint import compute_replay_fingerprint


def _fp(secret: str, event_type: str, actor: str, key: str) -> dict:
    return compute_replay_fingerprint(secret=secret, event_type=event_type, actor_id=actor, idempotency_key=key)


def test_replay_fingerprint_stable_secret_scoped_and_canonical_collision_safe():
    a = _fp("s1", "event", "actor", "k")
    assert a == _fp("s1", "event", "actor", "k")
    assert a["digest"].islower() and len(a["digest"]) == 64
    assert a["version"] == 1
    assert a != _fp("s1", "event2", "actor", "k")
    assert a != _fp("s1", "event", "actor2", "k")
    assert a != _fp("s1", "event", "actor", "k2")
    assert a != _fp("s2", "event", "actor", "k")
    assert _fp("s", "a", "b:c", "d") != _fp("s", "a:b", "c", "d")


def test_dispatch_trace_emits_non_secret_fingerprint_for_mapped_write(tmp_path: Path, monkeypatch):
    trace_path = tmp_path / "dispatch.jsonl"
    raw_key = "raw-idempotency-key"
    secret = "synthetic-test-secret"
    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.setenv(PATH_ENV, str(trace_path))
    monkeypatch.setenv(REPLAY_SECRET_ENV, secret)
    reg = ToolRegistry()
    reg.register("decision.add", lambda args, ctx: {"ok": True}, description="test", is_write=True)

    env = dispatch("decision.add", {"idempotency_key": raw_key}, actor_id="cli:test", request_id="r1", registry=reg)

    assert env.ok is True
    text = trace_path.read_text()
    assert raw_key not in text
    assert secret not in text
    rec = json.loads(text)
    assert rec["replay_fingerprint"] == _fp(secret, "decision.created", "cli:test", raw_key)


def _db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, actor_id TEXT NOT NULL, idempotency_key TEXT, request_id TEXT)")
    conn.execute("CREATE TABLE memory_recall_events(recall_id TEXT PRIMARY KEY)")
    return conn


def test_reconciler_request_id_and_idempotent_replay_mapping(tmp_path: Path):
    db_path = tmp_path / "journal.db"
    trace_path = tmp_path / "dispatch.jsonl"
    secret = "reconcile-secret"
    fp = _fp(secret, "decision.created", "cli:test", "idem-1")
    with _db(db_path) as conn:
        conn.execute("INSERT INTO events(event_type, actor_id, idempotency_key, request_id) VALUES (?, ?, ?, ?)", ("decision.created", "cli:test", "idem-1", "first-request"))
    trace_path.write_text("\n".join([
        json.dumps({"tool": "decision.add", "actor_id": "cli:test", "request_id": "first-request", "ok": True}),
        json.dumps({"tool": "decision.add", "actor_id": "cli:test", "request_id": "replay-request", "ok": True, "replay_fingerprint": fp}),
    ]) + "\n")

    report = reconcile(trace_path, db_path, replay_secret=secret)

    assert report["buckets"] == {"idempotent_replay_zero_new_rows": 1, "request_id_events": 1}
    assert report["items"][0]["event_count"] == 1
    assert report["items"][1]["event_count"] == 0
    assert report["items"][1]["prior_events"][0]["request_id"] == "first-request"
    assert "idempotency_key" not in report["items"][1]["prior_events"][0]
    assert "idempotency_key" not in report["items"][0]["events"][0]


def test_reconciler_rejects_malformed_or_stale_replay_fingerprint_metadata(tmp_path: Path):
    db_path = tmp_path / "journal.db"
    trace_path = tmp_path / "dispatch.jsonl"
    secret = "reconcile-secret"
    stale_fp = _fp(secret, "decision.created", "cli:test", "idem-1")
    stale_fp["version"] = 0
    with _db(db_path) as conn:
        conn.execute("INSERT INTO events(event_type, actor_id, idempotency_key, request_id) VALUES (?, ?, ?, ?)", ("decision.created", "cli:test", "idem-1", "first-request"))
    trace_path.write_text(json.dumps({"tool": "decision.add", "actor_id": "cli:test", "request_id": "replay-request", "ok": True, "replay_fingerprint": stale_fp}) + "\n")

    report = reconcile(trace_path, db_path, replay_secret=secret)

    assert report["buckets"] == {"zero_events_unmapped": 1}
    assert report["items"][0]["prior_events"] == []


def test_reconciler_readonly_uri_handles_metacharacter_db_path(tmp_path: Path):
    db_path = tmp_path / "journal #one?.db"
    trace_path = tmp_path / "dispatch.jsonl"
    with _db(db_path) as conn:
        conn.execute("INSERT INTO events(event_type, actor_id, idempotency_key, request_id) VALUES (?, ?, ?, ?)", ("decision.created", "cli:test", "idem-1", "request-1"))
    trace_path.write_text(json.dumps({"tool": "decision.add", "actor_id": "cli:test", "request_id": "request-1", "ok": True}) + "\n")

    report = reconcile(trace_path, db_path)

    assert report["buckets"] == {"request_id_events": 1}


def test_reconciler_zero_row_buckets(tmp_path: Path):
    db_path = tmp_path / "journal.db"
    trace_path = tmp_path / "dispatch.jsonl"
    with _db(db_path) as conn:
        conn.execute("INSERT INTO memory_recall_events(recall_id) VALUES ('recall-1')")
    records = [
        {"tool": "memory.recall", "request_id": "recall-1", "ok": True},
        {"tool": "decision.add", "request_id": "dry", "ok": True, "dry_run": True},
        {"tool": "market.bind", "request_id": "valid", "ok": False, "error_code": "VALIDATION_ERROR", "details": {"pattern_kind": "condition_id_hex64"}},
        {"tool": "adapter.polymarket", "request_id": "seeded", "ok": False, "error_code": "ADAPTER_PROTOCOL_ERROR", "details": {"reason": "seeded"}},
        {"tool": "adapter.polymarket", "request_id": "genuine", "ok": False, "error_code": "ADAPTER_PROTOCOL_ERROR", "details": {"reason": "bad_wire"}},
    ]
    trace_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    report = reconcile(trace_path, db_path)

    assert report["buckets"] == {
        "adapter_protocol_error_flagged": 1,
        "dry_run_zero_rows": 1,
        "expected_validation_error_pattern": 1,
        "memory_recall_zero_events": 1,
        "seeded_adapter_protocol_error_excluded": 1,
    }
