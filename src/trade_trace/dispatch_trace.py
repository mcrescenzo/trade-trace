"""Best-effort, env-gated append-only dispatch trace.

Tracing is intentionally off by default and writes only to standalone JSONL
files, never to the journal SQLite database. The helper swallows all trace I/O
failures so enabling diagnostics cannot change dispatch semantics.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from trade_trace.contracts.envelope import ErrorEnvelope, SuccessEnvelope, dump_envelope
from trade_trace.security import redact_for_log, scan_text

ENABLE_ENV = "TRADE_TRACE_DISPATCH_TRACE"
PATH_ENV = "TRADE_TRACE_DISPATCH_TRACE_PATH"
MAX_BYTES_ENV = "TRADE_TRACE_DISPATCH_TRACE_MAX_BYTES"
MAX_FILES_ENV = "TRADE_TRACE_DISPATCH_TRACE_MAX_FILES"
HOME_ENV = "TRADE_TRACE_HOME"

_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_MAX_FILES = 5


def is_enabled() -> bool:
    value = os.environ.get(ENABLE_ENV)
    return value is not None and value.strip().lower() not in {"", "0", "false", "no", "off"}


def now_ns() -> int:
    return time.perf_counter_ns()


def _positive_int_from_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def _trace_path(args: dict[str, Any]) -> Path | None:
    explicit = os.environ.get(PATH_ENV)
    if explicit:
        return Path(explicit).expanduser()

    # Do not derive a trace path from raw dispatch args. Error paths can be
    # reached before `args["home"]` has passed HomePathValidationError checks;
    # using it here would let a rejected traversal/malicious home create trace
    # directories. Without an explicit trace path, only operator-controlled
    # TRADE_TRACE_HOME is trusted for the default trace location.
    home = os.environ.get(HOME_ENV)
    if not home:
        return None
    return Path(str(home)).expanduser() / "trace" / "dispatch.jsonl"


def _chmod_0600(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _rotate(path: Path, max_bytes: int, max_files: int) -> None:
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
        oldest = path.with_name(f"{path.name}.{max_files}")
        oldest.unlink(missing_ok=True)
        for idx in range(max_files - 1, 0, -1):
            src = path.with_name(f"{path.name}.{idx}")
            if src.exists():
                dst = path.with_name(f"{path.name}.{idx + 1}")
                src.replace(dst)
                _chmod_0600(dst)
        rotated = path.with_name(f"{path.name}.1")
        path.replace(rotated)
        _chmod_0600(rotated)
    except OSError:
        return


def _safe_json_value(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def _redacted_record(record: dict[str, Any]) -> dict[str, Any]:
    # Redact the complete serialized line, then scan the final text so tests and
    # operators can rely on the same detection pass having seen persisted bytes.
    text = json.dumps(record, sort_keys=True, default=str, separators=(",", ":"))
    redacted = redact_for_log(text)
    scan_text(redacted)
    loaded = json.loads(redacted)
    return loaded if isinstance(loaded, dict) else record


def emit(
    *,
    tool: str,
    actor_id: str,
    request_id: str,
    args: dict[str, Any],
    env: SuccessEnvelope | ErrorEnvelope,
    started_ns: int,
    attempt: int | None = None,
    retry_of: str | None = None,
) -> None:
    if not is_enabled():
        return
    try:
        path = _trace_path(args)
        if path is None:
            return
        body = dump_envelope(env)
        meta = body.get("meta", {}) if isinstance(body.get("meta"), dict) else {}
        error = body.get("error", {}) if isinstance(body.get("error"), dict) else {}
        details = error.get("details", {}) if isinstance(error.get("details"), dict) else {}
        latency_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000, 3)
        record: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "latency_ms": latency_ms,
            "tool": tool,
            "actor_id": actor_id,
            "request_id": request_id,
            "dry_run": bool(meta.get("dry_run")),
            "ok": bool(body.get("ok")),
            "error_code": error.get("code"),
            "details": {},
            "meta": {
                "idempotency_source": meta.get("idempotency_source"),
                "idempotency_disabled": bool(meta.get("idempotency_disabled")),
            },
        }
        if attempt is not None:
            record["attempt"] = attempt
        if retry_of is not None:
            record["retry_of"] = retry_of
        if "reason" in details:
            record["details"]["reason"] = _safe_json_value(details["reason"])
        if "retry_after_seconds" in details:
            record["retry_after_seconds"] = _safe_json_value(details["retry_after_seconds"])

        line = json.dumps(_redacted_record(record), sort_keys=True, separators=(",", ":")) + "\n"
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        _rotate(path, _positive_int_from_env(MAX_BYTES_ENV, _DEFAULT_MAX_BYTES), _positive_int_from_env(MAX_FILES_ENV, _DEFAULT_MAX_FILES))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(line)
        finally:
            _chmod_0600(path)
    except Exception:
        return
