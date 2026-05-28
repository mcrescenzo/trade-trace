"""Migration 018_pretrade_intents.

Immutable local audit records for non-executing pre-trade intent packets.
"""

from __future__ import annotations

import sqlite3


def _migration_018_pretrade_intents(conn: sqlite3.Connection) -> None:
    """Create append-only pre-trade intent packet tables."""

    conn.execute(
        """
        CREATE TABLE pretrade_intents (
            id TEXT PRIMARY KEY,
            semantic_key TEXT NOT NULL,
            material_hash TEXT NOT NULL UNIQUE,
            market_id TEXT REFERENCES markets(id),
            instrument_id TEXT REFERENCES instruments(id),
            snapshot_id TEXT REFERENCES snapshots(id),
            thesis_id TEXT REFERENCES theses(id),
            forecast_id TEXT REFERENCES forecasts(id),
            decision_id TEXT REFERENCES decisions(id),
            risk_check_receipt_id TEXT REFERENCES risk_check_receipts(id),
            strategy_id TEXT REFERENCES strategies(id),
            playbook_version_id TEXT REFERENCES playbook_versions(id),
            proposed_shape_json TEXT NOT NULL,
            risk_budget_json TEXT NOT NULL DEFAULT '{}',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            source_ids_json TEXT NOT NULL DEFAULT '[]',
            caveats_json TEXT NOT NULL DEFAULT '[]',
            approval_state TEXT NOT NULL DEFAULT 'not_requested' CHECK (approval_state IN ('not_requested','pending_external_review','approved_elsewhere','waived_elsewhere','rejected_elsewhere')),
            approval_ref_id TEXT,
            as_of TEXT NOT NULL,
            run_id TEXT,
            idempotency_key TEXT,
            provenance_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            CHECK (market_id IS NOT NULL OR instrument_id IS NOT NULL),
            UNIQUE (semantic_key)
        )
        """,
    )
    conn.execute("CREATE INDEX idx_pretrade_intents_created_at ON pretrade_intents(created_at)")
    conn.execute("CREATE INDEX idx_pretrade_intents_market ON pretrade_intents(market_id, instrument_id)")
    conn.execute(
        """
        CREATE TRIGGER trg_pretrade_intents_no_update
        BEFORE UPDATE ON pretrade_intents
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on pretrade_intents is forbidden; create a new intent packet');
        END
        """,
    )
    conn.execute(
        """
        CREATE TRIGGER trg_pretrade_intents_no_delete
        BEFORE DELETE ON pretrade_intents
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on pretrade_intents is forbidden');
        END
        """,
    )


__all__ = ["_migration_018_pretrade_intents"]
