from __future__ import annotations

import json
import sqlite3

from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.core import dispatch
from trade_trace.dispatch_trace import ENABLE_ENV, PATH_ENV


def _lock_then_success_handler(calls: list[str]):
    def handler(args: dict[str, object], ctx: ToolContext) -> dict[str, object]:
        calls.append(ctx.request_id)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return {"request_id_seen": ctx.request_id}

    return handler


def test_single_writer_lock_retried_once_same_request_id_and_traced(monkeypatch, tmp_path):
    calls: list[str] = []
    sleeps: list[float] = []
    registry = ToolRegistry()
    registry.register("decision.add", _lock_then_success_handler(calls), is_write=True)
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.setenv(PATH_ENV, str(trace_path))
    monkeypatch.setattr("trade_trace.core.time.sleep", lambda seconds: sleeps.append(seconds))

    env = dispatch(
        "decision.add",
        {"home": str(tmp_path), "idempotency_key": "retry-test"},
        actor_id="agent:test",
        request_id="req-single-writer",
        registry=registry,
    )

    assert env.ok, env
    assert env.data["request_id_seen"] == "req-single-writer"
    assert calls == ["req-single-writer", "req-single-writer"]
    assert sleeps == [2.0]

    records = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert [(r["ok"], r["request_id"], r.get("attempt"), r.get("retry_of")) for r in records] == [
        (False, "req-single-writer", 1, None),
        (True, "req-single-writer", 2, "req-single-writer"),
    ]
    assert records[0]["error_code"] == "STORAGE_ERROR"
    assert records[0]["details"]["reason"] == "single_writer_lock"
    assert records[0]["retry_after_seconds"] == 2


def test_memory_recall_dispatch_uses_single_writer_retry_wrapper(monkeypatch, tmp_path):
    calls: list[str] = []
    sleeps: list[float] = []
    registry = ToolRegistry()
    registry.register("memory.recall", _lock_then_success_handler(calls), is_write=True)
    monkeypatch.setattr("trade_trace.core.time.sleep", lambda seconds: sleeps.append(seconds))

    env = dispatch(
        "memory.recall",
        {"home": str(tmp_path), "query": "risk notes", "idempotency_key": "recall-retry-test"},
        actor_id="agent:test",
        request_id="req-memory-recall",
        registry=registry,
    )

    assert env.ok, env
    assert calls == ["req-memory-recall", "req-memory-recall"]
    assert sleeps == [2.0]
