"""Console Logs page (trade-trace-jtec).

The Logs page reads operational log files defined in the
`trade-trace-3zvl` contract. These tests pin the empty-state
behavior, malformed-line tolerance, redaction posture, and the
no-Console-log-write invariant.
"""

from __future__ import annotations

import json
from pathlib import Path


def test_logs_context_handles_missing_log_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADE_TRACE_LOG_DIR", str(tmp_path / "never-exists"))
    from trade_trace.console.logs import logs_context

    ctx = logs_context(home=tmp_path)
    assert ctx["page_title"] == "Logs"
    assert ctx["rows"] == []
    assert ctx["empty_state"] is not None


def test_logs_context_parses_jsonl_lines(tmp_path: Path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "trade-trace.log"
    log_file.write_text(
        json.dumps({"ts": "2026-05-19T00:00:00.000Z", "level": "INFO", "actor": "agent:test", "verb": "drain", "message": "ok"}) + "\n"
        + json.dumps({"ts": "2026-05-19T00:00:01.000Z", "level": "WARN", "actor": "agent:test", "verb": "drain", "message": "slow"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADE_TRACE_LOG_DIR", str(log_dir))
    from trade_trace.console.logs import logs_context

    ctx = logs_context(home=tmp_path)
    assert len(ctx["rows"]) == 2
    assert ctx["rows"][0]["level"] == "INFO"
    assert ctx["rows"][1]["level"] == "WARN"


def test_logs_context_level_filter(tmp_path: Path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "trade-trace.log"
    log_file.write_text(
        json.dumps({"ts": "t1", "level": "INFO", "actor": "a", "message": "i"}) + "\n"
        + json.dumps({"ts": "t2", "level": "ERROR", "actor": "a", "message": "e"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADE_TRACE_LOG_DIR", str(log_dir))
    from trade_trace.console.logs import logs_context

    ctx = logs_context(home=tmp_path, level_filter="ERROR")
    assert len(ctx["rows"]) == 1
    assert ctx["rows"][0]["level"] == "ERROR"


def test_logs_context_tolerates_malformed_lines(tmp_path: Path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "trade-trace.log"
    log_file.write_text(
        "this is not json\n"
        + json.dumps({"ts": "t1", "level": "INFO", "actor": "a", "message": "ok"}) + "\n"
        + "[also not json]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADE_TRACE_LOG_DIR", str(log_dir))
    from trade_trace.console.logs import logs_context

    ctx = logs_context(home=tmp_path)
    # 3 rows: 1 parsed + 2 marked unparsed.
    assert len(ctx["rows"]) == 3
    unparsed = [r for r in ctx["rows"] if "_unparsed" in r]
    assert len(unparsed) == 2


def test_logs_context_redacts_secret_shapes(tmp_path: Path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "trade-trace.log"
    eth = "0x1234567890abcdef1234567890abcdef12345678"
    log_file.write_text(
        json.dumps({"ts": "t1", "level": "WARN", "actor": "a", "message": f"saw {eth}"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADE_TRACE_LOG_DIR", str(log_dir))
    from trade_trace.console.logs import logs_context

    ctx = logs_context(home=tmp_path)
    assert eth not in json.dumps(ctx["rows"][0])
    assert "***" in ctx["rows"][0]["message"]


def test_logs_context_does_not_write_to_log_file(tmp_path: Path, monkeypatch):
    """The Console must never write to the log files it reads.
    We hash the file before and after the read and assert
    bit-for-bit equality."""

    import hashlib

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "trade-trace.log"
    log_file.write_text(
        json.dumps({"ts": "t1", "level": "INFO", "actor": "a", "message": "ok"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADE_TRACE_LOG_DIR", str(log_dir))
    before = hashlib.sha256(log_file.read_bytes()).hexdigest()

    from trade_trace.console.logs import logs_context

    logs_context(home=tmp_path)
    logs_context(home=tmp_path, level_filter="INFO")
    logs_context(home=tmp_path, tail=5)

    after = hashlib.sha256(log_file.read_bytes()).hexdigest()
    assert before == after, "Console logs render mutated the log file"


def test_logs_context_reads_rotated_files(tmp_path: Path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "trade-trace.log").write_text(
        json.dumps({"ts": "current", "level": "INFO", "actor": "a", "message": "current"}) + "\n",
        encoding="utf-8",
    )
    (log_dir / "trade-trace.log.1").write_text(
        json.dumps({"ts": "rotated", "level": "INFO", "actor": "a", "message": "rotated"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADE_TRACE_LOG_DIR", str(log_dir))
    from trade_trace.console.logs import logs_context

    ctx = logs_context(home=tmp_path, tail=2000)
    messages = [r.get("message") for r in ctx["rows"]]
    assert "current" in messages
    assert "rotated" in messages


def test_logs_context_tail_keeps_live_entries_when_rotated_exceeds_tail(tmp_path: Path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "trade-trace.log.1").write_text(
        "".join(
            json.dumps({"ts": f"rotated-{i}", "level": "INFO", "actor": "a", "message": f"rotated-{i}"}) + "\n"
            for i in range(10)
        ),
        encoding="utf-8",
    )
    (log_dir / "trade-trace.log").write_text(
        json.dumps({"ts": "current", "level": "INFO", "actor": "a", "message": "current"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADE_TRACE_LOG_DIR", str(log_dir))
    from trade_trace.console.logs import logs_context

    ctx = logs_context(home=tmp_path, tail=5)
    messages = [r.get("message") for r in ctx["rows"]]
    assert len(messages) == 5
    assert messages == ["rotated-6", "rotated-7", "rotated-8", "rotated-9", "current"]


def test_base_template_includes_logs_nav_entry():
    source = Path(__file__).resolve().parents[2] / "frontend" / "console" / "src" / "main.tsx"
    text = source.read_text(encoding="utf-8")
    assert "to: '/logs'" in text
    assert "Logs page deferred" not in text
