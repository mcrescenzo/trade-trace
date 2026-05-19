"""Forward-only schema migrations per operability.md §4.

Each migration is an ordered callable `(connection) -> None` that bumps the
`meta.schema_version` integer by exactly one. Migrations are idempotent in
the sense that re-applying them against an already-migrated database is a
no-op (the version check short-circuits); but a partial mid-migration crash
is rolled back by SQLite WAL.

Adding a migration is a one-line append to MIGRATIONS plus the migration
function below. Removing or reordering is a breaking change requiring a
contract version bump.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from trade_trace.storage.policy import check_no_reverse_migration

Migration = Callable[[sqlite3.Connection], None]


def _migration_001_meta_table(conn: sqlite3.Connection) -> None:
    """Initial migration: create the `meta` table that stores schema_version
    and the package/contract version pair the DB was initialized against.

    `meta` is a low-volume key/value table. Updates write a corresponding
    `meta.updated` event once events ship in M1 (persistence.md §2).
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def _migration_002_events_outbox(conn: sqlite3.Connection) -> None:
    """Create the `events` log and `outbox` queue per persistence.md §3-§4.

    `events` is append-only; the deduplication index is the partial unique
    index on `(event_type, actor_id, idempotency_key)` where the key is not
    null (per persistence.md §3 indexes block). `outbox` is the queue that
    drives optional JSONL export; one row per `events.id` when export is
    enabled.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            subject_kind TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            idempotency_key TEXT,
            created_at TEXT NOT NULL,
            request_id TEXT,
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_subject "
        "ON events(subject_kind, subject_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at)"
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_events_idempotency
        ON events(event_type, actor_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            export_kind TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending'
                CHECK (state IN ('pending', 'exported', 'failed')),
            exported_at TEXT,
            error_text TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_outbox_pending "
        "ON outbox(state, export_kind, id)"
    )

    # `config` is a key/value table for runtime flags like
    # `outbox.jsonl_enabled`. Distinct from `meta` (which holds
    # immutable-after-init schema/version metadata).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


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


def _migration_005_signals(conn: sqlite3.Connection) -> None:
    """M2 signals table per trade-trace-och.

    Append-only. Rows are emitted lazily by `report.coach` or an explicit
    scan tool — never by a background daemon. `kind` is an open enum
    (extensions are non-breaking per operability.md §4.3); `severity` is
    a closed enum CHECK-constrained to {info, warn, critical}. Indexed
    on (kind, severity, created_at) for the coach's scan query.
    """

    conn.execute(
        """
        CREATE TABLE signals (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            severity TEXT NOT NULL CHECK (severity IN ('info','warn','critical')),
            body TEXT,
            meta_json TEXT NOT NULL DEFAULT '{}',
            related_refs_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            expires_at TEXT,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_signals_scan ON signals(kind, severity, created_at)"
    )
    conn.execute(
        "CREATE INDEX idx_signals_expires ON signals(expires_at) "
        "WHERE expires_at IS NOT NULL"
    )

    # Append-only triggers per persistence.md §8 (signals is on the
    # append-only list there).
    update_msg = (
        "append-only invariant: UPDATE on signals is forbidden; "
        "emit a new signal row to record a change (persistence.md §8)"
    )
    delete_msg = (
        "append-only invariant: DELETE on signals is forbidden (persistence.md §8)"
    )
    conn.execute(
        f"""
        CREATE TRIGGER trg_signals_no_update
        BEFORE UPDATE ON signals
        BEGIN
            SELECT RAISE(ABORT, '{update_msg}');
        END
        """
    )
    conn.execute(
        f"""
        CREATE TRIGGER trg_signals_no_delete
        BEFORE DELETE ON signals
        BEGIN
            SELECT RAISE(ABORT, '{delete_msg}');
        END
        """
    )


