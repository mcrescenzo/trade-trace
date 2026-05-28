"""Migration 021_account_snapshots.

Append-only sanitized imported account snapshot facts. Rows are caller-supplied
local evidence only; Trade Trace does not fetch account state, authenticate,
sign, move funds, or remediate.
"""

from __future__ import annotations

import sqlite3


def _migration_021_account_snapshots(conn: sqlite3.Connection) -> None:
    """Create append-only sanitized imported account snapshot records."""

    conn.execute(
        """
        CREATE TABLE account_snapshots (
            id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            semantic_key TEXT NOT NULL UNIQUE,
            material_hash TEXT NOT NULL UNIQUE,
            source_system TEXT NOT NULL,
            source_run_id TEXT,
            source_precedence INTEGER NOT NULL DEFAULT 100,
            confidence_label TEXT NOT NULL CHECK (confidence_label IN ('low','medium','high','unknown')),
            staleness_status TEXT NOT NULL CHECK (staleness_status IN ('fresh','stale','missing','unknown')),
            environment_label TEXT,
            account_label TEXT,
            venue_label TEXT,
            captured_at TEXT NOT NULL,
            effective_at TEXT,
            as_of TEXT NOT NULL,
            retrieved_at TEXT,
            imported_at TEXT NOT NULL,
            artifact_hash TEXT NOT NULL,
            redacted_artifact_ref TEXT,
            balances_json TEXT NOT NULL DEFAULT '[]',
            collateral_json TEXT NOT NULL DEFAULT '{}',
            open_orders_json TEXT NOT NULL DEFAULT '[]',
            positions_json TEXT NOT NULL DEFAULT '[]',
            fills_trades_json TEXT NOT NULL DEFAULT '[]',
            unsettled_claims_json TEXT NOT NULL DEFAULT '[]',
            public_allowance_facts_json TEXT NOT NULL DEFAULT '[]',
            caveats_json TEXT NOT NULL DEFAULT '[]',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            quarantine_reason TEXT,
            idempotency_key TEXT,
            actor_id TEXT NOT NULL
        )
        """,
    )
    conn.execute("CREATE INDEX idx_account_snapshots_source ON account_snapshots(source_system)")
    conn.execute("CREATE INDEX idx_account_snapshots_labels ON account_snapshots(environment_label, account_label, venue_label)")
    conn.execute("CREATE INDEX idx_account_snapshots_staleness ON account_snapshots(staleness_status)")
    conn.execute("CREATE INDEX idx_account_snapshots_as_of ON account_snapshots(as_of)")
    conn.execute(
        """
        CREATE TRIGGER trg_account_snapshots_no_update
        BEFORE UPDATE ON account_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on account_snapshots is forbidden; append a corrected snapshot');
        END
        """,
    )
    conn.execute(
        """
        CREATE TRIGGER trg_account_snapshots_no_delete
        BEFORE DELETE ON account_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on account_snapshots is forbidden');
        END
        """,
    )


__all__ = ["_migration_021_account_snapshots"]
