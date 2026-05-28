"""Migration 016_risk_policy_receipts.

Durable audit-only risk policy versions and pre-trade check receipts.
"""

from __future__ import annotations

import sqlite3


def _migration_016_risk_policy_receipts(conn: sqlite3.Connection) -> None:
    """Create immutable risk policy/version and receipt tables."""

    conn.execute(
        """
        CREATE TABLE risk_policy_versions (
            id TEXT PRIMARY KEY,
            policy_key TEXT NOT NULL,
            version TEXT NOT NULL,
            policy_hash TEXT NOT NULL,
            limits_json TEXT NOT NULL,
            rules_json TEXT NOT NULL,
            source TEXT NOT NULL,
            provenance_json TEXT NOT NULL DEFAULT '{}',
            effective_from TEXT NOT NULL,
            effective_to TEXT,
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            UNIQUE (policy_key, version),
            UNIQUE (policy_hash),
            CHECK (effective_to IS NULL OR effective_to >= effective_from)
        )
        """,
    )
    conn.execute(
        "CREATE INDEX idx_risk_policy_versions_key_effective "
        "ON risk_policy_versions(policy_key, effective_from)"
    )
    conn.execute(
        """
        CREATE TRIGGER trg_risk_policy_versions_no_update
        BEFORE UPDATE ON risk_policy_versions
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on risk_policy_versions is forbidden; create a new version');
        END
        """,
    )
    conn.execute(
        """
        CREATE TRIGGER trg_risk_policy_versions_no_delete
        BEFORE DELETE ON risk_policy_versions
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on risk_policy_versions is forbidden');
        END
        """,
    )

    conn.execute(
        """
        CREATE TABLE risk_check_receipts (
            id TEXT PRIMARY KEY,
            receipt_hash TEXT NOT NULL UNIQUE,
            policy_version_id TEXT NOT NULL REFERENCES risk_policy_versions(id),
            status TEXT NOT NULL CHECK (status IN ('pass','warn','fail','missing_data')),
            outcome TEXT NOT NULL CHECK (outcome IN (
                'pass','warning','hard_block','missing_data','stale_data','waived_warning'
            )),
            intended_action TEXT,
            proposed_intent_hash TEXT,
            decision_id TEXT REFERENCES decisions(id),
            market_id TEXT REFERENCES markets(id),
            instrument_id TEXT REFERENCES instruments(id),
            strategy_id TEXT REFERENCES strategies(id),
            snapshot_id TEXT REFERENCES snapshots(id),
            exposure_input_ids_json TEXT NOT NULL DEFAULT '[]',
            evidence_input_ids_json TEXT NOT NULL DEFAULT '[]',
            input_provenance_json TEXT NOT NULL DEFAULT '{}',
            as_of TEXT NOT NULL,
            waived_by TEXT,
            waiver_reason TEXT,
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            CHECK (status != 'pass' OR outcome = 'pass'),
            CHECK (outcome != 'waived_warning' OR waived_by IS NOT NULL)
        )
        """,
    )
    conn.execute("CREATE INDEX idx_risk_check_receipts_policy ON risk_check_receipts(policy_version_id)")
    conn.execute("CREATE INDEX idx_risk_check_receipts_status_created ON risk_check_receipts(status, created_at)")
    conn.execute("CREATE INDEX idx_risk_check_receipts_decision ON risk_check_receipts(decision_id)")
    conn.execute("CREATE INDEX idx_risk_check_receipts_instrument ON risk_check_receipts(instrument_id)")

    conn.execute(
        """
        CREATE TABLE risk_check_rule_results (
            id TEXT PRIMARY KEY,
            receipt_id TEXT NOT NULL REFERENCES risk_check_receipts(id) ON DELETE CASCADE,
            rule_id TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            severity TEXT NOT NULL CHECK (severity IN ('info','warning','hard_block','missing_data')),
            observed_value_json TEXT,
            threshold_json TEXT,
            contributing_record_ids_json TEXT NOT NULL DEFAULT '[]',
            waiver_required INTEGER NOT NULL CHECK (waiver_required IN (0, 1)),
            caveat TEXT,
            missing_data INTEGER NOT NULL DEFAULT 0 CHECK (missing_data IN (0, 1)),
            stale_data INTEGER NOT NULL DEFAULT 0 CHECK (stale_data IN (0, 1)),
            UNIQUE (receipt_id, rule_id)
        )
        """,
    )
    conn.execute("CREATE INDEX idx_risk_check_rule_results_receipt ON risk_check_rule_results(receipt_id)")
