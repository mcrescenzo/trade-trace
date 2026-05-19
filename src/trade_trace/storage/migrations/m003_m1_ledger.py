"""Migration 003_m1_ledger (extracted from storage/migrations.py per trade-trace-58ic). Schema-equivalence is gated by `tests/integration/test_migrations_schema_hash.py`."""

from __future__ import annotations

import sqlite3


def _migration_003_m1_ledger(conn: sqlite3.Connection) -> None:
    """M1 ledger schema per PRD §3.1.

    Creates the source-of-truth tables for manual ingestion plus the minimal
    edges table needed for source attachments (`about`/`supports`/
    `contradicts`) and outcome corrections (`supersedes`). The full memory
    layer (`memory_nodes`, `memory_node_embeddings`, `memory_node_stats`,
    `memory_recall_events`, `signals`, `strategies`) and the expanded edge
    endpoint kinds (`memory_node`, `signal`, `strategy`) plus edge types
    (`derived_from`, `violates`, `follows`) ship in M3.

    Notes:
    - `strategy_id` columns are reserved as nullable TEXT (no FK yet) since
      the `strategies` table is M3.
    - Bi-temporal columns (`valid_from`, `valid_to`, `invalidated_at`,
      `invalidated_by`) on belief-shaped rows.
    - Segmentation columns (`agent_id`, `model_id`, `environment`,
      `run_id`) on rows that participate in `report.compare` group-bys.
    - Append-only invariants enforced by triggers (see below).
    """

    # -- venues ----------------------------------------------------------
    conn.execute(
        """
        CREATE TABLE venues (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN
                ('exchange','broker','prediction_market','dex','otc','manual')),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )

    # -- instruments -----------------------------------------------------
    conn.execute(
        """
        CREATE TABLE instruments (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL REFERENCES venues(id),
            external_id TEXT,
            symbol TEXT,
            title TEXT NOT NULL,
            asset_class TEXT NOT NULL CHECK (asset_class IN
                ('equity','option','future','crypto_spot','crypto_perp',
                 'prediction_market','event_market','fx','commodity','other')),
            currency_or_collateral TEXT,
            expiration_or_resolution_at TEXT,
            resolution_criteria_text TEXT,
            contract_multiplier REAL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_instruments_venue ON instruments(venue_id)")

    # -- snapshots (append-only) -----------------------------------------
    conn.execute(
        """
        CREATE TABLE snapshots (
            id TEXT PRIMARY KEY,
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            captured_at TEXT NOT NULL,
            source TEXT,
            source_url TEXT,
            price REAL,
            bid REAL,
            ask REAL,
            mid REAL,
            spread REAL,
            volume REAL,
            open_interest REAL,
            implied_probability REAL,
            liquidity_depth_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_snapshots_instr_time ON snapshots(instrument_id, captured_at)")

    # -- theses (append-only, versioned) --------------------------------
    conn.execute(
        """
        CREATE TABLE theses (
            id TEXT PRIMARY KEY,
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            version INTEGER NOT NULL DEFAULT 1,
            parent_thesis_id TEXT REFERENCES theses(id),
            side TEXT NOT NULL CHECK (side IN
                ('long','short','yes','no','flat_neutral','pairs_long_short')),
            time_horizon_at TEXT,
            confidence_label TEXT CHECK (confidence_label IS NULL OR
                confidence_label IN ('very_low','low','medium','high','very_high')),
            body TEXT NOT NULL,
            falsification_criteria TEXT,
            exit_triggers TEXT,
            risk_notes TEXT,
            strategy_id TEXT,
            valid_from TEXT,
            valid_to TEXT,
            invalidated_at TEXT,
            invalidated_by TEXT,
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_theses_instr ON theses(instrument_id)")
    conn.execute("CREATE INDEX idx_theses_strategy ON theses(strategy_id)")

    # -- forecasts (append-only) ----------------------------------------
    conn.execute(
        """
        CREATE TABLE forecasts (
            id TEXT PRIMARY KEY,
            thesis_id TEXT NOT NULL REFERENCES theses(id),
            kind TEXT NOT NULL CHECK (kind IN ('binary','categorical','scalar')),
            resolution_at TEXT,
            yes_label TEXT,
            resolution_rule_text TEXT,
            scoring_support TEXT NOT NULL DEFAULT 'supported'
                CHECK (scoring_support IN ('supported','unsupported')),
            scoring_state TEXT NOT NULL DEFAULT 'pending'
                CHECK (scoring_state IN ('pending','scored','failed','superseded')),
            valid_from TEXT,
            valid_to TEXT,
            invalidated_at TEXT,
            invalidated_by TEXT,
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_forecasts_thesis ON forecasts(thesis_id)")
    conn.execute("CREATE INDEX idx_forecasts_state ON forecasts(scoring_state)")

    # -- forecast_outcomes (append-only, one row per outcome label) -----
    conn.execute(
        """
        CREATE TABLE forecast_outcomes (
            id TEXT PRIMARY KEY,
            forecast_id TEXT NOT NULL REFERENCES forecasts(id),
            outcome_label TEXT NOT NULL,
            probability REAL NOT NULL CHECK (probability >= 0.0 AND probability <= 1.0),
            lower_bound REAL,
            upper_bound REAL,
            UNIQUE (forecast_id, outcome_label)
        )
        """
    )

    # -- forecast_scores (append-only) ----------------------------------
    conn.execute(
        """
        CREATE TABLE forecast_scores (
            id TEXT PRIMARY KEY,
            forecast_id TEXT NOT NULL REFERENCES forecasts(id),
            outcome_id TEXT REFERENCES outcomes(id),
            metric TEXT NOT NULL,
            score REAL,
            scored_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute("CREATE INDEX idx_forecast_scores_forecast ON forecast_scores(forecast_id)")

    # -- decisions (append-only) ----------------------------------------
    conn.execute(
        """
        CREATE TABLE decisions (
            id TEXT PRIMARY KEY,
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            thesis_id TEXT REFERENCES theses(id),
            forecast_id TEXT REFERENCES forecasts(id),
            snapshot_id TEXT REFERENCES snapshots(id),
            type TEXT NOT NULL CHECK (type IN
                ('watch','skip','paper_enter','paper_exit','actual_enter',
                 'actual_exit','add','reduce','hold','invalidate_thesis',
                 'update_thesis','resolved','review')),
            side TEXT CHECK (side IS NULL OR side IN
                ('long','short','yes','no','flat_neutral','pairs_long_short')),
            quantity REAL,
            price REAL,
            fees REAL,
            slippage REAL,
            reason TEXT,
            playbook_version_id TEXT,
            review_by TEXT,
            strategy_id TEXT,
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_decisions_instr ON decisions(instrument_id)")
    conn.execute("CREATE INDEX idx_decisions_thesis ON decisions(thesis_id)")
    conn.execute("CREATE INDEX idx_decisions_strategy ON decisions(strategy_id)")

    # -- decision_tags (append-only) ------------------------------------
    conn.execute(
        """
        CREATE TABLE decision_tags (
            decision_id TEXT NOT NULL REFERENCES decisions(id),
            tag TEXT NOT NULL,
            PRIMARY KEY (decision_id, tag)
        )
        """
    )
    conn.execute("CREATE INDEX idx_decision_tags_tag ON decision_tags(tag)")

    # -- outcomes (append-only) ------------------------------------------
    conn.execute(
        """
        CREATE TABLE outcomes (
            id TEXT PRIMARY KEY,
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            resolved_at TEXT NOT NULL,
            outcome_label TEXT NOT NULL,
            outcome_value REAL,
            status TEXT NOT NULL CHECK (status IN
                ('resolved_final','resolved_provisional','ambiguous',
                 'disputed','void','cancelled')),
            source TEXT,
            confidence REAL,
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_outcomes_instr_time ON outcomes(instrument_id, resolved_at)")

    # -- sources (append-only) -------------------------------------------
    conn.execute(
        """
        CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN
                ('url','pdf','image','tweet','news_article','research_doc',
                 'transcript','chart_image','note','other')),
            ref TEXT,
            title TEXT,
            note TEXT,
            stance TEXT NOT NULL DEFAULT 'neutral'
                CHECK (stance IN ('supports','contradicts','neutral')),
            freshness_at TEXT,
            content_hash TEXT,
            captured_at TEXT,
            uri TEXT,
            media_type TEXT,
            storage_kind TEXT NOT NULL DEFAULT 'inline_text'
                CHECK (storage_kind IN ('url','local_path','inline_text','external_ref')),
            retrieved_at TEXT,
            source_author TEXT,
            publisher TEXT,
            excerpt TEXT,
            extracted_text TEXT,
            summary TEXT,
            hash_algorithm TEXT CHECK (hash_algorithm IS NULL OR
                hash_algorithm IN ('sha256','sha512','blake3','none')),
            redaction_status TEXT NOT NULL DEFAULT 'none'
                CHECK (redaction_status IN ('none','redacted','sensitive')),
            license_or_terms_note TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )

    # -- edges (append-only, M1 minimal endpoint/edge enums) -------------
    # M1 endpoints: decision, thesis, forecast, outcome, snapshot, instrument,
    # venue, source, review, playbook_version.
    # M1 edge types: about, supports, contradicts, supersedes.
    # `signal`/`strategy`/`memory_node` endpoint kinds and `derived_from`/
    # `violates`/`follows` edge types are M3 (PRD §3.2).
    conn.execute(
        """
        CREATE TABLE edges (
            id TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL CHECK (source_kind IN
                ('decision','thesis','forecast','outcome','snapshot',
                 'instrument','venue','source','review','playbook_version',
                 'memory_node','signal','strategy')),
            source_id TEXT NOT NULL,
            target_kind TEXT NOT NULL CHECK (target_kind IN
                ('decision','thesis','forecast','outcome','snapshot',
                 'instrument','venue','source','review','playbook_version',
                 'memory_node','signal','strategy')),
            target_id TEXT NOT NULL,
            edge_type TEXT NOT NULL CHECK (edge_type IN
                ('about','supports','contradicts','supersedes',
                 'derived_from','violates','follows')),
            weight REAL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_edges_source ON edges(source_kind, source_id)")
    conn.execute("CREATE INDEX idx_edges_target ON edges(target_kind, target_id)")
    conn.execute("CREATE INDEX idx_edges_type ON edges(edge_type)")

    # -- position_events (append-only) ----------------------------------
    conn.execute(
        """
        CREATE TABLE position_events (
            id TEXT PRIMARY KEY,
            position_id TEXT NOT NULL,
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            decision_id TEXT REFERENCES decisions(id),
            event_type TEXT NOT NULL CHECK (event_type IN
                ('open','add','reduce','close','mark','expire','assigned','corrected')),
            quantity_delta REAL,
            price REAL,
            fees REAL,
            slippage REAL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_position_events_position ON position_events(position_id)")
    conn.execute("CREATE INDEX idx_position_events_instr ON position_events(instrument_id)")

    # -- positions (PROJECTION - mutable, rebuildable) -------------------
    conn.execute(
        """
        CREATE TABLE positions (
            id TEXT PRIMARY KEY,
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            kind TEXT NOT NULL CHECK (kind IN ('paper','actual','simulation')),
            side TEXT NOT NULL CHECK (side IN
                ('long','short','yes','no','pairs_long_short')),
            status TEXT NOT NULL CHECK (status IN
                ('open','partial','closed','resolved','expired','assigned','voided')),
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            resolved_at TEXT,
            realized_pnl REAL,
            unrealized_pnl REAL,
            avg_entry_price REAL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_positions_instr ON positions(instrument_id)")
    conn.execute("CREATE INDEX idx_positions_status ON positions(status)")

    # -- Append-only triggers per persistence.md §8 ----------------------
    # Tables that are strictly append-only: snapshots, theses, forecasts,
    # forecast_outcomes, forecast_scores, decisions, decision_tags,
    # outcomes, sources, edges, position_events.
    # NOT in this list: events/outbox (M0 tables; events append-only triggers
    # are added by migration 009 while outbox remains mutable), positions
    # (projection - mutable by definition), and the M0
    # `meta`/`config` k/v tables (which allow upserts).
    append_only_tables = [
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
    ]
    for table in append_only_tables:
        update_msg = (
            f"append-only invariant: UPDATE on {table} is forbidden; "
            f"use a supersedes edge to record a correction (persistence.md §8)"
        )
        delete_msg = (
            f"append-only invariant: DELETE on {table} is forbidden (persistence.md §8)"
        )
        conn.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_update
            BEFORE UPDATE ON {table}
            BEGIN
                SELECT RAISE(ABORT, '{update_msg}');
            END
            """
        )
        conn.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN
                SELECT RAISE(ABORT, '{delete_msg}');
            END
            """
        )
