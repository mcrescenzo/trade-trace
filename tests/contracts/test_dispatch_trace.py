from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.core import dispatch
from trade_trace.dispatch_trace import (
    ENABLE_ENV,
    HOME_ENV,
    MAX_BYTES_ENV,
    MAX_FILES_ENV,
    PATH_ENV,
)
from trade_trace.storage.paths import HomePathValidationError
from trade_trace.tools.errors import ToolError


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _registry(name: str, handler, *, is_write: bool = False) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(name, handler, description="trace test handler", is_write=is_write)
    return reg


def test_env_unset_performs_zero_trace_io(tmp_path: Path, monkeypatch):
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.delenv(ENABLE_ENV, raising=False)
    monkeypatch.setenv(PATH_ENV, str(trace_path))

    env = dispatch(
        "report.trace_ok",
        {},
        actor_id="cli:test",
        request_id="r-zero-io",
        registry=_registry("report.trace_ok", lambda args, ctx: {"ok": True}),
    )

    assert env.ok is True
    assert not trace_path.exists()


def test_env_set_traces_success_with_meta_latency_permissions_and_no_journal_db(
    tmp_path: Path, monkeypatch
):
    trace_path = tmp_path / "custom" / "dispatch.jsonl"
    home = tmp_path / "home"
    secret_key = "sk-" + "A" * 24
    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.setenv(PATH_ENV, str(trace_path))

    env = dispatch(
        "write.trace_ok",
        {"home": str(home), "idempotency_key": secret_key},
        actor_id="cli:test",
        request_id="r-success",
        registry=_registry("write.trace_ok", lambda args, ctx: {"ok": True}, is_write=True),
    )

    assert env.ok is True
    rec = _records(trace_path)[0]
    assert rec["tool"] == "write.trace_ok"
    assert rec["actor_id"] == "cli:test"
    assert rec["request_id"] == "r-success"
    assert rec["ok"] is True
    assert rec["error_code"] is None
    assert rec["meta"]["idempotency_source"] == "caller"
    assert rec["meta"]["idempotency_disabled"] is False
    assert isinstance(rec["latency_ms"], (int, float)) and rec["latency_ms"] >= 0
    assert stat.S_IMODE(os.stat(trace_path).st_mode) == 0o600
    assert secret_key not in trace_path.read_text()
    assert not list(tmp_path.rglob("*.db"))


def test_default_trace_path_ignores_unvalidated_raw_args_home_on_validation_error(
    tmp_path: Path, monkeypatch
):
    raw_home = tmp_path / "rejected" / ".." / "evil-home"
    would_have_been_trace = tmp_path / "evil-home" / "trace" / "dispatch.jsonl"
    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.delenv(PATH_ENV, raising=False)
    monkeypatch.delenv(HOME_ENV, raising=False)

    def rejects_home(args: dict, ctx: ToolContext) -> dict:
        raise HomePathValidationError(str(args["home"]))

    env = dispatch(
        "report.reject_home",
        {"home": str(raw_home)},
        actor_id="cli:test",
        request_id="r-rejected-home",
        registry=_registry("report.reject_home", rejects_home),
    )

    assert env.ok is False
    assert env.error.code == ErrorCode.VALIDATION_ERROR
    assert not would_have_been_trace.exists()
    assert not (tmp_path / "evil-home").exists()


def test_explicit_trace_path_does_not_chmod_existing_parent_directory(
    tmp_path: Path, monkeypatch
):
    parent = tmp_path / "existing-parent"
    parent.mkdir(mode=0o755)
    os.chmod(parent, 0o755)
    before = stat.S_IMODE(os.stat(parent).st_mode)
    trace_path = parent / "dispatch.jsonl"
    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.setenv(PATH_ENV, str(trace_path))

    env = dispatch(
        "report.parent_mode",
        {},
        actor_id="cli:test",
        request_id="r-parent-mode",
        registry=_registry("report.parent_mode", lambda args, ctx: {"ok": True}),
    )

    assert env.ok is True
    assert trace_path.exists()
    assert stat.S_IMODE(os.stat(parent).st_mode) == before == 0o755
    assert stat.S_IMODE(os.stat(trace_path).st_mode) == 0o600


