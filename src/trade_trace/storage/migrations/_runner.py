"""Forward-only schema migrations per operability.md §4.

Each migration is an ordered callable `(connection) -> None` that bumps the
`meta.schema_version` integer by exactly one. Migrations are idempotent in
the sense that re-applying them against an already-migrated database is a
no-op (the version check short-circuits); but a partial mid-migration crash
is rolled back by SQLite WAL.

Adding a migration is a one-line append to MIGRATIONS plus the migration
function below. Removing or reordering is a breaking change requiring a
contract version bump.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from trade_trace.storage.policy import check_no_reverse_migration


class FTS5UnavailableError(RuntimeError):
    """The host SQLite build does not have FTS5 compiled in.

    Trade Trace's memory-layer recall path depends on FTS5 (the BM25
    backbone of `memory.recall`) so the migration cannot run on a
    SQLite that lacks the extension. The error includes remediation
    text the operator can paste into a search engine.

    Raised by migration 006 per bead trade-trace-qis / DEBT-013.
    """

    def __init__(self) -> None:
        super().__init__(
            "FTS5 is required for the memory layer but the host SQLite "
            "build does not include it. Install a SQLite (or Python "
            "distribution) compiled with -DSQLITE_ENABLE_FTS5 (most "
            "official CPython distributions on Linux/macOS/Windows ship "
            "FTS5; minimal Alpine/musl builds sometimes do not). See "
            "docs/architecture/persistence.md for the dependency policy."
        )


def _require_fts5(conn: sqlite3.Connection) -> None:
    """Preflight FTS5 availability. Raises `FTS5UnavailableError` with
    actionable remediation text if the host SQLite build lacks FTS5."""

    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS __qis_fts_check USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS __qis_fts_check")
    except sqlite3.OperationalError as exc:  # pragma: no cover - exercised via test
        raise FTS5UnavailableError() from exc

Migration = Callable[[sqlite3.Connection], None]



def _registry() -> tuple[
    list[Migration],
    list[tuple[int, list[str]]],
    list[tuple[int, dict[str, list[str]]]],
    list[tuple[int, list[str]]],
]:
    """Late-bind the registry to break the _runner → __init__ cycle.

    The migration registry (`MIGRATIONS`) and fingerprint constants
    (`_MIGRATION_TABLES_CREATED`, `_MIGRATION_COLUMNS_ADDED`,
    `_MIGRATION_INDEXES_CREATED`) live in
    the package `__init__.py` so the per-migration modules can be read
    as the canonical per-version source. `_runner.py` imports them
    lazily here so the import order is `__init__.py → _runner.py →
    mNNN_*.py` with no top-level cycle.
    """

    from trade_trace.storage.migrations import (
        _MIGRATION_COLUMNS_ADDED,
        _MIGRATION_INDEXES_CREATED,
        _MIGRATION_TABLES_CREATED,
        MIGRATIONS,
    )
    return (
        MIGRATIONS,
        _MIGRATION_TABLES_CREATED,
        _MIGRATION_COLUMNS_ADDED,
        _MIGRATION_INDEXES_CREATED,
    )



class SchemaMetaMismatchError(RuntimeError):
    """The DB's `meta.schema_version` disagrees with schema objects
    that actually exist on disk
    (bead trade-trace-0ib / DEBT-015; column-drift coverage added in
    trade-trace-n1mm; index-drift coverage added in trade-trace-o6qw).

    Raised before any migration runs so an opaque DDL failure ("table
    X already exists" / "duplicate column name" / "index X already
    exists") is replaced with an actionable diagnostic.
    """

    def __init__(
        self,
        current_version: int,
        unexpected_tables: list[str] | None = None,
        unexpected_columns: dict[str, list[str]] | None = None,
        unexpected_indexes: list[str] | None = None,
    ) -> None:
        self.current_version = current_version
        self.unexpected_tables = sorted(unexpected_tables or [])
        self.unexpected_columns = {
            table: sorted(cols)
            for table, cols in sorted((unexpected_columns or {}).items())
        }
        self.unexpected_indexes = sorted(unexpected_indexes or [])
        parts = [f"schema/meta mismatch: meta.schema_version={current_version}"]
        if self.unexpected_tables:
            parts.append(
                f"these table(s) already exist on disk: "
                f"{self.unexpected_tables!r}"
            )
        if self.unexpected_columns:
            parts.append(
                f"these column(s) already exist on disk: "
                f"{self.unexpected_columns!r}"
            )
        if self.unexpected_indexes:
            parts.append(
                f"these index(es) already exist on disk: "
                f"{self.unexpected_indexes!r}"
            )
        parts.append(
            "This usually means a prior migration committed without "
            "updating the meta row, or the meta row was reset by an "
            "out-of-band recovery. Restore the DB from a backup "
            "(tt journal restore --from <path>) or remove the "
            "unexpected schema elements manually before re-running "
            "tt journal init. See operability.md §4 for the migration "
            "policy."
        )
        super().__init__("; ".join(parts) + ".")


def _assert_schema_matches_meta(
    conn: sqlite3.Connection, current_version: int,
) -> None:
    """Detect a schema/meta mismatch before the migration loop starts.

    Walks `_MIGRATION_TABLES_CREATED`, `_MIGRATION_COLUMNS_ADDED`, and
    `_MIGRATION_INDEXES_CREATED`
    for migrations the meta row claims have NOT yet run and asserts
    none of those tables, columns, or indexes already exist on disk. If any do,
    raise `SchemaMetaMismatchError` with the offending names so the
    operator can recover deliberately instead of debugging an
    "table X already exists" or "duplicate column name" error mid-loop.
    Trigger drift is out of scope per
    `docs/architecture/schema-meta-diagnostics.md`.
    """

    # Use sqlite_master directly so the check works even when `meta`
    # is itself missing or stale.
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    existing_tables = {r[0] for r in rows}
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    existing_indexes = {r[0] for r in rows}

    _, tables_fp, columns_fp, indexes_fp = _registry()

    unexpected_tables: list[str] = []
    for version, tables in tables_fp:
        if version <= current_version:
            continue
        for table in tables:
            if table in existing_tables:
                unexpected_tables.append(table)

    unexpected_columns: dict[str, list[str]] = {}
    for version, fingerprint in columns_fp:
        if version <= current_version:
            continue
        for table, columns in fingerprint.items():
            if table not in existing_tables:
                continue
            present = {
                row[1]
                for row in conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }
            for column in columns:
                if column in present:
                    unexpected_columns.setdefault(table, []).append(column)

    unexpected_indexes: list[str] = []
    for version, indexes in indexes_fp:
        if version <= current_version:
            continue
        for index in indexes:
            if index in existing_indexes:
                unexpected_indexes.append(index)

    if unexpected_tables or unexpected_columns or unexpected_indexes:
        raise SchemaMetaMismatchError(
            current_version,
            unexpected_tables=unexpected_tables,
            unexpected_columns=unexpected_columns,
            unexpected_indexes=unexpected_indexes,
        )


def current_version(conn: sqlite3.Connection) -> int:
    """Return the integer `schema_version` currently recorded in `meta`,
    or 0 if no `meta` table exists yet (fresh DB)."""

    try:
        cur = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'")
    except sqlite3.OperationalError:
        return 0
    row = cur.fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def apply_pending_migrations(
    conn: sqlite3.Connection,
    *,
    target_version: int | None = None,
) -> tuple[int, int]:
    """Apply migrations from `current_version() + 1` through `target_version`
    (or the end of MIGRATIONS if not specified). Returns (from_version,
    to_version). The migration loop runs inside one SQLite transaction so a
    crash mid-loop leaves the schema_version unchanged."""

    migrations, _tables_fp, _columns_fp, _indexes_fp = _registry()
    end = len(migrations) if target_version is None else target_version
    if end > len(migrations):
        raise ValueError(
            f"target_version={target_version} exceeds available migrations "
            f"({len(migrations)})"
        )

    start = current_version(conn)
    # Forward-only check: target < current is a hard error (the policy is in
    # storage/policy.py so the rule is shared with linters and tests).
    check_no_reverse_migration(current_version=start, target_version=end)
    if start >= end:
        return start, start

    # Schema/meta consistency check (bead trade-trace-0ib): raise a
    # typed SchemaMetaMismatchError BEFORE running migrations if the
    # meta version disagrees with the schema objects on disk.
    _assert_schema_matches_meta(conn, start)

    conn.execute("BEGIN")
    try:
        for i in range(start, end):
            migrations[i](conn)
            new_version = i + 1
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(new_version),),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return start, end
