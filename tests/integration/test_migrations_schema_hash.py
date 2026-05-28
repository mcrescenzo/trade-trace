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
    "bdde85b9de1829bcc49c836c1a961078bbb348c5bb824070b1c199a65ca7cb85"
)
EXPECTED_INFO_HASH = (
    "2ef53ef5ccaf2e36cb16df64e9daf642df1412c0cfba0f8da1768f3a01484f39"
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


def test_m025_migrates_existing_forecast_score_outcome_fk(tmp_path: Path):
    db = open_database(db_path(tmp_path / "home_m025_fk"))
    try:
        apply_pending_migrations(db.connection, target_version=24)
        conn = db.connection
        now = "2020-01-01T00:00:00Z"
        conn.execute(
            "INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?)",
            ("polymarket", "Polymarket", "prediction_market", "{}", now, "agent:test"),
        )
        conn.execute(
            """
            INSERT INTO instruments(
                id, venue_id, external_id, title, asset_class,
                metadata_json, created_at, actor_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ins_m025", "polymarket", "pm-m025", "M025 market", "prediction_market", "{}", now, "agent:test"),
        )
        conn.execute(
            """
            INSERT INTO theses(id, instrument_id, side, body, metadata_json, created_at, actor_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("th_m025", "ins_m025", "yes", "body", "{}", now, "agent:test"),
        )
        conn.execute(
            """
            INSERT INTO forecasts(id, thesis_id, kind, resolution_at, yes_label, metadata_json, created_at, actor_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("fc_m025", "th_m025", "binary", now, "yes", "{}", now, "agent:test"),
        )
        conn.execute(
            """
            INSERT INTO outcomes(
                id, instrument_id, resolved_at, outcome_label, status,
                metadata_json, created_at, actor_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("out_m025", "ins_m025", now, "yes", "resolved_final", "{}", now, "agent:test"),
        )
        conn.execute(
            """
            INSERT INTO forecast_scores(
                id, forecast_id, outcome_id, metric, score, scored_at, actor_id, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("fs_m025", "fc_m025", "out_m025", "brier", 0.0, now, "agent:test", "{}"),
        )
        conn.commit()

        apply_pending_migrations(conn)

        assert conn.execute("SELECT outcome_id FROM forecast_scores WHERE id = 'fs_m025'").fetchone()[0] == "out_m025"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()
