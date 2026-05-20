"""Internal POSIX permission helpers.

These helpers centralize Trade Trace's best-effort privacy boundary for files
and directories that may contain user trading data. They intentionally no-op on
non-POSIX platforms and suppress chmod failures so callers keep the historical
best-effort behavior.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable
from pathlib import Path


def chmod_user_only_file(path: Path) -> None:
    """Best-effort ``chmod 0600`` on POSIX; no-op elsewhere."""

    if os.name != "posix":
        return
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except (OSError, PermissionError, NotImplementedError):
        pass


def chmod_user_only_dir(path: Path) -> None:
    """Best-effort ``chmod 0700`` on POSIX; no-op elsewhere."""

    if os.name != "posix":
        return
    try:
        path.chmod(stat.S_IRWXU)
    except (OSError, PermissionError, NotImplementedError):
        pass


def chmod_user_only_dirs(paths: Iterable[Path]) -> None:
    """Best-effort ``chmod 0700`` for an ordered group of directories.

    This preserves the exporter's historical group best-effort behavior: a
    chmod failure suppresses the error and stops processing remaining parents.
    """

    if os.name != "posix":
        return
    try:
        for path in paths:
            path.chmod(stat.S_IRWXU)
    except (OSError, PermissionError, NotImplementedError):
        pass
