"""Migration 025_polymarket_resolution_finality.

Expand outcome lifecycle statuses for local Polymarket finality evidence.
SQLite cannot alter CHECK constraints in place, so rebuild outcomes with the
same columns and a wider status enum. Rows remain append-only evidence; this
migration introduces no venue action or network behavior.
"""

from __future__ import annotations

import sqlite3

_OUTCOME_STATUSES = (
    "resolved_final",
    "resolved_provisional",
    "proposed",
    "provisional",
    "disputed",
    "ambiguous",
    "void",
    "cancelled",
    "imported_redeemed",
    "imported_settled",
)


def _migration_025_polymarket_resolution_finality(conn: sqlite3.Connection) -> None:
    status_sql = ",".join(f"'{status}'" for status in _OUTCOME_STATUSES)
    # PRAGMA legacy_alter_table is session-scoped and is NOT reset by a
    # SQLite ROLLBACK (verified experimentally). If the migration body raises
    # between the ON and OFF below, the pragma would leak ON for the rest of
    # the connection's lifetime, silently changing RENAME-based ALTER TABLE
    # semantics for any later migration on the same connection (e.g. after a
    # retry). The transaction ROLLBACK handles DDL atomicity; the pragma needs
    # its own cleanup path. See bead trade-trace-x17b.
    conn.execute("PRAGMA legacy_alter_table=ON")
    try:
        _rebuild_outcomes_and_forecast_scores(conn, status_sql)
    finally:
        conn.execute("PRAGMA legacy_alter_table=OFF")


def _rebuild_outcomes_and_forecast_scores(
    conn: sqlite3.Connection, status_sql: str
) -> None:
    conn.execute("DROP TRIGGER IF EXISTS trg_outcomes_no_update")
    conn.execute("DROP TRIGGER IF EXISTS trg_outcomes_no_delete")
    conn.execute("ALTER TABLE outcomes RENAME TO outcomes__m025_old")
    conn.execute("DROP INDEX IF EXISTS idx_outcomes_instr_time")
    conn.execute(
        f"""
        CREATE TABLE outcomes (
            id TEXT PRIMARY KEY,
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            resolved_at TEXT NOT NULL,
            outcome_label TEXT NOT NULL,
            outcome_value REAL,
            status TEXT NOT NULL CHECK (status IN ({status_sql})),
            source TEXT,
            confidence REAL,
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO outcomes(
            id, instrument_id, resolved_at, outcome_label, outcome_value,
            status, source, confidence, agent_id, model_id, environment,
            run_id, metadata_json, created_at, actor_id
        )
        SELECT
            id, instrument_id, resolved_at, outcome_label, outcome_value,
            status, source, confidence, agent_id, model_id, environment,
            run_id, metadata_json, created_at, actor_id
        FROM outcomes__m025_old
        """
    )
    conn.execute("CREATE INDEX idx_outcomes_instr_time ON outcomes(instrument_id, resolved_at)")
    conn.execute("DROP TRIGGER IF EXISTS trg_forecast_scores_no_update")
    conn.execute("DROP TRIGGER IF EXISTS trg_forecast_scores_no_delete")
    conn.execute("ALTER TABLE forecast_scores RENAME TO forecast_scores__m025_old")
    conn.execute("DROP INDEX IF EXISTS idx_forecast_scores_forecast")
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
    conn.execute(
        """
        INSERT INTO forecast_scores(
            id, forecast_id, outcome_id, metric, score, scored_at, actor_id, metadata_json
        )
        SELECT id, forecast_id, outcome_id, metric, score, scored_at, actor_id, metadata_json
        FROM forecast_scores__m025_old
        """
    )
    conn.execute("DROP TABLE forecast_scores__m025_old")
    conn.execute("DROP TABLE outcomes__m025_old")
    conn.execute("CREATE INDEX idx_forecast_scores_forecast ON forecast_scores(forecast_id)")
    conn.execute(
        """
        CREATE TRIGGER trg_forecast_scores_no_update
        BEFORE UPDATE ON forecast_scores
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on forecast_scores is forbidden (persistence.md §8)');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_forecast_scores_no_delete
        BEFORE DELETE ON forecast_scores
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on forecast_scores is forbidden (persistence.md §8)');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_outcomes_no_update
        BEFORE UPDATE ON outcomes
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on outcomes is forbidden; use a supersedes edge to record a correction (persistence.md §8)');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_outcomes_no_delete
        BEFORE DELETE ON outcomes
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on outcomes is forbidden (persistence.md §8)');
        END
        """
    )


__all__ = ["_migration_025_polymarket_resolution_finality"]