def _migration_006_memory_layer(conn: sqlite3.Connection) -> None:
    """M3 memory layer per bead trade-trace-e86 and docs/architecture/memory-layer.md.

    Adds:
    - `memory_nodes` — append-only typed memory rows (observation,
      reflection, playbook_rule) with bi-temporal validity columns
      (`valid_from`, `valid_to`, `invalidated_at`, `invalidated_by`),
      `importance` (1-10), `confidence_base`, and `decay_rate_per_day`.
    - `memory_recall_events` — append-only log of every `memory.recall`
      call (`strategies_used`, `node_ids_returned` JSON arrays). Drives
      the `memory_node_stats` rebuildable projection.
    - `memory_node_stats` — projection: per-node `recall_count` +
      `last_recalled_at`. Rebuildable from `memory_recall_events` per
      persistence.md §7.
    - `memory_node_fts` — FTS5 virtual table on `body` for the BM25
      recall strategy. The trigger pair keeps it in lockstep with
      `memory_nodes` writes.

    Append-only triggers cover `memory_nodes` and `memory_recall_events`;
    `memory_node_stats` is rebuildable so UPDATE/DELETE are allowed there
    (the projection-rebuild path needs them).
    """

    conn.execute(
        """
        CREATE TABLE memory_nodes (
            id TEXT PRIMARY KEY,
            node_type TEXT NOT NULL CHECK (node_type IN
                ('observation','reflection','playbook_rule')),
            version INTEGER NOT NULL DEFAULT 1,
            parent_node_id TEXT REFERENCES memory_nodes(id),
            title TEXT,
            body TEXT NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{}',
            confidence_base REAL NOT NULL DEFAULT 1.0
                CHECK (confidence_base >= 0.0 AND confidence_base <= 1.0),
            decay_rate_per_day REAL,
            importance INTEGER NOT NULL DEFAULT 5
                CHECK (importance >= 1 AND importance <= 10),
            valid_from TEXT NOT NULL,
            valid_to TEXT,
            invalidated_at TEXT,
            invalidated_by TEXT REFERENCES memory_nodes(id),
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT,
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_memory_nodes_type ON memory_nodes(node_type)")
    conn.execute("CREATE INDEX idx_memory_nodes_validity "
                 "ON memory_nodes(valid_from, valid_to)")

    # Append-only triggers on memory_nodes (persistence.md §8).
    for action, msg in (
        ("UPDATE", "append-only invariant: UPDATE on memory_nodes is forbidden; "
                   "write a new versioned node + supersedes edge"),
        ("DELETE", "append-only invariant: DELETE on memory_nodes is forbidden"),
    ):
        conn.execute(
            f"""
            CREATE TRIGGER trg_memory_nodes_no_{action.lower()}
            BEFORE {action} ON memory_nodes
            BEGIN
                SELECT RAISE(ABORT, '{msg}');
            END
            """
        )

    # FTS5 virtual table for BM25 recall. The trigger pair keeps it in
    # sync with INSERTs (UPDATE/DELETE blocked above, so no DELETE trigger
    # is needed).
    conn.execute(
        """
        CREATE VIRTUAL TABLE memory_node_fts USING fts5(
            id UNINDEXED, title, body,
            tokenize = 'porter ascii'
        )
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_memory_nodes_fts_insert
        AFTER INSERT ON memory_nodes
        BEGIN
            INSERT INTO memory_node_fts(id, title, body)
            VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
        END
        """
    )

    # Append-only recall event log.
    conn.execute(
        """
        CREATE TABLE memory_recall_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recall_id TEXT NOT NULL UNIQUE,
            query TEXT NOT NULL,
            strategies_used TEXT NOT NULL,        -- JSON array
            node_ids_returned TEXT NOT NULL,      -- JSON array; top-k order
            context_json TEXT NOT NULL DEFAULT '{}',
            limit_k INTEGER NOT NULL,
            as_of TEXT,
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT
        )
        """
    )
    conn.execute("CREATE INDEX idx_memory_recall_events_actor "
                 "ON memory_recall_events(actor_id, created_at)")

    for action, msg in (
        ("UPDATE", "append-only invariant: UPDATE on memory_recall_events is "
                   "forbidden"),
        ("DELETE", "append-only invariant: DELETE on memory_recall_events is "
                   "forbidden"),
    ):
        conn.execute(
            f"""
            CREATE TRIGGER trg_memory_recall_events_no_{action.lower()}
            BEFORE {action} ON memory_recall_events
            BEGIN
                SELECT RAISE(ABORT, '{msg}');
            END
            """
        )

    # Rebuildable projection (no triggers — projection rebuild uses
    # DELETE + bulk INSERT inside one transaction per persistence.md §7).
    conn.execute(
        """
        CREATE TABLE memory_node_stats (
            node_id TEXT PRIMARY KEY REFERENCES memory_nodes(id),
            recall_count INTEGER NOT NULL DEFAULT 0,
            last_recalled_at TEXT
        )
        """
    )


def _migration_007_strategies(conn: sqlite3.Connection) -> None:
    """Strategies table per bead trade-trace-ubp.

    First-class strategy rows (not tags). `slug` is a unique lowercase-
    kebab string scoped to a single Trade Trace database; `status` is a
    closed enum (active | archived). Archived strategies remain valid
    FK targets for historical decisions/theses so the audit history
    survives the soft-archive.
    """

    conn.execute(
        """
        CREATE TABLE strategies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE
                CHECK (length(slug) BETWEEN 1 AND 64),
            description TEXT,
            hypothesis TEXT,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','archived')),
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_strategies_slug ON strategies(slug)")
    conn.execute("CREATE INDEX idx_strategies_status ON strategies(status)")
    # Append-only on `created_at` semantics: rows can be UPDATEd by
    # strategy.update (which mutates `description`, `hypothesis`,
    # `status`, `meta_json`, `updated_at`). DELETE is blocked because
    # archived strategies stay live as FK targets.
    conn.execute(
        "CREATE TRIGGER trg_strategies_no_delete "
        "BEFORE DELETE ON strategies BEGIN "
        "SELECT RAISE(ABORT, 'append-only invariant: DELETE on strategies "
        "is forbidden; archive via strategy.update status=archived "
        "instead'); END"
    )


