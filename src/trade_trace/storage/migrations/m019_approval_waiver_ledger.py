"""Migration 019_approval_waiver_ledger.

Append-only local audit records for approval, waiver, and scoped autonomy
permission evidence. These rows are not live permission gates.
"""

from __future__ import annotations

import sqlite3


def _migration_019_approval_waiver_ledger(conn: sqlite3.Connection) -> None:
    """Create append-only approval/waiver/autonomy audit ledger."""

    conn.execute(
        """
        CREATE TABLE approval_waiver_records (
            id TEXT PRIMARY KEY,
            semantic_key TEXT NOT NULL UNIQUE,
            material_hash TEXT NOT NULL UNIQUE,
            record_type TEXT NOT NULL CHECK (record_type IN ('approval','denial','modification','expiry','revocation','warning_waiver','missing_data_waiver','hard_block_override_attempt','autonomy_permission')),
            decision TEXT NOT NULL CHECK (decision IN ('approved','denied','modified','expired','revoked','waived','attempted','permitted','rejected')),
            pretrade_intent_id TEXT REFERENCES pretrade_intents(id),
            risk_check_receipt_id TEXT REFERENCES risk_check_receipts(id),
            strategy_id TEXT REFERENCES strategies(id),
            instrument_id TEXT REFERENCES instruments(id),
            market_id TEXT REFERENCES markets(id),
            actor_mode TEXT NOT NULL,
            decision_actor_id TEXT NOT NULL,
            decision_at TEXT NOT NULL,
            reason TEXT,
            modifications_json TEXT NOT NULL DEFAULT '{}',
            scope_json TEXT NOT NULL DEFAULT '{}',
            limits_json TEXT NOT NULL DEFAULT '{}',
            expires_at TEXT,
            revoked_at TEXT,
            revocation_reason TEXT,
            waiver_class TEXT CHECK (waiver_class IN ('warning','missing_data','hard_block_override_attempt')),
            hard_block_policy_permitted INTEGER NOT NULL DEFAULT 0 CHECK (hard_block_policy_permitted IN (0,1)),
            violation_visible INTEGER NOT NULL DEFAULT 0 CHECK (violation_visible IN (0,1)),
            policy_version_id TEXT REFERENCES risk_policy_versions(id),
            policy_version TEXT,
            policy_evidence_json TEXT NOT NULL DEFAULT '{}',
            environment_label TEXT,
            account_label TEXT,
            external_receipt_refs_json TEXT NOT NULL DEFAULT '[]',
            caveats_json TEXT NOT NULL DEFAULT '[]',
            run_id TEXT,
            idempotency_key TEXT,
            provenance_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """,
    )
    conn.execute("CREATE INDEX idx_approval_waiver_intent ON approval_waiver_records(pretrade_intent_id)")
    conn.execute("CREATE INDEX idx_approval_waiver_risk ON approval_waiver_records(risk_check_receipt_id)")
    conn.execute("CREATE INDEX idx_approval_waiver_created_at ON approval_waiver_records(created_at)")
    conn.execute(
        """
        CREATE TRIGGER trg_approval_waiver_no_update
        BEFORE UPDATE ON approval_waiver_records
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on approval_waiver_records is forbidden; append a lifecycle record');
        END
        """,
    )
    conn.execute(
        """
        CREATE TRIGGER trg_approval_waiver_no_delete
        BEFORE DELETE ON approval_waiver_records
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on approval_waiver_records is forbidden');
        END
        """,
    )


__all__ = ["_migration_019_approval_waiver_ledger"]
