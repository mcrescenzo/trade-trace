"""Forward-only migration tests per docs/architecture/operability.md §4."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from trade_trace.storage import (
    MIGRATIONS,
    apply_pending_migrations,
    current_version,
    open_database,
)
from trade_trace.storage.paths import db_path


def _open(tmp_path: Path):
    return open_database(db_path(tmp_path / "home"))


def test_initial_version_is_zero(tmp_path: Path):
    db = _open(tmp_path)
    try:
        assert current_version(db.connection) == 0
    finally:
        db.close()


def test_apply_all_migrations(tmp_path: Path):
    db = _open(tmp_path)
    try:
        before, after = apply_pending_migrations(db.connection)
        assert before == 0
        assert after == len(MIGRATIONS)
        assert current_version(db.connection) == len(MIGRATIONS)
    finally:
        db.close()


def test_apply_is_idempotent(tmp_path: Path):
    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection)
        snapshot = current_version(db.connection)
        before, after = apply_pending_migrations(db.connection)
        assert before == after == snapshot  # no work to do
        assert current_version(db.connection) == snapshot
    finally:
        db.close()


def test_meta_table_holds_schema_version(tmp_path: Path):
    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection)
        row = db.connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        assert row is not None
        assert int(row[0]) == len(MIGRATIONS)
    finally:
        db.close()


def test_no_downgrade(tmp_path: Path):
    """target_version cannot exceed available migrations; ditto going backward
    is not supported (forward-only)."""

    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection)
        with pytest.raises(ValueError):
            apply_pending_migrations(db.connection, target_version=len(MIGRATIONS) + 99)
    finally:
        db.close()


def test_memory_layer_migration_requires_fts5(tmp_path: Path, monkeypatch):
    """Per bead trade-trace-qis / DEBT-013: when the host SQLite build
    lacks FTS5, migration 006 must raise the typed
    `FTS5UnavailableError` BEFORE creating any memory-layer tables.
    The previous behavior was an opaque `OperationalError` partway
    through after some tables had been created, leaving callers with
    no remediation hint and a partially-migrated schema."""

    import sqlite3

    from trade_trace.storage.migrations import FTS5UnavailableError

    def _fts5_unavailable(conn: sqlite3.Connection) -> None:
        # Simulate the OperationalError SQLite raises when FTS5 is not
        # compiled in while creating the FTS5 virtual table in the
        # migration preflight.
        raise FTS5UnavailableError() from sqlite3.OperationalError(
            "no such module: fts5"
        )

    db = _open(tmp_path)
    try:
        # Stop just before migration 006 so it's the next one to run.
        apply_pending_migrations(db.connection, target_version=5)
        baseline = current_version(db.connection)
        assert baseline == 5

        monkeypatch.setattr(
            "trade_trace.storage.migrations._require_fts5",
            _fts5_unavailable,
        )

        with pytest.raises(FTS5UnavailableError) as exc:
            apply_pending_migrations(db.connection)

        # The descriptive remediation hint is part of the contract.
        msg = str(exc.value)
        assert "FTS5" in msg
        assert "memory" in msg.lower()
        assert (
            "compiled" in msg.lower()
            or "rebuild" in msg.lower()
            or "build" in msg.lower()
        )

        # Schema version stays at the baseline; the memory-layer tables
        # do not exist.
        assert current_version(db.connection) == baseline
        for table in ("memory_nodes", "memory_node_fts", "memory_recall_events"):
            row = db.connection.execute(
                "SELECT name FROM sqlite_master WHERE name = ?", (table,),
            ).fetchone()
            assert row is None, f"{table!r} leaked despite FTS5 failure"
    finally:
        db.close()


def test_schema_meta_mismatch_raises_actionable_error(tmp_path: Path):
    """Per bead trade-trace-0ib / DEBT-015: when the DB has tables on
    disk that the meta.schema_version claims haven't been migrated
    yet, the migration runner raises SchemaMetaMismatchError with
    the offending table names BEFORE attempting the next migration —
    replacing the opaque "table X already exists" DDL failure with
    actionable remediation text."""

    from trade_trace.storage.migrations import SchemaMetaMismatchError

    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection, target_version=3)
        assert current_version(db.connection) == 3

        # Simulate an out-of-band recovery that reset meta but left
        # the M1 ledger tables on disk.
        db.connection.execute(
            "UPDATE meta SET value = '1' WHERE key = 'schema_version'"
        )
        assert current_version(db.connection) == 1

        with pytest.raises(SchemaMetaMismatchError) as exc:
            apply_pending_migrations(db.connection)

        msg = str(exc.value)
        assert "schema/meta mismatch" in msg
        assert "meta.schema_version=1" in msg
        # The error names at least one of the M1 ledger tables that
        # exists on disk but is claimed unrun.
        assert any(t in msg for t in ("decisions", "theses", "venues"))
        assert "table venues already exists" not in msg.lower()
        # And points at the recovery surfaces.
        assert "journal restore" in msg or "operability" in msg
    finally:
        db.close()


def test_missing_meta_with_existing_objects_raises_actionable_error(tmp_path: Path):
    """A DB with objects on disk but no usable meta.schema_version should
    fail before migration 001/002 can produce opaque DDL errors."""

    from trade_trace.storage.migrations import SchemaMetaMismatchError

    db = _open(tmp_path)
    try:
        db.connection.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        )

        with pytest.raises(SchemaMetaMismatchError) as exc:
            apply_pending_migrations(db.connection)

        msg = str(exc.value)
        assert "schema/meta mismatch" in msg
        assert "meta.schema_version=0" in msg
        assert "events" in msg
        assert "already exist" in msg
        assert "journal restore" in msg or "operability" in msg
        assert current_version(db.connection) == 0
    finally:
        db.close()


def test_require_fts5_passes_on_modern_sqlite(tmp_path: Path):
    """The positive case — most CPython distributions ship FTS5, so
    `_require_fts5` must be a no-op on a default SQLite connection."""

    from trade_trace.storage.migrations import _require_fts5

    db = _open(tmp_path)
    try:
        _require_fts5(db.connection)  # no exception
    finally:
        db.close()


def test_partial_migration_rolls_back(tmp_path: Path, monkeypatch):
    """A migration that raises mid-loop must leave schema_version unchanged."""

    def _bad_migration(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE __halfway (x TEXT)")
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(
        "trade_trace.storage.migrations.MIGRATIONS",
        MIGRATIONS + [_bad_migration],
    )

    db = _open(tmp_path)
    try:
        # First, apply only the legit migrations so we have a known starting state.
        apply_pending_migrations(db.connection, target_version=len(MIGRATIONS))
        baseline = current_version(db.connection)
        with pytest.raises(RuntimeError):
            apply_pending_migrations(db.connection)
        # The schema_version must NOT have advanced.
        assert current_version(db.connection) == baseline
        # The half-baked table must NOT survive the rollback.
        cur = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE name = '__halfway'"
        )
        assert cur.fetchone() is None
    finally:
        db.close()


def test_strategy_id_new_row_triggers_grandfather_preexisting_rows(tmp_path: Path):
    """Migration 010 validates only new inserts: orphan strategy_id rows
    that already existed after migration 009 are not retroactively rejected.
    """

    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection, target_version=9)
        db.connection.executescript(
            """
            INSERT INTO venues(id, name, kind, created_at, actor_id)
                VALUES ('v_1', 'manual', 'manual', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
                VALUES ('i_1', 'v_1', 'Test', 'prediction_market', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO decisions(id, instrument_id, type, strategy_id, created_at, actor_id)
                VALUES ('d_old', 'i_1', 'skip', 'missing_strategy', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id)
                VALUES ('t_old', 'i_1', 'yes', '...', 'missing_strategy', '2026-05-18T14:00:00Z', 'agent:default');
            """
        )

        before, after = apply_pending_migrations(db.connection)
        assert (before, after) == (9, len(MIGRATIONS))
        assert db.connection.execute(
            "SELECT strategy_id FROM decisions WHERE id = 'd_old'"
        ).fetchone()[0] == "missing_strategy"
        assert db.connection.execute(
            "SELECT strategy_id FROM theses WHERE id = 't_old'"
        ).fetchone()[0] == "missing_strategy"

        with pytest.raises(sqlite3.IntegrityError) as exc:
            db.connection.execute(
                "INSERT INTO decisions(id, instrument_id, type, strategy_id, created_at, actor_id) "
                "VALUES ('d_new', 'i_1', 'skip', 'missing_strategy', '2026-05-18T14:00:00Z', 'agent:default')"
            )
        assert "VALIDATION_ERROR" in str(exc.value)
        assert "decisions.strategy_id" in str(exc.value)
    finally:
        db.close()


def test_schema_meta_mismatch_detects_column_drift_from_migration_004(tmp_path: Path):
    """Per trade-trace-n1mm: when the DB has columns on disk that a
    not-yet-run column-only migration would add (migration 004's
    risk-units stub), the runner must surface SchemaMetaMismatchError
    with the offending columns instead of letting SQLite raise
    "duplicate column name". Migration 010 is trigger-only and is
    explicitly out of scope per
    docs/architecture/schema-meta-diagnostics.md."""

    from trade_trace.storage.migrations import SchemaMetaMismatchError

    db = _open(tmp_path)
    try:
        # Bring the DB up to migration 4 (which adds the columns), then
        # rewind meta.schema_version to 3 so the runner thinks 004 is
        # still pending. The columns are already on disk.
        apply_pending_migrations(db.connection, target_version=4)
        assert current_version(db.connection) == 4
        db.connection.execute(
            "UPDATE meta SET value = '3' WHERE key = 'schema_version'"
        )
        assert current_version(db.connection) == 3

        with pytest.raises(SchemaMetaMismatchError) as exc:
            apply_pending_migrations(db.connection)

        err = exc.value
        assert err.current_version == 3
        # The diagnostic must enumerate the migration-004 columns the
        # check found already present on disk.
        assert "theses" in err.unexpected_columns
        assert "risk_unit_label" in err.unexpected_columns["theses"]
        assert "decisions" in err.unexpected_columns
        assert "declared_risk_amount" in err.unexpected_columns["decisions"]
        # And must NOT contain a raw SQLite "duplicate column" message.
        msg = str(err)
        assert "duplicate column name" not in msg.lower()
        assert "schema/meta mismatch" in msg
    finally:
        db.close()
