"""Migration 017_expanded_source_stances.

Expand the storage-pinned ``sources.stance`` enum for agent-native evidence
packets. SQLite cannot alter CHECK constraints in place, so this migration
rebuilds the table additively with identical columns and a wider stance check.
Existing rows are copied unchanged; append-only triggers are restored.
"""

from __future__ import annotations

import sqlite3

_EXPANDED_STANCES = (
    "supports",
    "contradicts",
    "neutral",
    "context",
    "resolution_rule",
    "official_source",
    "stale",
    "missing",
    "redacted",
    "sensitive",
)


def _migration_017_expanded_source_stances(conn: sqlite3.Connection) -> None:
    """Rebuild ``sources`` with the expanded stance CHECK constraint."""

    stance_sql = ",".join(f"'{stance}'" for stance in _EXPANDED_STANCES)
    conn.execute("DROP TRIGGER IF EXISTS trg_sources_no_update")
    conn.execute("DROP TRIGGER IF EXISTS trg_sources_no_delete")
    conn.execute("ALTER TABLE sources RENAME TO sources__m017_old")
    conn.execute(
        f"""
        CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN
                ('url','pdf','image','tweet','news_article','research_doc',
                 'transcript','chart_image','note','other')),
            ref TEXT,
            title TEXT,
            note TEXT,
            stance TEXT NOT NULL DEFAULT 'neutral'
                CHECK (stance IN ({stance_sql})),
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
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO sources(
            id, kind, ref, title, note, stance, freshness_at, content_hash,
            captured_at, uri, media_type, storage_kind, retrieved_at,
            source_author, publisher, excerpt, extracted_text, summary,
            hash_algorithm, redaction_status, license_or_terms_note,
            metadata_json, created_at, actor_id, agent_id, model_id,
            environment, run_id
        )
        SELECT
            id, kind, ref, title, note, stance, freshness_at, content_hash,
            captured_at, uri, media_type, storage_kind, retrieved_at,
            source_author, publisher, excerpt, extracted_text, summary,
            hash_algorithm, redaction_status, license_or_terms_note,
            metadata_json, created_at, actor_id, agent_id, model_id,
            environment, run_id
        FROM sources__m017_old
        """
    )
    conn.execute("DROP TABLE sources__m017_old")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sources_agent_run
        ON sources(agent_id, model_id, environment, run_id)
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_sources_no_update
        BEFORE UPDATE ON sources
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: UPDATE on sources is forbidden; use a supersedes edge to record a correction (persistence.md §8)');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_sources_no_delete
        BEFORE DELETE ON sources
        BEGIN
            SELECT RAISE(ABORT, 'append-only invariant: DELETE on sources is forbidden (persistence.md §8)');
        END
        """
    )


__all__ = ["_migration_017_expanded_source_stances"]
