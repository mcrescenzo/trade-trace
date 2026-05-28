"""Migration 026_replay_evaluation_artifacts.

Append-only registry for externally generated replay/evaluation artifacts. These
records are review evidence only: no simulation, backtest execution, strategy
optimization, data fetching, trade advice, or execution path is introduced.
"""

from __future__ import annotations

import sqlite3


def _migration_026_replay_evaluation_artifacts(conn: sqlite3.Connection) -> None:
    """Create append-only replay/evaluation artifact registry."""

    conn.execute(
        """
        CREATE TABLE replay_evaluation_artifacts (
            id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            semantic_key TEXT NOT NULL UNIQUE,
            material_hash TEXT NOT NULL UNIQUE,
            artifact_type TEXT NOT NULL CHECK (artifact_type IN ('historical_simulation','paper','imported_live','evaluation_report','dataset','other')),
            evidence_mode TEXT NOT NULL CHECK (evidence_mode IN ('historical_simulation','paper','imported_live','other')),
            dataset_hash TEXT NOT NULL,
            strategy_id TEXT,
            strategy_version TEXT NOT NULL,
            parameters_json TEXT NOT NULL DEFAULT '{}',
            assumptions_json TEXT NOT NULL DEFAULT '{}',
            fill_model_json TEXT NOT NULL DEFAULT '{}',
            slippage_model_json TEXT NOT NULL DEFAULT '{}',
            result_summary_json TEXT NOT NULL DEFAULT '{}',
            sample_size INTEGER NOT NULL DEFAULT 0 CHECK (sample_size >= 0),
            source_links_json TEXT NOT NULL DEFAULT '[]',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            caveats_json TEXT NOT NULL DEFAULT '[]',
            redaction_profile TEXT NOT NULL,
            redacted_artifact_ref TEXT,
            as_of TEXT NOT NULL,
            evaluated_at TEXT,
            imported_at TEXT NOT NULL,
            idempotency_key TEXT,
            actor_id TEXT NOT NULL
        )
        """,
    )
    conn.execute("CREATE INDEX idx_replay_eval_artifacts_strategy ON replay_evaluation_artifacts(strategy_id, strategy_version)")
    conn.execute("CREATE INDEX idx_replay_eval_artifacts_dataset_hash ON replay_evaluation_artifacts(dataset_hash)")
    conn.execute("CREATE INDEX idx_replay_eval_artifacts_as_of ON replay_evaluation_artifacts(as_of)")
    conn.execute("CREATE INDEX idx_replay_eval_artifacts_evidence_mode ON replay_evaluation_artifacts(evidence_mode)")
    conn.execute(
        """
        CREATE TRIGGER trg_replay_evaluation_artifacts_no_update
        BEFORE UPDATE ON replay_evaluation_artifacts
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on replay_evaluation_artifacts is forbidden; append a new artifact record');
        END
        """,
    )
    conn.execute(
        """
        CREATE TRIGGER trg_replay_evaluation_artifacts_no_delete
        BEFORE DELETE ON replay_evaluation_artifacts
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on replay_evaluation_artifacts is forbidden');
        END
        """,
    )


__all__ = ["_migration_026_replay_evaluation_artifacts"]
