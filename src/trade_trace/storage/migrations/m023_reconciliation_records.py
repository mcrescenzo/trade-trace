"""Migration 023_reconciliation_records.

Append-only reconciliation snapshots/results over local projection and imported
external facts. Rows are derived local evidence for external operators only;
Trade Trace does not fetch private account state, authenticate, sign, submit,
cancel, settle, move funds, or remediate mismatches.
"""

from __future__ import annotations

import sqlite3


def _migration_023_reconciliation_records(conn: sqlite3.Connection) -> None:
    """Create append-only reconciliation result records."""

    conn.execute(
        """
        CREATE TABLE reconciliation_records (
            id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            semantic_key TEXT NOT NULL UNIQUE,
            material_hash TEXT NOT NULL UNIQUE,
            as_of TEXT NOT NULL,
            source TEXT NOT NULL,
            source_precedence_json TEXT NOT NULL DEFAULT '[]',
            expected_state_json TEXT NOT NULL DEFAULT '{}',
            observed_imported_state_json TEXT NOT NULL DEFAULT '{}',
            diff_json TEXT NOT NULL DEFAULT '{}',
            diff_severity TEXT NOT NULL CHECK (diff_severity IN ('none','info','warning','critical')),
            mismatch_codes_json TEXT NOT NULL DEFAULT '[]',
            resolution_status TEXT NOT NULL CHECK (resolution_status IN ('unresolved','explained','accepted_caveat','superseded','not_applicable')),
            contributing_ids_json TEXT NOT NULL DEFAULT '{}',
            caveats_json TEXT NOT NULL DEFAULT '[]',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            imported_at TEXT,
            recorded_at TEXT NOT NULL,
            idempotency_key TEXT,
            actor_id TEXT NOT NULL
        )
        """,
    )
    conn.execute("CREATE INDEX idx_reconciliation_records_as_of ON reconciliation_records(as_of)")
    conn.execute("CREATE INDEX idx_reconciliation_records_severity ON reconciliation_records(diff_severity)")
    conn.execute("CREATE INDEX idx_reconciliation_records_status ON reconciliation_records(resolution_status)")
    conn.execute(
        """
        CREATE TRIGGER trg_reconciliation_records_no_update
        BEFORE UPDATE ON reconciliation_records
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on reconciliation_records is forbidden; append a new reconciliation record');
        END
        """,
    )
    conn.execute(
        """
        CREATE TRIGGER trg_reconciliation_records_no_delete
        BEFORE DELETE ON reconciliation_records
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on reconciliation_records is forbidden');
        END
        """,
    )


__all__ = ["_migration_023_reconciliation_records"]
