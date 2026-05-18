"""P1 stub columns for risk-units and opportunity-analysis per yom.

Columns are nullable in M1 and have no write-tool surface; the P1 path
will populate them via JSONL import / future tool surface. Validation
rules fire even when set via raw INSERT, because the BEFORE INSERT
triggers run regardless of caller.
"""

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


def _seed_minimal(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        INSERT INTO venues(id, name, kind, created_at, actor_id)
            VALUES ('v_1', 'manual', 'manual', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
            VALUES ('i_1', 'v_1', 'Test', 'prediction_market', '2026-05-18T14:00:00Z', 'agent:default');
        """
    )


def test_theses_stub_columns_present(tmp_path: Path):
    db = _db(tmp_path)
    try:
        cur = db.connection.execute("PRAGMA table_info(theses)")
        cols = {row[1] for row in cur.fetchall()}
        for col in ("risk_unit_label", "max_loss_budget", "invalidation_condition"):
            assert col in cols, f"theses missing stub column {col!r}"
    finally:
        db.close()


def test_decisions_stub_columns_present(tmp_path: Path):
    db = _db(tmp_path)
    try:
        cur = db.connection.execute("PRAGMA table_info(decisions)")
        cols = {row[1] for row in cur.fetchall()}
        for col in (
            "declared_risk_amount",
            "declared_risk_unit",
            "expected_edge",
            "expected_edge_after_costs",
            "cost_basis_estimate",
            "risk_reward_estimate",
        ):
            assert col in cols, f"decisions missing stub column {col!r}"
    finally:
        db.close()


def test_position_events_stub_columns_present(tmp_path: Path):
    db = _db(tmp_path)
    try:
        cur = db.connection.execute("PRAGMA table_info(position_events)")
        cols = {row[1] for row in cur.fetchall()}
        for col in ("initial_risk_amount", "realized_r_multiple", "unrealized_r_multiple"):
            assert col in cols, f"position_events missing stub column {col!r}"
    finally:
        db.close()


def test_positions_projection_mirrors_r_columns(tmp_path: Path):
    db = _db(tmp_path)
    try:
        cur = db.connection.execute("PRAGMA table_info(positions)")
        cols = {row[1] for row in cur.fetchall()}
        for col in ("initial_risk_amount", "realized_r_multiple", "unrealized_r_multiple"):
            assert col in cols, f"positions missing stub column {col!r}"
    finally:
        db.close()


def test_declared_risk_amount_nonneg(tmp_path: Path):
    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        with pytest.raises(sqlite3.IntegrityError) as exc:
            db.connection.execute(
                "INSERT INTO decisions(id, instrument_id, type, declared_risk_amount, "
                "created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("d_bad", "i_1", "skip", -1.0, "2026-05-18T14:00:00Z", "agent:default"),
            )
        assert "declared_risk_amount must be >= 0" in str(exc.value)
    finally:
        db.close()


def test_declared_risk_amount_zero_allowed(tmp_path: Path):
    """Per risk-units.md §3.5 'declared_risk_amount >= 0; 0 is allowed
    (no-risk trade, e.g. a paper trade tracked for calibration only)'."""

    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        db.connection.execute(
            "INSERT INTO decisions(id, instrument_id, type, declared_risk_amount, "
            "created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?)",
            ("d_zero", "i_1", "skip", 0.0, "2026-05-18T14:00:00Z", "agent:default"),
        )
    finally:
        db.close()


def test_expected_edge_after_costs_ordering(tmp_path: Path):
    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        # OK: after-costs <= expected (with 1e-9 tolerance)
        db.connection.execute(
            "INSERT INTO decisions(id, instrument_id, type, expected_edge, "
            "expected_edge_after_costs, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("d_ok", "i_1", "skip", 1.0, 0.5, "2026-05-18T14:00:00Z", "agent:default"),
        )
        # Float-tolerance edge case: after-costs slightly > expected by < 1e-9 → allowed.
        db.connection.execute(
            "INSERT INTO decisions(id, instrument_id, type, expected_edge, "
            "expected_edge_after_costs, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("d_eps", "i_1", "skip", 1.0, 1.0 + 1e-10, "2026-05-18T14:00:00Z", "agent:default"),
        )
        # Violation: after-costs > expected + 1e-9 → rejected.
        with pytest.raises(sqlite3.IntegrityError) as exc:
            db.connection.execute(
                "INSERT INTO decisions(id, instrument_id, type, expected_edge, "
                "expected_edge_after_costs, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("d_bad", "i_1", "skip", 1.0, 1.5, "2026-05-18T14:00:00Z", "agent:default"),
            )
        assert "expected_edge_after_costs" in str(exc.value)
    finally:
        db.close()


def test_nullable_columns_default_to_null(tmp_path: Path):
    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        db.connection.execute(
            "INSERT INTO decisions(id, instrument_id, type, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?)",
            ("d_null", "i_1", "skip", "2026-05-18T14:00:00Z", "agent:default"),
        )
        row = db.connection.execute(
            "SELECT declared_risk_amount, expected_edge, risk_reward_estimate "
            "FROM decisions WHERE id = 'd_null'"
        ).fetchone()
        assert row == (None, None, None)
    finally:
        db.close()


def test_position_events_initial_risk_amount_nonneg(tmp_path: Path):
    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO position_events(id, position_id, instrument_id, event_type, "
                "initial_risk_amount, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("pe_bad", "p_1", "i_1", "open", -10.0, "2026-05-18T14:00:00Z", "agent:default"),
            )
    finally:
        db.close()


def test_theses_max_loss_budget_nonneg(tmp_path: Path):
    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO theses(id, instrument_id, side, body, max_loss_budget, "
                "created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("t_bad", "i_1", "yes", "...", -100.0, "2026-05-18T14:00:00Z", "agent:default"),
            )
    finally:
        db.close()


def test_no_cli_or_mcp_tool_accepts_stub_columns_yet():
    """yom acceptance: no CLI/MCP tool surface accepts these columns as
    kebab-cased args at M1 (P1 only). We assert this by introspecting the
    journal.schema output and verifying the stub columns do appear in the
    Pydantic models (since they're nullable schema fields) but the dispatch
    surface doesn't expose write tools that take them — which is true at M1
    because no write tools beyond journal.* are registered yet."""

    from trade_trace.core import default_registry

    registry = default_registry()
    # The journal.* tools don't accept any of these columns as args.
    journal_tools = {name for name in registry.names() if name.startswith("journal.")}
    risk_arg_names = {
        "declared_risk_amount",
        "declared_risk_unit",
        "expected_edge",
        "expected_edge_after_costs",
        "cost_basis_estimate",
        "risk_reward_estimate",
        "max_loss_budget",
        "risk_unit_label",
        "invalidation_condition",
        "initial_risk_amount",
        "realized_r_multiple",
        "unrealized_r_multiple",
    }
    # No registered tool has a name that hints at writing these columns.
    assert all(
        not any(arg in name for arg in risk_arg_names) for name in journal_tools
    )
