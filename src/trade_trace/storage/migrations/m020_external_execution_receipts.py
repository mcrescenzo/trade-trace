"""Migration 020_external_execution_receipts.

Append-only imported external execution-event receipt facts. These rows are
sanitized claims supplied by external tooling; Trade Trace does not fetch,
sign, submit, cancel, settle, or remediate external activity.
"""

from __future__ import annotations

import sqlite3


def _migration_020_external_execution_receipts(conn: sqlite3.Connection) -> None:
    """Create append-only sanitized imported external receipt records."""

    conn.execute(
        """
        CREATE TABLE external_execution_receipts (
            id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            semantic_key TEXT NOT NULL UNIQUE,
            material_hash TEXT NOT NULL UNIQUE,
            lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('submitted','accepted','rejected','partial_fill','filled','cancel_requested','canceled','expired','failed','corrected','mismatch','orphan')),
            external_event_type TEXT NOT NULL CHECK (external_event_type IN ('order','fill','cancel','error','correction','status')),
            pretrade_intent_id TEXT REFERENCES pretrade_intents(id),
            approval_ref_id TEXT REFERENCES approval_waiver_records(id),
            market_id TEXT REFERENCES markets(id),
            instrument_id TEXT REFERENCES instruments(id),
            external_order_ref TEXT,
            external_fill_ref TEXT,
            external_event_ref TEXT,
            source_system TEXT NOT NULL,
            source_run_id TEXT,
            retrieved_at TEXT,
            as_of TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            artifact_hash TEXT NOT NULL,
            redacted_artifact_ref TEXT,
            sanitized_facts_json TEXT NOT NULL DEFAULT '{}',
            caveats_json TEXT NOT NULL DEFAULT '[]',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            quarantine_reason TEXT,
            idempotency_key TEXT,
            actor_id TEXT NOT NULL
        )
        """,
    )
    conn.execute("CREATE INDEX idx_external_receipts_intent ON external_execution_receipts(pretrade_intent_id)")
    conn.execute("CREATE INDEX idx_external_receipts_state ON external_execution_receipts(lifecycle_state)")
    conn.execute("CREATE INDEX idx_external_receipts_imported_at ON external_execution_receipts(imported_at)")
    conn.execute("CREATE INDEX idx_external_receipts_order_ref ON external_execution_receipts(external_order_ref)")
    conn.execute(
        """
        CREATE TRIGGER trg_external_receipts_no_update
        BEFORE UPDATE ON external_execution_receipts
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on external_execution_receipts is forbidden; append a corrected receipt');
        END
        """,
    )
    conn.execute(
        """
        CREATE TRIGGER trg_external_receipts_no_delete
        BEFORE DELETE ON external_execution_receipts
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on external_execution_receipts is forbidden');
        END
        """,
    )


__all__ = ["_migration_020_external_execution_receipts"]
