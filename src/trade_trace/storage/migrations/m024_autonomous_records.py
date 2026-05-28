"""Migration 024_autonomous_records.

Append-only local audit records for autonomous run/session metadata and
operator-supplied incident facts. These tables do not supervise runtime, start
agents, schedule work, fetch broker/private state, execute/cancel orders, or
remediate incidents.
"""

from __future__ import annotations

import sqlite3


def _migration_024_autonomous_records(conn: sqlite3.Connection) -> None:
    """Create append-only autonomous run/session and incident records."""

    conn.execute(
        """
        CREATE TABLE autonomous_run_records (
            id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            semantic_key TEXT NOT NULL UNIQUE,
            material_hash TEXT NOT NULL UNIQUE,
            mode TEXT NOT NULL CHECK (mode IN ('autonomous','assisted','manual_replay','simulation','dry_run','unknown')),
            run_status TEXT NOT NULL CHECK (run_status IN ('started','running','completed','failed','blocked','canceled','timed_out','unknown')),
            run_id TEXT NOT NULL,
            session_id TEXT,
            actor_id_recorded TEXT,
            model_id TEXT,
            provider_id TEXT,
            environment_label TEXT,
            policy_version TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            as_of TEXT NOT NULL,
            config_json TEXT NOT NULL DEFAULT '{}',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            caveats_json TEXT NOT NULL DEFAULT '[]',
            recorded_at TEXT NOT NULL,
            idempotency_key TEXT,
            recorder_actor_id TEXT NOT NULL
        )
        """,
    )
    conn.execute("CREATE INDEX idx_autonomous_run_records_run_id ON autonomous_run_records(run_id)")
    conn.execute("CREATE INDEX idx_autonomous_run_records_session_id ON autonomous_run_records(session_id)")
    conn.execute("CREATE INDEX idx_autonomous_run_records_status ON autonomous_run_records(run_status)")
    conn.execute("CREATE INDEX idx_autonomous_run_records_as_of ON autonomous_run_records(as_of)")

    conn.execute(
        """
        CREATE TABLE autonomous_incident_records (
            id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            semantic_key TEXT NOT NULL UNIQUE,
            material_hash TEXT NOT NULL UNIQUE,
            incident_type TEXT NOT NULL CHECK (incident_type IN ('blocked_action','kill_switch','cancel_only','missing_evidence','policy_violation','reconciliation_mismatch','approval_gap','execution_receipt_gap','recovery_item','operator_note','other')),
            severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
            resolution_status TEXT NOT NULL CHECK (resolution_status IN ('unresolved','monitoring','explained','accepted_caveat','resolved','superseded','not_applicable')),
            run_record_id TEXT,
            run_id TEXT,
            session_id TEXT,
            occurred_at TEXT NOT NULL,
            as_of TEXT NOT NULL,
            summary TEXT NOT NULL,
            imported_fact_only INTEGER NOT NULL DEFAULT 1 CHECK (imported_fact_only IN (0,1)),
            evidence_state TEXT NOT NULL CHECK (evidence_state IN ('complete','sparse','missing','conflicting','unknown')),
            link_ids_json TEXT NOT NULL DEFAULT '{}',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            caveats_json TEXT NOT NULL DEFAULT '[]',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            recorded_at TEXT NOT NULL,
            idempotency_key TEXT,
            recorder_actor_id TEXT NOT NULL,
            FOREIGN KEY(run_record_id) REFERENCES autonomous_run_records(id)
        )
        """,
    )
    conn.execute("CREATE INDEX idx_autonomous_incident_records_run_id ON autonomous_incident_records(run_id)")
    conn.execute("CREATE INDEX idx_autonomous_incident_records_session_id ON autonomous_incident_records(session_id)")
    conn.execute("CREATE INDEX idx_autonomous_incident_records_type ON autonomous_incident_records(incident_type)")
    conn.execute("CREATE INDEX idx_autonomous_incident_records_status ON autonomous_incident_records(resolution_status)")
    conn.execute("CREATE INDEX idx_autonomous_incident_records_as_of ON autonomous_incident_records(as_of)")

    for table in ("autonomous_run_records", "autonomous_incident_records"):
        conn.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_update
            BEFORE UPDATE ON {table}
            BEGIN
                SELECT RAISE(ABORT, 'append-only invariant: UPDATE on {table} is forbidden; append a new record');
            END
            """,
        )
        conn.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN
                SELECT RAISE(ABORT, 'append-only invariant: DELETE on {table} is forbidden');
            END
            """,
        )


__all__ = ["_migration_024_autonomous_records"]