def _migration_008_playbooks(conn: sqlite3.Connection) -> None:
    """M4 playbooks per bead trade-trace-fbq and PRD §4.3.

    Adds:
    - `playbooks`: append-only registry row per named playbook
      (`name` unique). Status field is reserved nullable text for a
      future archive/retired flag; MVP treats all playbooks as live.
    - `playbook_versions`: append-only versions of a playbook. Each
      version requires a `provenance_reflection_node_id` (FK to a
      `memory_nodes` row with `node_type='reflection'`) so the rule
      lineage stays explainable.
    - `decision_playbook_rules`: normalized adherence rows per
      `(decision_id, playbook_version_id, rule_node_id)`. The
      `rule_node_id` references a `memory_nodes` row with
      `node_type='playbook_rule'` — the FK check at write time is
      delegated to the tool layer (SQLite cannot enforce the
      node_type subset alone, so the tool validates before INSERT).
    """

    conn.execute(
        """
        CREATE TABLE playbooks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            status TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_playbooks_name ON playbooks(name)")

    conn.execute(
        """
        CREATE TABLE playbook_versions (
            id TEXT PRIMARY KEY,
            playbook_id TEXT NOT NULL REFERENCES playbooks(id),
            version INTEGER NOT NULL,
            parent_version_id TEXT REFERENCES playbook_versions(id),
            provenance_reflection_node_id TEXT NOT NULL
                REFERENCES memory_nodes(id),
            description TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            UNIQUE (playbook_id, version)
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_playbook_versions_playbook "
        "ON playbook_versions(playbook_id)"
    )

    conn.execute(
        """
        CREATE TABLE decision_playbook_rules (
            id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL REFERENCES decisions(id),
            playbook_version_id TEXT NOT NULL
                REFERENCES playbook_versions(id),
            rule_node_id TEXT NOT NULL REFERENCES memory_nodes(id),
            status TEXT NOT NULL CHECK (status IN
                ('considered','followed','overridden','not_applicable')),
            reason TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            UNIQUE (decision_id, playbook_version_id, rule_node_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_decision_playbook_rules_decision "
        "ON decision_playbook_rules(decision_id)"
    )
    conn.execute(
        "CREATE INDEX idx_decision_playbook_rules_version "
        "ON decision_playbook_rules(playbook_version_id)"
    )
    conn.execute(
        "CREATE INDEX idx_decision_playbook_rules_status "
        "ON decision_playbook_rules(status)"
    )

    # Append-only triggers on all three M4 tables per persistence.md §8.
    for table in ("playbooks", "playbook_versions", "decision_playbook_rules"):
        for action in ("UPDATE", "DELETE"):
            msg = (
                f"append-only invariant: {action} on {table} is forbidden; "
                "append a new version row instead"
            )
            conn.execute(
                f"CREATE TRIGGER trg_{table}_no_{action.lower()} "
                f"BEFORE {action} ON {table} BEGIN "
                f"SELECT RAISE(ABORT, '{msg}'); END"
            )


def _migration_009_events_append_only(conn: sqlite3.Connection) -> None:
    """Harden the durable `events` audit log as append-only.

    `outbox` intentionally remains mutable because exporters update queue
    state (`state`, `exported_at`, `error_text`, `attempt_count`).
    """

    update_msg = (
        "append-only invariant: UPDATE on events is forbidden; "
        "append a new event to record follow-up state (persistence.md §8)"
    )
    delete_msg = (
        "append-only invariant: DELETE on events is forbidden (persistence.md §8)"
    )
    conn.execute(
        f"""
        CREATE TRIGGER trg_events_no_update
        BEFORE UPDATE ON events
        BEGIN
            SELECT RAISE(ABORT, '{update_msg}');
        END
        """
    )
    conn.execute(
        f"""
        CREATE TRIGGER trg_events_no_delete
        BEFORE DELETE ON events
        BEGIN
            SELECT RAISE(ABORT, '{delete_msg}');
        END
        """
    )


MIGRATIONS: list[Migration] = [
    _migration_001_meta_table,
    _migration_002_events_outbox,
    _migration_003_m1_ledger,
    _migration_004_p1_stub_columns,
    _migration_005_signals,
    _migration_006_memory_layer,
    _migration_007_strategies,
    _migration_008_playbooks,
    _migration_009_events_append_only,
]


def current_version(conn: sqlite3.Connection) -> int:
    """Return the integer `schema_version` currently recorded in `meta`,
    or 0 if no `meta` table exists yet (fresh DB)."""

    try:
        cur = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'")
    except sqlite3.OperationalError:
        return 0
    row = cur.fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def apply_pending_migrations(
    conn: sqlite3.Connection,
    *,
    target_version: int | None = None,
) -> tuple[int, int]:
    """Apply migrations from `current_version() + 1` through `target_version`
    (or the end of MIGRATIONS if not specified). Returns (from_version,
    to_version). The migration loop runs inside one SQLite transaction so a
    crash mid-loop leaves the schema_version unchanged."""

    end = len(MIGRATIONS) if target_version is None else target_version
    if end > len(MIGRATIONS):
        raise ValueError(
            f"target_version={target_version} exceeds available migrations "
            f"({len(MIGRATIONS)})"
        )

    start = current_version(conn)
    # Forward-only check: target < current is a hard error (the policy is in
    # storage/policy.py so the rule is shared with linters and tests).
    check_no_reverse_migration(current_version=start, target_version=end)
    if start >= end:
        return start, start

    conn.execute("BEGIN")
    try:
        for i in range(start, end):
            MIGRATIONS[i](conn)
            new_version = i + 1
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(new_version),),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return start, end
