"""Migration 012_markets.

Add a prediction-market lifecycle anchor table. Population and adapter binding
ship later; this migration only establishes the durable schema surface.
"""

from __future__ import annotations

import sqlite3


def _migration_012_markets(conn: sqlite3.Connection) -> None:
    """Create markets table for venue market metadata and lifecycle state."""

    conn.execute(
        """
        CREATE TABLE markets (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL CHECK (source IN
                ('polymarket','kalshi','manifold','predictit','manual')),
            external_id TEXT NOT NULL,
            title TEXT,
            question TEXT,
            url TEXT,
            state TEXT NOT NULL CHECK (state IN
                ('open','closed_for_trading','resolving','resolved','voided','ambiguous')),
            mechanism TEXT NOT NULL CHECK (mechanism IN
                ('clob','amm','scalar','hybrid')),
            resolution_source TEXT CHECK (resolution_source IS NULL OR
                resolution_source IN ('market_contract','oracle_feed','manual_review','arbitration')),
            ambiguity_kind TEXT CHECK (ambiguity_kind IS NULL OR
                ambiguity_kind IN ('market_rules_unclear','oracle_dispute',
                    'event_happened_but_label_ambiguous','event_null_and_void')),
            bound_via TEXT NOT NULL CHECK (bound_via IN ('adapter','manual')),
            opened_at TEXT,
            close_at TEXT,
            closed_for_trading_at TEXT,
            resolving_at TEXT,
            resolved_at TEXT,
            voided_at TEXT,
            ambiguous_at TEXT,
            venue_metadata_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            UNIQUE (source, external_id)
        )
        """
    )
    conn.execute("CREATE INDEX idx_markets_source_external ON markets(source, external_id)")
    conn.execute("CREATE INDEX idx_markets_state ON markets(state)")
    conn.execute("CREATE INDEX idx_markets_close_at ON markets(close_at)")
