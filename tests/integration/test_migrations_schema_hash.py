"""Schema-equivalence harness for `storage/migrations.py` per
trade-trace-y5pj (filed as the gating regression for trade-trace-58ic
— the migration-package split).

The harness captures two SHA-256 fingerprints after applying every
migration against a fresh DB:

- `ddl_hash`: canonical JSON of every `sqlite_master` row (tables,
  indexes, triggers) by `(name, type)`, with whitespace collapsed in
  each SQL string so cosmetic re-flows of an unchanged statement
  don't trip the hash.
- `info_hash`: canonical JSON of `PRAGMA table_info(<table>)` for
  every table in the DB.

The hashes below were captured against the current `migrations.py`
on 2026-05-19. Any intentional schema change (a new migration or a
column tweak) must update both literals. An *accidental* drift —
e.g., during a refactor that splits the module into per-migration
files — must keep them unchanged.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path

EXPECTED_DDL_HASH = (
    "422146ea9b104fc5b211da40b8a449b3cd04d192d3c54ec76adffb3aa6775d57"
)
EXPECTED_INFO_HASH = (
    "2282472f27460bceb135a0769e5ee256b43b59f9784ee10ff3dff138deec580d"
)


@pytest.fixture
def fresh_db(tmp_path: Path):
    db = open_database(db_path(tmp_path / "home"))
    try:
        apply_pending_migrations(db.connection)
        yield db
    finally:
        db.close()


def _ddl_snapshot(conn) -> str:
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' "
        "ORDER BY name ASC, type ASC"
    ).fetchall()
    ddl = [
        {"type": r[0], "name": r[1], "sql": " ".join((r[2] or "").split())}
        for r in rows
    ]
    return json.dumps(ddl, sort_keys=True)


def _info_snapshot(conn) -> str:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name ASC"
    ).fetchall()
    info = {}
    for (name,) in rows:
        info[name] = [
            list(col)
            for col in conn.execute(f"PRAGMA table_info({name})").fetchall()
        ]
    return json.dumps(info, sort_keys=True)


def test_migration_ddl_hash_is_stable(fresh_db):
    """Hash of every `sqlite_master` row after a full migration walk
    must match the pinned constant. Catches accidental DDL drift even
    when other tests pass."""

    actual = hashlib.sha256(_ddl_snapshot(fresh_db.connection).encode()).hexdigest()
    assert actual == EXPECTED_DDL_HASH, (
        "DDL hash drifted; intentional schema changes must update "
        "EXPECTED_DDL_HASH in this file. "
        f"got={actual!r} expected={EXPECTED_DDL_HASH!r}"
    )


def test_migration_table_info_hash_is_stable(fresh_db):
    """Hash of `PRAGMA table_info(...)` for every table must match the
    pinned constant. Catches column-order/type/nullability drift even
    when the DDL hash happens to be the same."""

    actual = hashlib.sha256(_info_snapshot(fresh_db.connection).encode()).hexdigest()
    assert actual == EXPECTED_INFO_HASH, (
        "Table-info hash drifted; intentional schema changes must "
        "update EXPECTED_INFO_HASH in this file. "
        f"got={actual!r} expected={EXPECTED_INFO_HASH!r}"
    )
