"""Contract tests for `trade_trace.logging` per trade-trace-3zvl
(docs/architecture/logging.md).

These pin the wire-format and process-mode invariants of the
operational logging module. The module is intentionally thin —
a stdlib `logging.Logger` configured with a JSONL formatter,
a rotating file handler, and a redaction adapter — but those
guarantees matter enough that they get a dedicated test file.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_log_env(tmp_path, monkeypatch):
    """Each test gets its own log directory and a clean module state
    so handler registration in one test doesn't leak into the next."""

    monkeypatch.setenv("TRADE_TRACE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("TRADE_TRACE_TRANSPORT", raising=False)
    # Drop the cached module + any project loggers we set up so
    # `get_logger` rebuilds with the test env vars.
    import sys

    sys.modules.pop("trade_trace.logging", None)
    for name in list(logging.Logger.manager.loggerDict):
        if name.startswith("trade_trace"):
            logger = logging.getLogger(name)
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
            logger.handlers.clear()
    yield


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _log_file(tmp_path: Path) -> Path:
    return tmp_path / "logs" / "trade-trace.log"


def test_jsonl_line_shape_includes_required_keys(tmp_path: Path):
    from trade_trace.logging import get_logger

    log = get_logger("trade_trace.test_logging")
    log.info("draining outbox", extra={"subject": "outbox", "verb": "drain", "record_id": "42"})

    records = _read_lines(_log_file(tmp_path))
    assert len(records) == 1, records
    rec = records[0]
    assert set(rec) >= {"ts", "level", "actor", "message"}, rec
    assert rec["level"] == "INFO"
    assert rec["message"] == "draining outbox"
    assert rec["subject"] == "outbox"
    assert rec["verb"] == "drain"
    assert rec["record_id"] == "42"
    assert rec["ts"].endswith("Z"), rec
    # No raw LogRecord internals leak into the JSON line.
    for forbidden in ("args", "msg", "levelname", "filename"):
        assert forbidden not in rec, rec


def test_redaction_strips_known_secret_patterns(tmp_path: Path):
    from trade_trace.logging import get_logger

    log = get_logger("trade_trace.test_logging")
    eth = "0x1234567890abcdef1234567890abcdef12345678"
    log.warning(f"saw suspicious address {eth} in payload",
                extra={"verb": "scan"})

    rec = _read_lines(_log_file(tmp_path))[0]
    assert eth not in json.dumps(rec), rec
    # The redacted marker is in the message; the line is still
    # written so the operator knows something matched.
    assert "***" in rec["message"], rec


def test_redaction_strips_secret_patterns_inside_tuple_extra_payload(tmp_path: Path):
    from trade_trace.logging import get_logger

    log = get_logger("trade_trace.test_logging")
    eth = "0x1234567890abcdef1234567890abcdef12345678"
    log.warning(
        "tuple payload probe",
        extra={"verb": "scan", "payload": ("safe", {"nested": (eth,)})},
    )

    rec = _read_lines(_log_file(tmp_path))[0]
    dumped = json.dumps(rec)
    assert eth not in dumped, rec
    assert rec["payload"][0] == "safe"
    assert rec["payload"][1]["nested"][0] == "***"


def test_mcp_mode_does_not_attach_stderr_handler(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADE_TRACE_TRANSPORT", "mcp")
    import sys

    sys.modules.pop("trade_trace.logging", None)
    from trade_trace.logging import get_logger

    log = get_logger("trade_trace.test_logging")
    kinds = {type(h).__name__ for h in log.handlers}
    assert "StreamHandler" not in kinds, log.handlers
    # File handler still attached.
    assert any("FileHandler" in k or "RotatingFileHandler" in k for k in kinds), kinds


def test_cli_mode_attaches_stderr_handler_for_warn_and_above(monkeypatch, tmp_path, capsys):
    # No TRADE_TRACE_TRANSPORT means CLI mode.
    import sys

    sys.modules.pop("trade_trace.logging", None)
    from trade_trace.logging import get_logger

    log = get_logger("trade_trace.test_logging")
    log.info("not on stderr")
    log.warning("on stderr")

    captured = capsys.readouterr()
    assert "not on stderr" not in captured.err
    assert "on stderr" in captured.err


def test_repeat_get_logger_does_not_double_attach_handlers(tmp_path: Path):
    from trade_trace.logging import get_logger

    a = get_logger("trade_trace.test_logging")
    a_count = len(a.handlers)
    b = get_logger("trade_trace.test_logging")
    assert a is b
    assert len(b.handlers) == a_count


def test_rotation_triggered_by_max_bytes(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TRADE_TRACE_LOG_MAX_BYTES", "512")
    monkeypatch.setenv("TRADE_TRACE_LOG_BACKUP_COUNT", "1")
    import sys

    sys.modules.pop("trade_trace.logging", None)
    from trade_trace.logging import get_logger

    log = get_logger("trade_trace.test_logging")
    for i in range(100):
        log.info("padding-message-" + "x" * 32, extra={"i": i})

    log_dir = tmp_path / "logs"
    rotated = sorted(log_dir.glob("trade-trace.log*"))
    # At least the live file plus one backup (configured backup count).
    assert len(rotated) >= 2, list(log_dir.iterdir())


def test_log_file_permissions_are_0o600(tmp_path: Path):
    from trade_trace.logging import get_logger

    log = get_logger("trade_trace.test_logging")
    log.info("permission probe")

    mode = _log_file(tmp_path).stat().st_mode & 0o777
    assert mode == 0o600, oct(mode)


def test_log_dir_created_with_0o700(tmp_path: Path):
    from trade_trace.logging import get_logger

    log = get_logger("trade_trace.test_logging")
    log.info("dir probe")

    log_dir = tmp_path / "logs"
    mode = log_dir.stat().st_mode & 0o777
    assert mode == 0o700, oct(mode)


def test_drain_outbox_emits_operational_logs_end_to_end(tmp_path: Path):
    """Acceptance: at least one existing tool path emits operational
    logs through the module end-to-end. The JSONL exporter is the
    canonical first adopter — `drain_outbox` logs an INFO at start
    and finish."""

    from trade_trace.exporter import drain_outbox
    from trade_trace.mcp_server import mcp_call
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    home = tmp_path / "home"
    mcp_call("journal.init", {"home": str(home)})
    mcp_call("journal.config_set", {"home": str(home), "key": "outbox.jsonl_enabled", "value": "true", "_confirm": True, "idempotency_key": "log-cfg"}, actor_id="agent:default")
    mcp_call("memory.retain", {"home": str(home), "node_type": "observation", "body": "log probe", "idempotency_key": "log-mem"}, actor_id="agent:default")

    db = open_database(db_path(home))
    try:
        drain_outbox(db.connection, home)
        db.connection.commit()
    finally:
        db.close()

    log_path = tmp_path / "logs" / "trade-trace.log"
    assert log_path.exists(), "drain_outbox did not write any log lines"
    records = _read_lines(log_path)
    verbs = {r.get("verb") for r in records}
    assert "drain" in verbs, records
    drain_records = [r for r in records if r.get("verb") == "drain"]
    # At least the start and completion records.
    assert any("starting" in r.get("message", "") for r in drain_records), drain_records
    assert any("completed" in r.get("message", "") for r in drain_records), drain_records
