"""Regression coverage for explicit SQLite transactions in autocommit mode."""

from __future__ import annotations

import pytest

from trade_trace.storage.database import open_database


def _create_probe_table(db):
    db.connection.execute("CREATE TABLE probe(id INTEGER PRIMARY KEY, value TEXT)")


def _probe_values(db) -> list[str]:
    return [row[0] for row in db.connection.execute("SELECT value FROM probe ORDER BY id")]


def test_transaction_rolls_back_writes_on_exception_with_open_database(tmp_path):
    db = open_database(tmp_path / "journal.db")
    try:
        _create_probe_table(db)

        with pytest.raises(RuntimeError, match="boom"):
            with db.transaction() as conn:
                conn.execute("INSERT INTO probe(value) VALUES ('leaked')")
                raise RuntimeError("boom")

        assert _probe_values(db) == []
    finally:
        db.close()


def test_transaction_commits_writes_on_success_with_open_database(tmp_path):
    db = open_database(tmp_path / "journal.db")
    try:
        _create_probe_table(db)

        with db.transaction() as conn:
            conn.execute("INSERT INTO probe(value) VALUES ('persisted')")

        assert _probe_values(db) == ["persisted"]
    finally:
        db.close()


def test_nested_transaction_exception_rolls_back_to_inner_savepoint_only(tmp_path):
    db = open_database(tmp_path / "journal.db")
    try:
        _create_probe_table(db)

        with db.transaction() as outer:
            outer.execute("INSERT INTO probe(value) VALUES ('outer-before')")
            with pytest.raises(RuntimeError, match="inner"):
                with db.transaction() as inner:
                    inner.execute("INSERT INTO probe(value) VALUES ('inner-leaked')")
                    raise RuntimeError("inner")
            outer.execute("INSERT INTO probe(value) VALUES ('outer-after')")

        assert _probe_values(db) == ["outer-before", "outer-after"]
    finally:
        db.close()


def test_nested_transaction_success_participates_in_outer_transaction(tmp_path):
    db = open_database(tmp_path / "journal.db")
    try:
        _create_probe_table(db)

        with pytest.raises(RuntimeError, match="outer"):
            with db.transaction() as outer:
                outer.execute("INSERT INTO probe(value) VALUES ('outer')")
                with db.transaction() as inner:
                    inner.execute("INSERT INTO probe(value) VALUES ('inner')")
                raise RuntimeError("outer")

        assert _probe_values(db) == []
    finally:
        db.close()
