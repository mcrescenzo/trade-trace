"""Migration 008_playbooks (extracted from storage/migrations.py per trade-trace-58ic). Schema-equivalence is gated by `tests/integration/test_migrations_schema_hash.py`."""

from __future__ import annotations

import sqlite3


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
