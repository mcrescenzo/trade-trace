"""Migration 014_pm_forecast_memory_transition.

Additive PM forecast/memory transition checkpoint.

This migration intentionally does not drop/rebuild legacy theses,
forecast_outcomes, venues, instruments, or legacy runtime columns.  It adds the
canonical forecast fields and the memory_nodes.metadata_json alias column, then
performs only deterministic bounded backfills from existing rows.
"""

from __future__ import annotations

import sqlite3


def _migration_014_pm_forecast_memory_transition(conn: sqlite3.Connection) -> None:
    """Add canonical forecast columns and memory metadata alias."""

    # SQLite ADD COLUMN permits column-level CHECK/REFERENCES on nullable columns;
    # table-level pruning/rebuilds are deliberately deferred to later slices.
    for ddl in (
        "ALTER TABLE forecasts ADD COLUMN market_id TEXT REFERENCES markets(id)",
        "ALTER TABLE forecasts ADD COLUMN rationale_body TEXT",
        "ALTER TABLE forecasts ADD COLUMN falsification_criteria TEXT",
        "ALTER TABLE forecasts ADD COLUMN updated_rationale_at TEXT",
        "ALTER TABLE forecasts ADD COLUMN updated_rationale_by TEXT",
        "ALTER TABLE forecasts ADD COLUMN probability REAL CHECK (probability IS NULL OR (probability >= 0.0 AND probability <= 1.0))",
        "ALTER TABLE memory_nodes ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
    ):
        conn.execute(ddl)

    conn.execute("CREATE INDEX idx_forecasts_market ON forecasts(market_id)")

    # Existing append-only triggers block UPDATEs. Temporarily remove only the
    # update triggers needed for deterministic migration backfill, then restore
    # their original append-only behavior before returning.
    conn.execute("DROP TRIGGER trg_forecasts_no_update")
    conn.execute("DROP TRIGGER trg_memory_nodes_no_update")
    try:
        conn.execute(
            """
            UPDATE forecasts
            SET market_id = (
                SELECT m.id
                FROM theses t
                JOIN markets m ON m.id = t.instrument_id
                WHERE t.id = forecasts.thesis_id
            )
            WHERE market_id IS NULL
              AND EXISTS (
                SELECT 1
                FROM theses t
                JOIN markets m ON m.id = t.instrument_id
                WHERE t.id = forecasts.thesis_id
              )
            """
        )
        conn.execute(
            """
            UPDATE forecasts
            SET rationale_body = COALESCE(rationale_body, (
                    SELECT t.body FROM theses t WHERE t.id = forecasts.thesis_id
                )),
                falsification_criteria = COALESCE(falsification_criteria, (
                    SELECT t.falsification_criteria FROM theses t WHERE t.id = forecasts.thesis_id
                ))
            WHERE EXISTS (SELECT 1 FROM theses t WHERE t.id = forecasts.thesis_id)
            """
        )
        conn.execute(
            """
            UPDATE forecasts
            SET probability = (
                SELECT fo.probability
                FROM forecast_outcomes fo
                WHERE fo.forecast_id = forecasts.id
                  AND lower(fo.outcome_label) = lower(COALESCE(forecasts.yes_label, 'yes'))
                  AND (
                    lower(COALESCE(forecasts.yes_label, 'yes')) = 'yes'
                    OR lower(fo.outcome_label) = lower(forecasts.yes_label)
                  )
                GROUP BY fo.forecast_id
                HAVING COUNT(*) = 1
            )
            WHERE probability IS NULL
              AND (
                SELECT COUNT(*)
                FROM forecast_outcomes fo
                WHERE fo.forecast_id = forecasts.id
                  AND lower(fo.outcome_label) = lower(COALESCE(forecasts.yes_label, 'yes'))
                  AND (
                    lower(COALESCE(forecasts.yes_label, 'yes')) = 'yes'
                    OR lower(fo.outcome_label) = lower(forecasts.yes_label)
                  )
              ) = 1
            """
        )
        conn.execute(
            """
            UPDATE memory_nodes
            SET metadata_json = meta_json
            WHERE metadata_json = '{}'
              AND meta_json IS NOT NULL
            """
        )
    finally:
        conn.execute(
            """
            CREATE TRIGGER trg_forecasts_no_update
            BEFORE UPDATE ON forecasts
            BEGIN
                SELECT RAISE(ABORT, 'append-only invariant: UPDATE on forecasts is forbidden; use a supersedes edge to record a correction (persistence.md §8)');
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER trg_memory_nodes_no_update
            BEFORE UPDATE ON memory_nodes
            BEGIN
                SELECT RAISE(ABORT, 'append-only invariant: UPDATE on memory_nodes is forbidden; write a new versioned node + supersedes edge');
            END
            """
        )
