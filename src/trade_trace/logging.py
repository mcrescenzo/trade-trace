"""Operational logging module per docs/architecture/logging.md
(trade-trace-3zvl).

Thin wrapper around stdlib `logging` that adds:

- JSONL formatter mapping `LogRecord.__dict__` into the
  fixed-shape schema documented in logging.md §Format.
- Field-level redaction via the shared `scan_for_secrets` adapter.
- Per-process rotating file handler under `<home>/logs/` (or
  `$TRADE_TRACE_LOG_DIR`).
- stderr handler only in CLI mode (`TRADE_TRACE_TRANSPORT != "mcp"`).
- Idempotent `get_logger` so re-entry doesn't double-attach handlers.

Never raises into the request path; if file IO fails, the module
falls back to in-memory loggers and (in CLI mode) emits a single
startup warning to stderr.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trade_trace.storage.paths import resolve_home

_RESERVED_KEYS = (
    "ts", "level", "actor", "subject", "verb", "record_id",
    "message", "tool", "request_id",
)
_LOG_RECORD_INTERNALS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname",
    "filename", "module", "exc_info", "exc_text", "stack_info",
    "lineno", "funcName", "created", "msecs", "relativeCreated",
    "thread", "threadName", "processName", "process", "message",
    "asctime", "taskName",
})

_REDACTION_MARKER = "***"

_DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MiB
_DEFAULT_BACKUP_COUNT = 5


def _utc_now_iso() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _mcp_mode() -> bool:
    return os.environ.get("TRADE_TRACE_TRANSPORT", "").lower() == "mcp"


def _log_dir() -> Path:
    override = os.environ.get("TRADE_TRACE_LOG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return resolve_home() / "logs"


def _max_bytes() -> int:
    raw = os.environ.get("TRADE_TRACE_LOG_MAX_BYTES")
    if raw is None:
        return _DEFAULT_MAX_BYTES
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_BYTES


def _backup_count() -> int:
    raw = os.environ.get("TRADE_TRACE_LOG_BACKUP_COUNT")
    if raw is None:
        return _DEFAULT_BACKUP_COUNT
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_BACKUP_COUNT


def _redact_string(value: str) -> str:
    """Replace every secret-shaped substring with the redaction
    marker. Returns the value unchanged when nothing matched so
    short hot-path strings don't pay a string-build cost."""

    from trade_trace.security.patterns import compiled_patterns

    # Late-import so importing `trade_trace.logging` at module load
    # doesn't drag the security adapter — the logger may be
    # instantiated from very early init paths.
    found_any = False
    for pattern in compiled_patterns().values():
        new_value, n = pattern.subn(_REDACTION_MARKER, value)
        if n:
            value = new_value
            found_any = True
    if found_any:
        return value
    return value


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return type(value)(_redact(v) for v in value)
    return value


class JSONLFormatter(logging.Formatter):
    """Serialize a `LogRecord` to a single JSONL line. Reserved
    keys per logging.md §Format are populated from the record's
    `extra=` dict; anything else the caller passes in `extra=`
    flows through verbatim (after redaction)."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003 — stdlib name
        line: dict[str, Any] = {
            "ts": _utc_now_iso(),
            "level": record.levelname,
            "actor": getattr(record, "actor", record.name),
            "message": record.getMessage(),
        }
        for key in _RESERVED_KEYS:
            if key in line:
                continue
            if hasattr(record, key):
                line[key] = getattr(record, key)
        # Preserve any caller-provided extras that weren't reserved.
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_INTERNALS or key in line:
                continue
            if key.startswith("_"):
                continue
            line[key] = value
        line = _redact(line)
        return json.dumps(line, sort_keys=True, default=str, ensure_ascii=False)


_CONFIGURED: dict[str, logging.Logger] = {}


def _ensure_log_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        # `mkdir(mode=...)` honors the umask on POSIX; re-pin the bits
        # so a permissive umask doesn't widen the directory.
        try:
            path.chmod(0o700)
        except OSError:
            pass
        return True
    except OSError:
        return False


def _attach_file_handler(logger: logging.Logger, log_dir: Path) -> None:
    log_path = log_dir / "trade-trace.log"
    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=_max_bytes(),
        backupCount=_backup_count(),
        encoding="utf-8",
        delay=False,
    )
    handler.setFormatter(JSONLFormatter())
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        # Re-pin 0600 on the existing file (RotatingFileHandler opens
        # it with the umask-default bits). New rotated files inherit
        # via the rotator below.
        log_path.chmod(0o600)
    except OSError:
        pass

    def _rotator(source: str, dest: str) -> None:
        os.replace(source, dest)
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass

    handler.rotator = _rotator


def _attach_stderr_handler(logger: logging.Logger) -> None:
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(JSONLFormatter())
    handler.setLevel(logging.WARNING)
    logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a project-configured stdlib `Logger`. Idempotent —
    repeated calls with the same name return the same logger
    without re-attaching handlers."""

    if name in _CONFIGURED:
        return _CONFIGURED[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    # Clean any inherited handlers (test harness leakage, etc.).
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    log_dir = _log_dir()
    if _ensure_log_dir(log_dir):
        try:
            _attach_file_handler(logger, log_dir)
        except OSError as exc:
            if not _mcp_mode():
                # Single startup warning; not a request-path log line.
                sys.stderr.write(
                    f"trade_trace.logging: file handler unavailable ({exc}); "
                    "operational logs will not be persisted\n",
                )

    if not _mcp_mode():
        _attach_stderr_handler(logger)

    _CONFIGURED[name] = logger
    return logger


def _reset_for_tests() -> None:
    """Internal hook for the test harness to clear the
    configured-logger cache without poking module privates."""

    _CONFIGURED.clear()
