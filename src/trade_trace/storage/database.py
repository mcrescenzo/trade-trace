"""SQLite connection management.

Operability.md §3.2 fixes the busy_timeout to 5 seconds and §3.1 enforces
single-writer WAL semantics. §6.3 says file permissions should default to
0600 where the platform supports it.

This module is deliberately thin: opening a Database does NOT make outbound
network calls and does NOT touch any path outside `$TRADE_TRACE_HOME`. The
journal.init tool wraps this to provide the user-facing idempotent setup.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

BUSY_TIMEOUT_MS = 5000


def _set_user_only_permissions(path: Path) -> None:
    """Best-effort `chmod 0600` on platforms where it's supported. Silently
    skipped on platforms where stat permissions aren't meaningful (e.g. Windows
    NTFS without POSIX support)."""

    if os.name != "posix":
        return
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except (OSError, PermissionError):
        # The file is created with whatever permissions umask allowed; we
        # warn at the journal-init layer if the result is world-readable.
        pass


def _set_user_only_dir_permissions(path: Path) -> None:
    """Best-effort `chmod 0700` on a directory. Same skip rules as
    `_set_user_only_permissions`."""

    if os.name != "posix":
        return
    try:
        path.chmod(stat.S_IRWXU)
    except (OSError, PermissionError):
        pass


def _chmod_wal_shm_siblings(db_path_: Path) -> None:
    """Best-effort `chmod 0600` on the SQLite WAL and SHM neighbor files
    if they exist. WAL mode creates `<db>-wal` and `<db>-shm` lazily
    on the first write, so callers run this after a write/commit to
    pin the air-gap permission contract (security.md §6.3 / bead
    trade-trace-ljl9). Missing files are a no-op."""

    for suffix in ("-wal", "-shm"):
        candidate = db_path_.with_name(db_path_.name + suffix)
        if candidate.exists():
            _set_user_only_permissions(candidate)


@dataclass
class Database:
    """Wrapper around a sqlite3 connection with the project's defaults."""

    path: Path
    connection: sqlite3.Connection

    def close(self) -> None:
        # Pin permissions on any WAL/SHM siblings that came into
        # existence during this connection's lifetime before closing
        # so a permissive umask cannot leave them world-readable.
        _chmod_wal_shm_siblings(self.path)
        self.connection.close()

    def ensure_user_only_permissions(self) -> None:
        """Re-apply 0600 to the DB plus any WAL/SHM siblings.

        Callers run this after writes to tighten the perms an
        unfortunately-loose umask may have allowed. Safe to call
        repeatedly; missing siblings are no-ops.
        """

        _set_user_only_permissions(self.path)
        _chmod_wal_shm_siblings(self.path)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block in a single SQLite transaction. Commits on success,
        rolls back on exception."""

        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise


def open_database(path: Path, *, create_parent: bool = True) -> Database:
    """Open (or create) a SQLite database at `path` with the project's
    defaults: WAL mode, busy_timeout=5s, foreign_keys=ON, user-only
    permissions on POSIX.

    Makes zero outbound network calls."""

    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
        _set_user_only_dir_permissions(path.parent)

    newly_created = not path.exists()
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    if newly_created:
        _set_user_only_permissions(path)
    # WAL/SHM siblings can persist between sessions; pin their perms
    # if they already exist when we open the DB. New ones get pinned
    # on close() (per Database.close).
    _chmod_wal_shm_siblings(path)
    # Apply pragmas. WAL must be SET (returns the new mode); the others use
    # `PRAGMA name = value`.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return Database(path=path, connection=conn)


def has_fts5(conn: sqlite3.Connection) -> bool:
    """Best-effort FTS5 availability check. SQLite ships FTS5 by default in
    most modern builds; older Linux package builds may have it disabled.
    This check creates a temp FTS5 virtual table; failure means FTS5 is not
    compiled in."""

    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS __ftscheck USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS __ftscheck")
        return True
    except sqlite3.OperationalError:
        return False


def has_sqlite_vec(conn: sqlite3.Connection) -> bool:  # pragma: no cover - optional
    """Best-effort sqlite-vec detection. The package ships sqlite-vec as a
    runtime dep but the extension may not be loadable in every build context.
    Vectors are off by default in MVP; this is informational only."""

    try:
        import sqlite_vec  # type: ignore[import-not-found]

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        # Smoke-test by creating a vec0 virtual table.
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS __veccheck USING vec0(x float[4])")
        conn.execute("DROP TABLE IF EXISTS __veccheck")
        return True
    except Exception:
        return False
