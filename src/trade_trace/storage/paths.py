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


def resolve_home(explicit: str | Path | None = None) -> Path:
    """Resolve the home dir, preferring an explicit override."""

    if explicit is None:
        return default_home()
    return Path(explicit).expanduser().resolve()


def db_path(home: Path) -> Path:
    return home / DB_FILENAME
