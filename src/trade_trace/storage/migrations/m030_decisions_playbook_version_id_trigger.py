"""Migration 030_decisions_playbook_version_id_trigger.

Validate `decisions.playbook_version_id` on new inserts against the
`playbook_versions` table (bead trade-trace-2kpi).

Migration 003 reserved `playbook_version_id` as a bare nullable TEXT
column on `decisions` with no `REFERENCES` clause and no insert-time
trigger, because the `playbook_versions` table itself didn't exist
until migration 008. By contrast, `decisions.strategy_id` received
trigger-based enforcement in migration 010
(`trg_decisions_strategy_id_exists`). That asymmetry left a hole: a
decision row can be written with a `playbook_version_id` that points at
a non-existent `playbook_versions` row and the FK violation is silent,
which makes playbook-adherence reports and lineage queries fragile.

Policy: a new-row trigger (the same grandfathering pattern as
migration 010). NULL stays legal (the canonical "no playbook version"
value). Non-NULL values must exist in `playbook_versions` at insert
time. Rows that predated this migration are NOT validated — historic
data is grandfathered.

Why not a strict FK: SQLite cannot add foreign keys to an existing
table via ALTER TABLE; a rebuild would require copying every row and
would break the append-only invariant during the copy. A BEFORE INSERT
trigger gives the same enforcement at insert time without touching
history — identical to the choice made for `strategy_id` in m010.
"""

from __future__ import annotations

import sqlite3


def _migration_030_decisions_playbook_version_id_trigger(
    conn: sqlite3.Connection,
) -> None:
    """Add a BEFORE INSERT trigger on `decisions` that aborts when a
    non-NULL `playbook_version_id` is absent from `playbook_versions`.
    Mirrors m010's `trg_decisions_strategy_id_exists` for `strategy_id`.
    """

    msg = (
        "VALIDATION_ERROR: decisions.playbook_version_id references "
        "nonexistent playbook_version; create the playbook version first "
        "or leave the column NULL (bead trade-trace-2kpi)"
    )
    conn.execute(
        "CREATE TRIGGER trg_decisions_playbook_version_id_exists "
        "BEFORE INSERT ON decisions "
        "WHEN NEW.playbook_version_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM playbook_versions WHERE id = NEW.playbook_version_id) "
        f"BEGIN SELECT RAISE(ABORT, '{msg}'); END"
    )


__all__ = ["_migration_030_decisions_playbook_version_id_trigger"]
