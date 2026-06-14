"""`journal.init` exercises SQLite bootstrap, migrations, and idempotency."""

from __future__ import annotations

import json
import sqlite3
import stat
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.storage import MIGRATIONS, current_version, open_database
from trade_trace.storage.paths import db_path


def _init(home: Path) -> dict:
    env = mcp_call("journal.init", {"home": str(home)}, actor_id="cli:test")
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True, json.dumps(body)
    return body


def test_init_creates_db_file(tmp_path: Path):
    home = tmp_path / "home"
    body = _init(home)
    assert body["data"]["db_exists"] if "db_exists" in body["data"] else True
    assert Path(body["data"]["db_path"]).exists()


def test_init_sets_schema_version(tmp_path: Path):
    home = tmp_path / "home"
    body = _init(home)
    head = len(MIGRATIONS)
    assert body["data"]["schema_version"] == head
    assert body["data"]["applied_migrations"] == list(range(1, head + 1))

    db = open_database(db_path(home), create_parent=False)
    try:
        assert current_version(db.connection) == head
    finally:
        db.close()


def test_init_is_idempotent(tmp_path: Path):
    home = tmp_path / "home"
    first = _init(home)
    second = _init(home)
    # Re-running succeeds, applied_migrations is empty on second pass.
    assert second["data"]["schema_version"] == first["data"]["schema_version"]
    assert second["data"]["applied_migrations"] == []
    assert second["data"]["schema_version_before"] == first["data"]["schema_version"]


def test_init_writes_user_only_permissions(tmp_path: Path):
    """On POSIX, the freshly-created DB file should be 0600."""

    home = tmp_path / "home"
    _init(home)
    path = db_path(home)
    mode = stat.S_IMODE(path.stat().st_mode)
    # Some filesystems strip user/group bits; we assert at minimum that
    # group/other read/write are not set.
    assert (mode & stat.S_IRWXG) == 0
    assert (mode & stat.S_IRWXO) == 0


def test_init_enables_wal(tmp_path: Path):
    """journal_mode must be WAL after init for the single-writer semantics
    in operability.md §3.1."""

    home = tmp_path / "home"
    _init(home)
    conn = sqlite3.connect(str(db_path(home)))
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"


def test_open_database_sets_synchronous_normal(tmp_path: Path):
    """trade-trace-1k5d: open_database must set synchronous=NORMAL (value 1)
    on the connection. synchronous is connection-scoped, so it is asserted on
    a connection obtained from open_database itself."""

    db = open_database(tmp_path / "home" / "journal.db")
    try:
        value = db.connection.execute("PRAGMA synchronous").fetchone()[0]
    finally:
        db.close()
    assert value == 1  # 1 == NORMAL


def test_open_database_still_sets_synchronous_when_wal_pragma_is_locked(tmp_path: Path, monkeypatch):
    """trade-trace-1k5d: a transient 'database is locked' raised by the
    journal_mode=WAL negotiation must NOT skip the synchronous=NORMAL pragma.
    Previously both pragmas shared one try/except, so a contended open silently
    left synchronous at the SQLite default (FULL). Simulate the locked WAL
    pragma and assert synchronous is still applied."""

    real_connect = sqlite3.connect

    class _Proxy:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn
            self.synchronous_set = False

        def execute(self, sql: str, *args, **kwargs):
            if "journal_mode = WAL" in sql:
                raise sqlite3.OperationalError("database is locked")
            if "synchronous = NORMAL" in sql:
                self.synchronous_set = True
            return self._conn.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    proxies: list[_Proxy] = []

    def _fake_connect(*args, **kwargs):
        proxy = _Proxy(real_connect(*args, **kwargs))
        proxies.append(proxy)
        return proxy

    monkeypatch.setattr(sqlite3, "connect", _fake_connect)
    db = open_database(tmp_path / "home" / "journal.db")
    try:
        # The WAL pragma was swallowed (locked) but synchronous still ran.
        assert proxies and proxies[-1].synchronous_set is True
    finally:
        db.connection._conn.close()


def test_status_reports_schema_version_after_init(tmp_path: Path):
    home = tmp_path / "home"
    _init(home)
    env = mcp_call("journal.status", {"home": str(home)})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    assert body["data"]["db_exists"] is True
    assert body["data"]["schema_version"] == len(MIGRATIONS)


def test_status_without_init_reports_zero(tmp_path: Path):
    """`journal.status` against an uninitialized home reports schema_version=0
    and db_exists=False, with no side effect on the filesystem."""

    home = tmp_path / "home"  # does NOT exist
    env = mcp_call("journal.status", {"home": str(home)})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    assert body["data"]["db_exists"] is False
    assert body["data"]["schema_version"] == 0
    # The status call must NOT create the directory or the DB file.
    assert not home.exists()


def test_init_reports_fts5_available(tmp_path: Path):
    """Modern SQLite builds should report FTS5 available."""

    home = tmp_path / "home"
    body = _init(home)
    assert "fts5_available" in body["data"]
    # We don't hard-assert True because some minimal sqlite builds lack FTS5;
    # the field's presence is the contract.


def test_schema_emits_json_schemas(tmp_path: Path):
    env = mcp_call("journal.schema", {"home": str(tmp_path / "home")})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    schemas = body["data"]["schemas"]
    assert "Decision" in schemas
    assert "MemoryNode" in schemas
    assert schemas["Decision"]["type"] == "object"
    assert "properties" in schemas["Decision"]


@pytest.mark.parametrize("tool_name", ["Decision", "Forecast", "MemoryNode"])
def test_schema_filter_by_tool(tmp_path: Path, tool_name: str):
    env = mcp_call("journal.schema", {"tool": tool_name})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["data"]["schemas"].keys() == {tool_name}
