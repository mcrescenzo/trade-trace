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