def test_unknown_tool_and_early_idempotency_validation_are_traced(tmp_path: Path, monkeypatch):
    trace_path = tmp_path / "dispatch.jsonl"
    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.setenv(PATH_ENV, str(trace_path))
    reg = _registry("write.needs_key", lambda args, ctx: {"unreachable": True}, is_write=True)

    missing = dispatch("missing.tool", {}, actor_id="cli:test", request_id="r-missing", registry=reg)
    validation = dispatch("write.needs_key", {}, actor_id="cli:test", request_id="r-valid", registry=reg)

    assert missing.ok is False
    assert validation.ok is False
    records = _records(trace_path)
    assert [r["error_code"] for r in records] == ["NOT_FOUND", "VALIDATION_ERROR"]
    assert records[0]["tool"] == "missing.tool"
    assert records[1]["request_id"] == "r-valid"


def test_handler_toolerror_adapter_and_dry_run_paths_are_traced(tmp_path: Path, monkeypatch):
    trace_path = tmp_path / "dispatch.jsonl"
    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.setenv(PATH_ENV, str(trace_path))

    def adapter_error(args: dict, ctx: ToolContext) -> dict:
        raise ToolError(ErrorCode.ADAPTER_TIMEOUT, "adapter timed out", details={"reason": "upstream"})

    env = dispatch(
        "adapter.trace",
        {"_dry_run": True, "_allow_no_idempotency": True},
        actor_id="cli:test",
        request_id="r-adapter",
        registry=_registry("adapter.trace", adapter_error, is_write=True),
    )

    assert env.ok is False
    rec = _records(trace_path)[0]
    assert rec["error_code"] == "ADAPTER_TIMEOUT"
    assert rec["dry_run"] is True
    assert rec["meta"]["idempotency_disabled"] is True
    assert rec["details"]["reason"] == "upstream"


def test_single_writer_lock_storage_error_trace_details(tmp_path: Path, monkeypatch):
    import sqlite3

    trace_path = tmp_path / "dispatch.jsonl"
    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.setenv(PATH_ENV, str(trace_path))

    def locked(args: dict, ctx: ToolContext) -> dict:
        raise sqlite3.OperationalError("database is locked")

    env = dispatch(
        "write.locked",
        {"idempotency_key": "lock-key"},
        actor_id="cli:test",
        request_id="r-lock",
        registry=_registry("write.locked", locked, is_write=True),
    )

    assert env.ok is False
    rec = _records(trace_path)[0]
    assert rec["error_code"] == "STORAGE_ERROR"
    assert rec["details"]["reason"] == "single_writer_lock"
    assert rec["retry_after_seconds"] == 2
    assert "lock-key" not in trace_path.read_text()


def test_trace_rotates_at_configured_cap(tmp_path: Path, monkeypatch):
    trace_path = tmp_path / "dispatch.jsonl"
    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.setenv(PATH_ENV, str(trace_path))
    monkeypatch.setenv(MAX_BYTES_ENV, "1")
    monkeypatch.setenv(MAX_FILES_ENV, "2")
    reg = _registry("report.rotate", lambda args, ctx: {"ok": True})

    for idx in range(4):
        dispatch("report.rotate", {}, actor_id="cli:test", request_id=f"r-rot-{idx}", registry=reg)

    assert trace_path.exists()
    assert trace_path.with_name("dispatch.jsonl.2").exists()
    assert not trace_path.with_name("dispatch.jsonl.3").exists()
    assert stat.S_IMODE(os.stat(trace_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(trace_path.with_name("dispatch.jsonl.2")).st_mode) == 0o600
