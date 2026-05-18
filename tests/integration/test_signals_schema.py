"""Signals table schema per trade-trace-och.

The table is the substrate for ux0 chunks 3 (lazy emission) and 4 (coach
output); this bead lands the schema only, no tool surface.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path
from trade_trace.storage.policy import CLOSED_ENUMS


def _db(tmp_path: Path):
    db = open_database(db_path(tmp_path / "home"))
    apply_pending_migrations(db.connection)
    return db


def test_signals_table_exists(tmp_path: Path):
    db = _db(tmp_path)
    try:
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'signals'"
        ).fetchone()
    finally:
        db.close()
    assert row is not None


def test_signals_columns_match_contract(tmp_path: Path):
    """The columns enumerated in ux0 acceptance are all present."""

    db = _db(tmp_path)
    try:
        info = db.connection.execute("PRAGMA table_info(signals)").fetchall()
    finally:
        db.close()
    cols = {row[1] for row in info}
    expected = {
        "id", "kind", "severity", "body", "meta_json", "related_refs_json",
        "created_at", "expires_at", "actor_id",
    }
    assert expected.issubset(cols)


def test_severity_check_constraint_rejects_unknown_values(tmp_path: Path):
    db = _db(tmp_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO signals(id, kind, severity, created_at, actor_id) "
                "VALUES ('sig_bad', 'sample_size_warning', 'made_up',"
                "        '2026-05-18T14:00:00Z', 'system:report.coach')"
            )
    finally:
        db.close()


@pytest.mark.parametrize("severity", ["info", "warn", "critical"])
def test_severity_check_constraint_accepts_documented_values(
    tmp_path: Path, severity: str
):
    db = _db(tmp_path)
    try:
        db.connection.execute(
            "INSERT INTO signals(id, kind, severity, created_at, actor_id) "
            "VALUES (?, 'calibration_drift', ?, '2026-05-18T14:00:00Z', 'system:report.coach')",
            (f"sig_{severity}", severity),
        )
        db.connection.commit()
    finally:
        db.close()


def test_signals_severity_closed_enum_registered():
    """The new closed enum is documented in storage/policy.py so a future
    migration that adds a value will trip the policy check."""

    assert CLOSED_ENUMS["signals.severity"] == frozenset({"info", "warn", "critical"})


def test_signals_kind_is_open_enum_no_check_constraint(tmp_path: Path):
    """`signals.kind` is an open enum (signals.kind in OPEN_ENUMS), so new
    values are non-breaking — no CHECK constraint enforces a closed set."""

    db = _db(tmp_path)
    try:
        # Any free-text kind works; the CHECK lives only on severity.
        db.connection.execute(
            "INSERT INTO signals(id, kind, severity, created_at, actor_id) "
            "VALUES ('sig_freekind', 'fully_made_up_kind_value', 'info',"
            "        '2026-05-18T14:00:00Z', 'system:report.coach')"
        )
        db.connection.commit()
    finally:
        db.close()


def test_signals_scan_index_created(tmp_path: Path):
    """The (kind, severity, created_at) index that the coach scan query
    relies on is created by the migration."""

    db = _db(tmp_path)
    try:
        idx = db.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' "
            "AND tbl_name = 'signals' AND name = 'idx_signals_scan'"
        ).fetchone()
    finally:
        db.close()
    assert idx is not None
    assert "kind" in idx[0]
    assert "severity" in idx[0]
    assert "created_at" in idx[0]
