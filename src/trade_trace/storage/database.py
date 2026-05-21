"""SQLite connection management.

Operability.md §3.2 fixes the busy_timeout to 5 seconds and §3.1 enforces
single-writer WAL semantics. §6.3 says file permissions should default to
0600 where the platform supports it.

This module is deliberately thin: opening a Database does NOT make outbound
network calls and does NOT touch any path outside `$TRADE_TRACE_HOME`. The
journal.init tool wraps this to provide the user-facing idempotent setup.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from trade_trace._permissions import chmod_user_only_dir, chmod_user_only_file

BUSY_TIMEOUT_MS = 5000


def _configured_embeddings_provider(conn: sqlite3.Connection) -> str:
    """Return persisted embeddings.provider, defaulting to air-gapped none."""

    try:
        row = conn.execute(
            "SELECT value FROM config WHERE key = 'embeddings.provider'"
        ).fetchone()
    except sqlite3.OperationalError:
        return "none"
    if row is None or row[0] in (None, ""):
        return "none"
    return str(row[0])


def load_sqlite_vec_extension(conn: sqlite3.Connection) -> None:  # pragma: no cover - optional
    """Load sqlite-vec lazily so base installs do not require the extra."""

    import sqlite_vec  # type: ignore[import-not-found]

    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


def _chmod_wal_shm_siblings(db_path_: Path) -> None:
    """Best-effort `chmod 0600` on the SQLite WAL and SHM neighbor files
    if they exist. WAL mode creates `<db>-wal` and `<db>-shm` lazily
    on the first write, so callers run this after a write/commit to
    pin the air-gap permission contract (security.md §6.3 / bead
    trade-trace-ljl9). Missing files are a no-op."""

    for suffix in ("-wal", "-shm"):
        candidate = db_path_.with_name(db_path_.name + suffix)
        if candidate.exists():
            chmod_user_only_file(candidate)


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

        chmod_user_only_file(self.path)
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


class ReadOnlyDatabaseError(RuntimeError):
    """Raised by `open_database_readonly` when the requested DB
    cannot be opened cleanly (trade-trace-1kkv.3). Carries a
    machine-readable `reason` so the Console can render a
    friendly empty-state instead of crashing."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


_MIN_REQUIRED_TABLES = ("events", "config")


def open_database_readonly(path: Path) -> Database:
    """Open `path` in OS-enforced read-only mode for the Console
    data-access layer (trade-trace-1kkv.3). Uses
    `sqlite3.connect("file:<path>?mode=ro", uri=True)` so attempted
    writes raise `sqlite3.OperationalError` at the SQLite layer —
    not via call-site discipline.

    Never runs migrations. A DB that does not carry the M0 schema
    (`events` + `config` tables) is reported as
    `ReadOnlyDatabaseError(reason='unsupported_schema')` instead of
    being silently upgraded.

    Reasons surfaced via `ReadOnlyDatabaseError.reason`:

    - `missing`: file does not exist at `path`.
    - `unsupported_schema`: file exists but does not carry the
      M0 baseline tables.
    """

    path = Path(path)
    if not path.exists():
        raise ReadOnlyDatabaseError(
            f"journal database not found at {path}",
            reason="missing",
        )

    # `mode=ro` plus the URI flag is the SQLite-enforced read-only
    # contract — the OS file descriptor opens read-only and the
    # SQLite layer rejects writes with "attempt to write a readonly
    # database". `check_same_thread=False` matches the writable
    # `open_database` helper so a FastAPI worker pool can share a
    # handle without re-opening per request.
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None, check_same_thread=False)

    # Belt-and-suspenders: pin `query_only` so any tool inspecting
    # pragmas (Console pool-factory tests; oncall greps) can verify
    # the intent without parsing the URI flags. URI ro mode is the
    # actual guard.
    conn.execute("PRAGMA query_only = 1")

    # Verify the baseline schema. Missing required tables means the
    # caller pointed at a wrong file or a pre-M0 database; either
    # way the Console must render an empty state, not migrate.
    try:
        present = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name IN (?, ?)",
                _MIN_REQUIRED_TABLES,
            )
        }
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise ReadOnlyDatabaseError(
            f"journal database at {path} is not a SQLite file: {exc}",
            reason="unsupported_schema",
        ) from exc
    missing = set(_MIN_REQUIRED_TABLES) - present
    if missing:
        conn.close()
        raise ReadOnlyDatabaseError(
            f"journal database at {path} is missing required tables: "
            f"{sorted(missing)}",
            reason="unsupported_schema",
        )
    return Database(path=path, connection=conn)


def open_database(path: Path, *, create_parent: bool = True) -> Database:
    """Open (or create) a SQLite database at `path` with the project's
    defaults: WAL mode, busy_timeout=5s, foreign_keys=ON, user-only
    permissions on POSIX.

    Makes zero outbound network calls."""

    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
        chmod_user_only_dir(path.parent)

    newly_created = not path.exists()
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    if newly_created:
        chmod_user_only_file(path)
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
    if _configured_embeddings_provider(conn) != "none":
        load_sqlite_vec_extension(conn)
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
        load_sqlite_vec_extension(conn)
        # Smoke-test by creating a vec0 virtual table.
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS __veccheck USING vec0(x float[4])")
        conn.execute("DROP TABLE IF EXISTS __veccheck")
        return True
    except Exception:
        return False
