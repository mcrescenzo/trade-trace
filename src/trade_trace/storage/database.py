"""SQLite connection management.

Operability.md §3.2 fixes the busy_timeout to 5 seconds and §3.1 enforces
single-writer WAL semantics. §6.3 says file permissions should default to
0600 where the platform supports it.

This module is deliberately thin: opening a Database does NOT make outbound
network calls and does NOT touch any path outside `$TRADE_TRACE_HOME`. The
journal.init tool wraps this to provide the user-facing idempotent setup.
"""

from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from trade_trace._permissions import chmod_user_only_dir, chmod_user_only_file

BUSY_TIMEOUT_MS = 5000
_SAVEPOINT_COUNTER = itertools.count(1)


def load_sqlite_vec_extension(conn: sqlite3.Connection) -> None:  # pragma: no cover - legacy
    """Legacy no-op kept for callers that only report capability.

    Trade Trace's embeddings path is now local ONNX + brute-force cosine over
    the ordinary SQLite table, so opening a configured journal must not require
    sqlite-vec or any loadable extension.
    """

    _ = conn


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

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block in a single SQLite transaction. Commits on success,
        rolls back on exception.

        `open_database` keeps SQLite in autocommit mode so ordinary statements
        persist immediately outside this context manager. Start an explicit
        transaction here; otherwise rollback after an exception cannot undo
        statements that SQLite has already autocommitted.

        Nested callers use a savepoint so an inner failure rolls back only the
        inner block, and an inner success remains owned by the outer transaction.
        """

        if self.connection.in_transaction:
            savepoint = f"__trade_trace_txn_{next(_SAVEPOINT_COUNTER)}"
            self.connection.execute(f"SAVEPOINT {savepoint}")
            try:
                yield self.connection
                self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:
                self.connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            return

        self.connection.execute("BEGIN")
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise


@contextmanager
def read_snapshot(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Pin a single consistent read snapshot for a multi-query report
    composition (trade-trace-d8lu).

    Without an explicit transaction, each SELECT on a Python sqlite3
    connection acts as its own implicit read transaction. In WAL mode
    that means concurrent commits between SELECTs leak into the report
    body — two sections of the same report can disagree about how many
    decisions exist or which strategies are active.

    `BEGIN DEFERRED` starts a read transaction whose snapshot is fixed at
    the first SELECT after the BEGIN, so every subsequent SELECT in the
    block sees the same database state. The helper is a no-op when the
    connection is already inside a transaction (e.g., nested report
    composition) and always commits to release the snapshot.
    """

    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN DEFERRED")
    try:
        yield conn
    except Exception:
        # If a caller writes inside the snapshot and then raises, those
        # writes must be discarded — not silently committed. Mirrors
        # Database.transaction() (trade-trace-7wvp).
        conn.rollback()
        raise
    else:
        conn.commit()


class ReadOnlyDatabaseError(RuntimeError):
    """Raised by `open_database_readonly` when the requested DB
    cannot be opened cleanly (trade-trace-1kkv.3). Carries a
    machine-readable `reason` so read-only consumers can present a
    friendly empty-state instead of crashing."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


_MIN_REQUIRED_TABLES = ("events", "config")


def open_database_readonly(path: Path) -> Database:
    """Open `path` in OS-enforced read-only mode for read-only
    reporting data access (trade-trace-1kkv.3). Uses
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
    # `open_database` helper so long-lived CLI/MCP/reporting callers
    # can share a handle without re-opening per query.
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None, check_same_thread=False)

    # Belt-and-suspenders: pin `query_only` so any tool or test
    # inspecting pragmas can verify the intent without parsing the URI
    # flags. URI ro mode is the actual guard.
    conn.execute("PRAGMA query_only = 1")

    # Verify the baseline schema. Missing required tables means the
    # caller pointed at a wrong file or a pre-M0 database; either way
    # read-only consumers must present an empty state, not migrate.
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
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    if newly_created:
        chmod_user_only_file(path)
    # WAL/SHM siblings can persist between sessions; pin their perms
    # if they already exist when we open the DB. New ones get pinned
    # on close() (per Database.close).
    _chmod_wal_shm_siblings(path)
    # Apply pragmas. Set busy_timeout before WAL negotiation so a contended
    # second writer honors operability.md §3.2 even if the lock is observed
    # while opening/configuring the connection.
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError as exc:
        if "database is locked" not in str(exc).lower():
            raise
        # Another writer can hold the WAL write lock while this connection is
        # being opened. Existing Trade Trace databases are already in WAL mode;
        # let the actual write statement honor busy_timeout and surface the
        # documented single_writer_lock envelope instead of failing during
        # connection setup.
    # synchronous=NORMAL is a connection-scoped pragma that does not touch the
    # WAL write lock, so it must run even when the journal_mode negotiation
    # above hit a transient lock — otherwise a contended open silently leaves
    # the connection at the SQLite default (FULL), changing durability/fsync
    # behavior for the rest of its lifetime. Its own try/except keeps it
    # resilient to the same transient lock without skipping it.
    try:
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.OperationalError as exc:
        if "database is locked" not in str(exc).lower():
            raise
    conn.execute("PRAGMA foreign_keys = ON")
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


def has_sqlite_vec(conn: sqlite3.Connection) -> bool:  # pragma: no cover - legacy
    """sqlite-vec is no longer part of the default or embeddings posture."""

    _ = conn
    return False
