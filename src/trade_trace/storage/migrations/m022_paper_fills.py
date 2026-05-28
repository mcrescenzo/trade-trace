"""Migration 022_paper_fills.

Append-only first-class paper fill records. These rows are local paper evidence
only and are never imported/live account truth or execution instructions.
"""

from __future__ import annotations

import sqlite3


def _migration_022_paper_fills(conn: sqlite3.Connection) -> None:
    """Create append-only paper fill records."""

    conn.execute(
        """
        CREATE TABLE paper_fill_records (
            id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            semantic_key TEXT NOT NULL UNIQUE,
            material_hash TEXT NOT NULL UNIQUE,
            environment_label TEXT NOT NULL CHECK (environment_label = 'paper'),
            account_label TEXT NOT NULL,
            market_id TEXT,
            instrument_id TEXT,
            pretrade_intent_id TEXT,
            side TEXT NOT NULL CHECK (side IN ('buy','sell')),
            outcome_side TEXT CHECK (outcome_side IN ('yes','no')),
            requested_quantity REAL NOT NULL CHECK (requested_quantity > 0),
            filled_quantity REAL NOT NULL CHECK (filled_quantity >= 0),
            remaining_quantity REAL NOT NULL CHECK (remaining_quantity >= 0),
            limit_price REAL NOT NULL CHECK (limit_price >= 0),
            average_fill_price REAL,
            fee_amount REAL NOT NULL DEFAULT 0 CHECK (fee_amount >= 0),
            slippage_cap_bps REAL,
            quote_id TEXT,
            book_id TEXT,
            snapshot_id TEXT,
            snapshot_as_of TEXT,
            order_as_of TEXT NOT NULL,
            freshness_status TEXT NOT NULL CHECK (freshness_status IN ('fresh','stale','missing','unknown')),
            fill_status TEXT NOT NULL CHECK (fill_status IN ('full','partial','no_fill')),
            conservative_fill_model TEXT NOT NULL,
            mark_source TEXT NOT NULL,
            mark_as_of TEXT NOT NULL,
            confidence_label TEXT NOT NULL CHECK (confidence_label IN ('low','medium','high','unknown')),
            staleness_status TEXT NOT NULL CHECK (staleness_status IN ('fresh','stale','missing','unknown')),
            source_precedence INTEGER NOT NULL DEFAULT 1000,
            caveats_json TEXT NOT NULL DEFAULT '[]',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            recorded_at TEXT NOT NULL,
            idempotency_key TEXT,
            actor_id TEXT NOT NULL,
            FOREIGN KEY (market_id) REFERENCES markets(id),
            FOREIGN KEY (instrument_id) REFERENCES instruments(id),
            FOREIGN KEY (pretrade_intent_id) REFERENCES pretrade_intents(id)
        )
        """,
    )
    conn.execute("CREATE INDEX idx_paper_fills_scope ON paper_fill_records(environment_label, account_label)")
    conn.execute("CREATE INDEX idx_paper_fills_market ON paper_fill_records(market_id, instrument_id)")
    conn.execute("CREATE INDEX idx_paper_fills_order_as_of ON paper_fill_records(order_as_of)")
    conn.execute(
        """
        CREATE TRIGGER trg_paper_fill_records_no_update
        BEFORE UPDATE ON paper_fill_records
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on paper_fill_records is forbidden; append a correction');
        END
        """,
    )
    conn.execute(
        """
        CREATE TRIGGER trg_paper_fill_records_no_delete
        BEFORE DELETE ON paper_fill_records
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on paper_fill_records is forbidden');
        END
        """,
    )


__all__ = ["_migration_022_paper_fills"]
