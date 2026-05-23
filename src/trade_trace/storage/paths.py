"""Resolve `$TRADE_TRACE_HOME` and derived paths."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DIR_NAME = ".trade-trace"
DB_FILENAME = "trade-trace.sqlite"


def default_home() -> Path:
    """Return the default home directory: `$TRADE_TRACE_HOME` if set, else
    `$XDG_DATA_HOME/trade-trace`, else `~/.trade-trace`."""

    env = os.environ.get("TRADE_TRACE_HOME")
    if env:
        return Path(env).expanduser().resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / "trade-trace"
    return Path.home() / DEFAULT_DIR_NAME


class HomePathValidationError(ValueError):
    """Raised by `resolve_home` when an explicit `--home` value contains
    `..` path components (bead trade-trace-pqex). Callers translate this
    into a typed `VALIDATION_ERROR` envelope so a path-traversal attempt
    is refused before any filesystem state is created."""

    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__(
            f"home must not contain `..` path components; got {value!r}"
        )


def resolve_home(explicit: str | Path | None = None) -> Path:
    """Resolve the home dir, preferring an explicit override.

    Rejects explicit values containing `..` path components so callers
    cannot escape the journal sandbox by passing
    `--home '../../etc/passwd'` (bead trade-trace-pqex). The env-var
    fallback in `default_home()` is operator-controlled and not
    validated here.
    """

    if explicit is None:
        return default_home()
    raw_text = str(explicit)
    parts = Path(raw_text).parts
    if any(part == ".." for part in parts):
        raise HomePathValidationError(raw_text)
    return Path(explicit).expanduser().resolve()


def db_path(home: Path) -> Path:
    return home / DB_FILENAME
