"""M1 schema tests per PRD §3.1 + docs/architecture/persistence.md
(trade-trace-7lo)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path


def _db(tmp_path: Path):
    db = open_database(db_path(tmp_path / "home"))
    apply_pending_migrations(db.connection)
    return db


M1_TABLES = {
    "venues",
    "instruments",
    "snapshots",
    "theses",
    "forecasts",
    "forecast_outcomes",
    "forecast_scores",
    "decisions",
    "decision_tags",
    "outcomes",
    "sources",
    "edges",
    "position_events",
    "positions",
    "events",  # M0 migration 002
    "outbox",  # M0 migration 002
    "config",  # M0 migration 002
    "meta",  # M0 migration 001
}


def test_all_m1_tables_present(tmp_path: Path):
    db = _db(tmp_path)
    try:
        cur = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = {row[0] for row in cur.fetchall()}
        missing = M1_TABLES - tables
        assert not missing, f"missing M1 tables: {missing}"
    finally:
        db.close()


def test_decision_required_field_matrix_enums(tmp_path: Path):
    """All 13 decision types from PRD §3.1 accepted by CHECK constraint."""

    db = _db(tmp_path)
    try:
        # Insert prerequisite rows.
        db.connection.execute(
            "INSERT INTO venues(id, name, kind, created_at, actor_id) VALUES (?, ?, ?, ?, ?)",
            ("v_1", "manual", "manual", "2026-05-18T14:00:00Z", "agent:default"),
        )
        db.connection.execute(
            "INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("i_1", "v_1", "Test", "prediction_market", "2026-05-18T14:00:00Z", "agent:default"),
        )
        for i, t in enumerate(
            [
                "watch",
                "skip",
                "paper_enter",
                "paper_exit",
                "actual_enter",
                "actual_exit",
                "add",
                "reduce",
                "hold",
                "invalidate_thesis",
                "update_thesis",
                "resolved",
                "review",
            ]
        ):
            db.connection.execute(
                "INSERT INTO decisions(id, instrument_id, type, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"d_{i}", "i_1", t, "2026-05-18T14:00:00Z", "agent:default"),
            )
        count = db.connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        assert count == 13
    finally:
        db.close()


def test_invalid_decision_type_rejected(tmp_path: Path):
    db = _db(tmp_path)
    try:
        db.connection.execute(
            "INSERT INTO venues(id, name, kind, created_at, actor_id) VALUES (?, ?, ?, ?, ?)",
            ("v_1", "manual", "manual", "2026-05-18T14:00:00Z", "agent:default"),
        )
        db.connection.execute(
            "INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("i_1", "v_1", "Test", "prediction_market", "2026-05-18T14:00:00Z", "agent:default"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO decisions(id, instrument_id, type, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?)",
                ("d_bad", "i_1", "not_a_real_type", "2026-05-18T14:00:00Z", "agent:default"),
            )
    finally:
        db.close()


def test_outcome_status_enum(tmp_path: Path):
    """All 6 outcome statuses from scoring.md §5 accepted."""

    db = _db(tmp_path)
    try:
        db.connection.execute(
            "INSERT INTO venues(id, name, kind, created_at, actor_id) VALUES (?, ?, ?, ?, ?)",
            ("v_1", "manual", "manual", "2026-05-18T14:00:00Z", "agent:default"),
        )
        db.connection.execute(
            "INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("i_1", "v_1", "Test", "prediction_market", "2026-05-18T14:00:00Z", "agent:default"),
        )
        statuses = [
            "resolved_final",
            "resolved_provisional",
            "ambiguous",
            "disputed",
            "void",
            "cancelled",
        ]
        for i, s in enumerate(statuses):
            db.connection.execute(
                "INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, "
                "status, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"o_{i}", "i_1", "2026-05-18T14:00:00Z", "YES", s, "2026-05-18T14:00:00Z", "agent:default"),
            )
        count = db.connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
        assert count == 6
    finally:
        db.close()


def test_forecast_outcome_unique_label_per_forecast(tmp_path: Path):
    """`forecast_outcomes` UNIQUE on (forecast_id, outcome_label)."""

    db = _db(tmp_path)
    try:
        db.connection.execute(
            "INSERT INTO venues(id, name, kind, created_at, actor_id) VALUES (?, ?, ?, ?, ?)",
            ("v_1", "manual", "manual", "2026-05-18T14:00:00Z", "agent:default"),
        )
        db.connection.execute(
            "INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("i_1", "v_1", "Test", "prediction_market", "2026-05-18T14:00:00Z", "agent:default"),
        )
        db.connection.execute(
            "INSERT INTO theses(id, instrument_id, side, body, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("t_1", "i_1", "yes", "...", "2026-05-18T14:00:00Z", "agent:default"),
        )
        db.connection.execute(
            "INSERT INTO forecasts(id, thesis_id, kind, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?)",
            ("f_1", "t_1", "binary", "2026-05-18T14:00:00Z", "agent:default"),
        )
        db.connection.execute(
            "INSERT INTO forecast_outcomes(id, forecast_id, outcome_label, probability) "
            "VALUES (?, ?, ?, ?)",
            ("fo_1", "f_1", "YES", 0.6),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO forecast_outcomes(id, forecast_id, outcome_label, probability) "
                "VALUES (?, ?, ?, ?)",
                ("fo_2", "f_1", "YES", 0.4),  # duplicate label for same forecast
            )
    finally:
        db.close()


def test_probability_check_constraint(tmp_path: Path):
    db = _db(tmp_path)
    try:
        # Set up parents.
        db.connection.executescript(
            """
            INSERT INTO venues(id, name, kind, created_at, actor_id)
                VALUES ('v_1', 'manual', 'manual', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
                VALUES ('i_1', 'v_1', 'Test', 'prediction_market', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO theses(id, instrument_id, side, body, created_at, actor_id)
                VALUES ('t_1', 'i_1', 'yes', '...', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO forecasts(id, thesis_id, kind, created_at, actor_id)
                VALUES ('f_1', 't_1', 'binary', '2026-05-18T14:00:00Z', 'agent:default');
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO forecast_outcomes(id, forecast_id, outcome_label, probability) "
                "VALUES (?, ?, ?, ?)",
                ("fo_bad", "f_1", "YES", 1.5),  # > 1.0
            )
    finally:
        db.close()


def test_scoring_state_enum(tmp_path: Path):
    """`scoring_state` is closed at {pending, scored, failed, superseded}."""

    db = _db(tmp_path)
    try:
        db.connection.executescript(
            """
            INSERT INTO venues(id, name, kind, created_at, actor_id)
                VALUES ('v_1', 'manual', 'manual', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
                VALUES ('i_1', 'v_1', 'Test', 'prediction_market', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO theses(id, instrument_id, side, body, created_at, actor_id)
                VALUES ('t_1', 'i_1', 'yes', '...', '2026-05-18T14:00:00Z', 'agent:default');
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO forecasts(id, thesis_id, kind, scoring_state, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("f_bad", "t_1", "binary", "made_up_state", "2026-05-18T14:00:00Z", "agent:default"),
            )
    finally:
        db.close()


def test_strategy_id_nullable_with_new_row_validation(tmp_path: Path):
    """Per bead trade-trace-z4q / DEBT-012: `strategy_id` stays
    nullable TEXT without a hard FK (SQLite can't add FKs via
    ALTER TABLE) but migration 010 installs BEFORE INSERT triggers
    on `decisions` and `theses` that reject new rows pointing at a
    nonexistent strategy. NULL stays legal (the canonical "no
    strategy"). Rows that predate migration 010 are grandfathered
    and not retroactively validated."""

    db = _db(tmp_path)
    try:
        db.connection.executescript(
            """
            INSERT INTO venues(id, name, kind, created_at, actor_id)
                VALUES ('v_1', 'manual', 'manual', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
                VALUES ('i_1', 'v_1', 'Test', 'prediction_market', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO strategies(id, name, slug, status, created_at, updated_at, actor_id)
                VALUES ('strat_real', 'Real', 'real', 'active',
                        '2026-05-18T14:00:00Z', '2026-05-18T14:00:00Z', 'agent:default');
            """
        )

        # NULL strategy_id stays allowed.
        db.connection.execute(
            "INSERT INTO decisions(id, instrument_id, type, strategy_id, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("d_1", "i_1", "skip", None,
             "2026-05-18T14:00:00Z", "agent:default"),
        )

        db.connection.execute(
            "INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("t_1", "i_1", "yes", "...", None,
             "2026-05-18T14:00:00Z", "agent:default"),
        )

        # Real strategy_id allowed on both tables.
        db.connection.execute(
            "INSERT INTO decisions(id, instrument_id, type, strategy_id, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("d_2", "i_1", "skip", "strat_real",
             "2026-05-18T14:00:00Z", "agent:default"),
        )
        db.connection.execute(
            "INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("t_2", "i_1", "yes", "...", "strat_real",
             "2026-05-18T14:00:00Z", "agent:default"),
        )

        # Nonexistent strategy_id rejected by the new-row trigger.
        with pytest.raises(sqlite3.IntegrityError) as exc:
            db.connection.execute(
                "INSERT INTO decisions(id, instrument_id, type, strategy_id, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("d_3", "i_1", "skip", "strat_nope",
                 "2026-05-18T14:00:00Z", "agent:default"),
            )
        assert "VALIDATION_ERROR" in str(exc.value)
        assert "decisions.strategy_id" in str(exc.value)
        assert "nonexistent strategy" in str(exc.value)

        # Same contract holds for theses.
        with pytest.raises(sqlite3.IntegrityError) as exc:
            db.connection.execute(
                "INSERT INTO theses(id, instrument_id, side, body, "
                "strategy_id, created_at, actor_id) VALUES "
                "(?, ?, ?, ?, ?, ?, ?)",
                ("t_nope", "i_1", "yes", "...", "strat_nope",
                 "2026-05-18T14:00:00Z", "agent:default"),
            )
        assert "VALIDATION_ERROR" in str(exc.value)
        assert "theses.strategy_id" in str(exc.value)
        assert "nonexistent strategy" in str(exc.value)

        count = db.connection.execute(
            "SELECT COUNT(*) FROM decisions WHERE strategy_id IS NULL "
            "OR strategy_id IS NOT NULL"
        ).fetchone()[0]
        assert count == 2
        assert db.connection.execute("SELECT COUNT(*) FROM theses").fetchone()[0] == 2
    finally:
        db.close()


def test_segmentation_columns_present(tmp_path: Path):
    """Segmentation fields per PRD §2 must exist on belief-shaped tables."""

    db = _db(tmp_path)
    try:
        for table in ("theses", "forecasts", "decisions", "outcomes"):
            cur = db.connection.execute(f"PRAGMA table_info({table})")
            cols = {row[1] for row in cur.fetchall()}
            for seg in ("agent_id", "model_id", "environment", "run_id"):
                assert seg in cols, f"{table} missing segmentation column {seg!r}"
    finally:
        db.close()


def test_bitemporal_columns_present(tmp_path: Path):
    """Bi-temporal columns per operability.md §2.3."""

    db = _db(tmp_path)
    try:
        for table in ("theses", "forecasts"):
            cur = db.connection.execute(f"PRAGMA table_info({table})")
            cols = {row[1] for row in cur.fetchall()}
            for col in ("valid_from", "valid_to", "invalidated_at", "invalidated_by"):
                assert col in cols, f"{table} missing bi-temporal column {col!r}"
    finally:
        db.close()


def test_positions_projection_is_mutable(tmp_path: Path):
    """`positions` is a projection (rebuildable); UPDATE/DELETE allowed."""

    db = _db(tmp_path)
    try:
        db.connection.executescript(
            """
            INSERT INTO venues(id, name, kind, created_at, actor_id)
                VALUES ('v_1', 'manual', 'manual', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
                VALUES ('i_1', 'v_1', 'Test', 'prediction_market', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, updated_at)
                VALUES ('p_1', 'i_1', 'paper', 'yes', 'open',
                        '2026-05-18T14:00:00Z', '2026-05-18T14:00:00Z');
            """
        )
        # UPDATE should succeed (projection table is mutable by definition).
        db.connection.execute(
            "UPDATE positions SET status = 'closed', closed_at = ? WHERE id = 'p_1'",
            ("2026-05-19T14:00:00Z",),
        )
        row = db.connection.execute(
            "SELECT status, closed_at FROM positions WHERE id = 'p_1'"
        ).fetchone()
        assert row[0] == "closed"
        # DELETE also allowed (rebuilds drop+reinsert).
        db.connection.execute("DELETE FROM positions WHERE id = 'p_1'")
        assert db.connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0
    finally:
        db.close()
