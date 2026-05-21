"""Read-only SQLite access layer for reporting consumers.

These tests pin the storage contract for non-mutating report/read-model paths:

- `open_database_readonly(path)` opens with the URI read-only flag.
- The handle rejects INSERT / UPDATE / DELETE / DDL at the SQLite
  layer (not via call-site discipline).
- Reads do not mutate the on-disk DB file.
- Missing / empty / unsupported schema produce graceful errors,
  not crashes.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _seeded_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok
    # A handful of writes so the DB has content the read paths can hit.
    mcp_call("memory.retain", {"home": str(home), "node_type": "observation", "body": "rd-probe", "idempotency_key": "rd-1"}, actor_id="agent:default")
    mcp_call("strategy.create", {"home": str(home), "name": "rd-strat", "slug": "rd-strat", "description": "d", "idempotency_key": "rd-2"}, actor_id="agent:default")
    return home


def test_open_database_readonly_returns_usable_connection(tmp_path: Path):
    from trade_trace.storage.database import open_database_readonly
    from trade_trace.storage.paths import db_path

    home = _seeded_home(tmp_path)
    db = open_database_readonly(db_path(home))
    try:
        rows = db.connection.execute("SELECT name FROM strategies").fetchall()
    finally:
        db.close()
    assert any(r[0] == "rd-strat" for r in rows), rows


def test_readonly_handle_rejects_writes_at_sqlite_layer(tmp_path: Path):
    from trade_trace.storage.database import open_database_readonly
    from trade_trace.storage.paths import db_path

    home = _seeded_home(tmp_path)
    db = open_database_readonly(db_path(home))
    try:
        # Use a minimal-column INSERT that would otherwise succeed on
        # a writable handle — `config(key, value, updated_at)` is
        # NOT NULL on all three but doesn't require auto-id.
        for statement in (
            "INSERT INTO config(key, value, updated_at) VALUES('rd-evil','x','2026-05-19T00:00:00Z')",
            "UPDATE config SET value='evil'",
            "DELETE FROM config",
            "CREATE TABLE evil(x INT)",
            "DROP TABLE config",
        ):
            with pytest.raises(sqlite3.OperationalError) as excinfo:
                db.connection.execute(statement)
            assert "readonly" in str(excinfo.value).lower(), str(excinfo.value)
    finally:
        db.close()


def test_readonly_query_does_not_mutate_db_file(tmp_path: Path):
    from trade_trace.storage.database import open_database_readonly
    from trade_trace.storage.paths import db_path

    home = _seeded_home(tmp_path)
    path = db_path(home)
    before = _sha256(path)

    db = open_database_readonly(path)
    try:
        db.connection.execute("SELECT * FROM events").fetchall()
        db.connection.execute("SELECT * FROM strategies").fetchall()
        db.connection.execute("SELECT * FROM memory_nodes").fetchall()
    finally:
        db.close()
    after = _sha256(path)
    assert before == after, "read-only handle modified the DB file"


def test_readonly_uri_escapes_reserved_characters_in_db_path(tmp_path: Path):
    from trade_trace.storage.database import open_database_readonly
    from trade_trace.storage.paths import db_path

    home = _seeded_home(tmp_path)
    requested = tmp_path / "journal ? # space & = %.sqlite"

    source = sqlite3.connect(str(db_path(home)))
    try:
        destination = sqlite3.connect(str(requested))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    wrong_truncated_sibling = requested.with_name(requested.name.split("?", 1)[0])

    db = open_database_readonly(requested)
    try:
        row = db.connection.execute("PRAGMA database_list").fetchone()
    finally:
        db.close()

    assert row is not None
    assert Path(row[2]).resolve() == requested.resolve()
    assert not wrong_truncated_sibling.exists()


def test_readonly_handle_pragma_query_only_is_on(tmp_path: Path):
    """Belt-and-suspenders: the URI flag is the strict guard but
    `query_only=1` makes the intent obvious to any tool that
    inspects pragmas."""

    from trade_trace.storage.database import open_database_readonly
    from trade_trace.storage.paths import db_path

    home = _seeded_home(tmp_path)
    db = open_database_readonly(db_path(home))
    try:
        result = db.connection.execute("PRAGMA query_only").fetchone()
    finally:
        db.close()
    assert result[0] == 1, result


def test_readonly_missing_db_raises_typed_error(tmp_path: Path):
    from trade_trace.storage.database import (
        ReadOnlyDatabaseError,
        open_database_readonly,
    )

    missing = tmp_path / "does-not-exist.sqlite"
    with pytest.raises(ReadOnlyDatabaseError) as excinfo:
        open_database_readonly(missing)
    assert excinfo.value.reason == "missing", excinfo.value.reason
    assert str(missing) in str(excinfo.value)


def test_readonly_empty_db_treated_as_unsupported_schema(tmp_path: Path):
    """A file that exists but has no `events` table is reported as
    `unsupported_schema`, not a crash."""

    from trade_trace.storage.database import (
        ReadOnlyDatabaseError,
        open_database_readonly,
    )

    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(str(empty)).close()  # zero-byte SQLite file
    with pytest.raises(ReadOnlyDatabaseError) as excinfo:
        open_database_readonly(empty)
    assert excinfo.value.reason == "unsupported_schema", excinfo.value.reason


def test_readonly_does_not_run_migrations(tmp_path: Path):
    """The read-only path must never invoke the migration runner.
    A non-migrated DB raises `unsupported_schema` instead of being
    silently upgraded."""

    from trade_trace.storage.database import (
        ReadOnlyDatabaseError,
        open_database_readonly,
    )

    legacy = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(str(legacy))
    try:
        conn.execute("CREATE TABLE not_events(id INT)")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(ReadOnlyDatabaseError) as excinfo:
        open_database_readonly(legacy)
    assert excinfo.value.reason == "unsupported_schema"
