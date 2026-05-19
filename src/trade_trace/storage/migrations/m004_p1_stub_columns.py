"""Migration 004_p1_stub_columns (extracted from storage/migrations.py per trade-trace-58ic). Schema-equivalence is gated by `tests/integration/test_migrations_schema_hash.py`."""

from __future__ import annotations

import sqlite3


def _migration_004_p1_stub_columns(conn: sqlite3.Connection) -> None:
    """P1 risk-units + opportunity-analysis stub columns per
    docs/architecture/risk-units.md §3 and opportunity-analysis.md.

    These columns are nullable in M1 and have no write-tool surface; they
    let the P1 import path and the P1 risk/opportunity reports populate
    rows without a breaking migration later. Validation rules (negative
    risk amounts rejected, expected_edge_after_costs <= expected_edge)
    are enforced via CHECK constraints AND a BEFORE INSERT trigger
    because SQLite's ALTER TABLE ADD COLUMN cannot install CHECK
    constraints on existing tables.
    """

    # theses.risk_unit_label / max_loss_budget / invalidation_condition
    conn.execute("ALTER TABLE theses ADD COLUMN risk_unit_label TEXT")
    conn.execute("ALTER TABLE theses ADD COLUMN max_loss_budget REAL")
    conn.execute("ALTER TABLE theses ADD COLUMN invalidation_condition TEXT")

    # decisions: 6 P1 R-multiple/opportunity columns
    conn.execute("ALTER TABLE decisions ADD COLUMN declared_risk_amount REAL")
    conn.execute("ALTER TABLE decisions ADD COLUMN declared_risk_unit TEXT")
    conn.execute("ALTER TABLE decisions ADD COLUMN expected_edge REAL")
    conn.execute("ALTER TABLE decisions ADD COLUMN expected_edge_after_costs REAL")
    conn.execute("ALTER TABLE decisions ADD COLUMN cost_basis_estimate REAL")
    conn.execute("ALTER TABLE decisions ADD COLUMN risk_reward_estimate REAL")

    # position_events: 3 risk-multiple columns
    conn.execute("ALTER TABLE position_events ADD COLUMN initial_risk_amount REAL")
    conn.execute("ALTER TABLE position_events ADD COLUMN realized_r_multiple REAL")
    conn.execute("ALTER TABLE position_events ADD COLUMN unrealized_r_multiple REAL")

    # positions projection: mirror the position_events R columns
    conn.execute("ALTER TABLE positions ADD COLUMN initial_risk_amount REAL")
    conn.execute("ALTER TABLE positions ADD COLUMN realized_r_multiple REAL")
    conn.execute("ALTER TABLE positions ADD COLUMN unrealized_r_multiple REAL")

    # Validation triggers (CHECK can't be added via ALTER TABLE in SQLite;
    # BEFORE INSERT trigger is the equivalent enforcement layer).
    conn.execute(
        """
        CREATE TRIGGER trg_theses_max_loss_budget_nonneg
        BEFORE INSERT ON theses
        WHEN NEW.max_loss_budget IS NOT NULL AND NEW.max_loss_budget < 0
        BEGIN
            SELECT RAISE(ABORT,
                'VALIDATION_ERROR: theses.max_loss_budget must be >= 0 (risk-units.md §3.5)');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_decisions_declared_risk_amount_nonneg
        BEFORE INSERT ON decisions
        WHEN NEW.declared_risk_amount IS NOT NULL AND NEW.declared_risk_amount < 0
        BEGIN
            SELECT RAISE(ABORT,
                'VALIDATION_ERROR: decisions.declared_risk_amount must be >= 0 (risk-units.md §3.5)');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_decisions_expected_edge_after_costs_ordering
        BEFORE INSERT ON decisions
        WHEN NEW.expected_edge IS NOT NULL
             AND NEW.expected_edge_after_costs IS NOT NULL
             AND NEW.expected_edge_after_costs > NEW.expected_edge + 0.000000001
        BEGIN
            SELECT RAISE(ABORT,
                'VALIDATION_ERROR: decisions.expected_edge_after_costs must be <= expected_edge + 1e-9 (risk-units.md §3.5)');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_position_events_initial_risk_amount_nonneg
        BEFORE INSERT ON position_events
        WHEN NEW.initial_risk_amount IS NOT NULL AND NEW.initial_risk_amount < 0
        BEGIN
            SELECT RAISE(ABORT,
                'VALIDATION_ERROR: position_events.initial_risk_amount must be >= 0 (risk-units.md §3.5)');
        END
        """
    )
