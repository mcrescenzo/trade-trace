"""Console Logs page — read-only operational log viewer
(trade-trace-jtec, follow-up to the Console MVP epic).

The Console reads the operational log files defined in
`docs/architecture/logging.md`: JSONL lines under
`<home>/logs/trade-trace.log` (or `$TRADE_TRACE_LOG_DIR`),
rotated by `RotatingFileHandler` to `*.1`, `*.2`, …

This module exposes a `logs_context()` page handler that:

- Tolerates missing log directory / empty / malformed lines.
- Applies the same secret-pattern redaction the logging module
  uses on write — defense in depth, since templates already
  HTML-escape strings.
- Never writes to the log file path.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trade_trace.console.security import is_loopback_address  # noqa: F401
from trade_trace.storage.paths import resolve_home

LOG_FILENAME = "trade-trace.log"
DEFAULT_TAIL_LINES = 200


def _log_dir(home: Path | None = None) -> Path:
    override = os.environ.get("TRADE_TRACE_LOG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return resolve_home(home) / "logs"


def _iter_log_paths(dir_path: Path) -> Iterable[Path]:
    """Live file plus rotated siblings, newest-first. Returns an
    empty iterator if the directory does not exist."""

    if not dir_path.exists():
        return []
    live = dir_path / LOG_FILENAME
    rotated = sorted(dir_path.glob(LOG_FILENAME + ".*"), reverse=True)
    paths: list[Path] = []
    if live.exists():
        paths.append(live)
    paths.extend(rotated)
    return paths


def _parse_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Parse JSONL lines. Malformed lines surface as
    `{"_unparsed": <raw>}` so the operator sees them in the UI
    instead of having the whole page break."""

    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.rstrip("\n")
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            out.append({"_unparsed": line})
            continue
        if not isinstance(parsed, dict):
            out.append({"_unparsed": line})
            continue
        out.append(parsed)
    return out


def _redact_record(record: dict[str, Any]) -> dict[str, Any]:
    """Defense-in-depth: re-run the secret redactor over the
    parsed record. The on-write redactor in `trade_trace.logging`
    already scrubs at emit time; this catches any pre-redactor
    files (e.g., shipped via a backup before the redactor
    landed)."""

    from trade_trace.logging import _redact

    return _redact(record)


def logs_context(
    home: Path | None = None,
    *,
    tail: int = DEFAULT_TAIL_LINES,
    level_filter: str | None = None,
) -> dict[str, Any]:
    """Build the Logs page context. Returns an empty-state dict
    when no log file exists, or when the file is present but
    empty. Filters by `level_filter` (`INFO`, `WARN`, etc.) when
    provided."""

    dir_path = _log_dir(home)
    log_paths = list(_iter_log_paths(dir_path))
    if not log_paths:
        return {
            "page_title": "Logs",
            "generated_at": _iso_now(),
            "rows": [],
            "log_dir": str(dir_path),
            "empty_state": {
                "title": "No operational log files yet.",
                "next_steps": [
                    ("Run a tool that emits via the logger",
                     "tt journal init && tt export drain"),
                    ("Or set TRADE_TRACE_LOG_DIR to a path you control",
                     "export TRADE_TRACE_LOG_DIR=/path/to/logs"),
                ],
            },
        }

    # Read the newest `tail` lines across the live file and rotated
    # siblings in order. `tail` is bounded to keep page render
    # cheap on a 5 MiB+ rotated log.
    lines: list[str] = []
    for path in log_paths:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                # Read whole file; logs.md §rotation pins each file
                # to 5 MiB by default which is fine for one render.
                lines.extend(fh.readlines())
        except OSError:
            continue
        if len(lines) >= tail:
            break

    records = _parse_lines(lines[-tail:])
    if level_filter:
        wanted = level_filter.upper()
        records = [r for r in records if r.get("level") == wanted]

    redacted = [_redact_record(r) for r in records]
    return {
        "page_title": "Logs",
        "generated_at": _iso_now(),
        "rows": redacted,
        "log_dir": str(dir_path),
        "tail": tail,
        "level_filter": level_filter,
        "empty_state": (
            {
                "title": "Log file exists but no entries match the filter.",
                "next_steps": [
                    ("Clear the filter", "Use 'All' in the level dropdown"),
                ],
            }
            if not redacted
            else None
        ),
    }


def _iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
