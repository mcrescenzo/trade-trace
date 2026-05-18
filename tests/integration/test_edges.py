"""Edge endpoint enums per PRD §3.2 + 7lo M1 minimal endpoint enum."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path


def _db(tmp_path: Path):
    db = open_database(db_path(tmp_path / "home"))
    apply_pending_migrations(db.connection)
    return db


def _seed_minimal(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        INSERT INTO venues(id, name, kind, created_at, actor_id)
            VALUES ('v_1', 'manual', 'manual', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
            VALUES ('i_1', 'v_1', 'Test', 'prediction_market', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO theses(id, instrument_id, side, body, created_at, actor_id)
            VALUES ('t_1', 'i_1', 'yes', 'thesis body', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO forecasts(id, thesis_id, kind, created_at, actor_id)
            VALUES ('f_1', 't_1', 'binary', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO decisions(id, instrument_id, type, created_at, actor_id)
            VALUES ('d_1', 'i_1', 'skip', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO sources(id, kind, created_at, actor_id)
            VALUES ('s_1', 'note', '2026-05-18T14:00:00Z', 'agent:default');
        INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, status, created_at, actor_id)
            VALUES ('o_1', 'i_1', '2026-05-18T14:00:00Z', 'YES', 'resolved_final',
                    '2026-05-18T14:00:00Z', 'agent:default');
        """
    )


M1_EDGE_TYPES = ("about", "supports", "contradicts", "supersedes")
M1_ENDPOINT_KINDS = (
    "decision",
    "thesis",
    "forecast",
    "outcome",
    "snapshot",
    "instrument",
    "venue",
    "source",
    "review",
    "playbook_version",
)


@pytest.mark.parametrize("edge_type", M1_EDGE_TYPES)
def test_m1_edge_types_accepted(tmp_path: Path, edge_type: str):
    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        db.connection.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
            "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"e_{edge_type}", "source", "s_1", "thesis", "t_1", edge_type,
             "2026-05-18T14:00:00Z", "agent:default"),
        )
        row = db.connection.execute(
            "SELECT edge_type FROM edges WHERE id = ?", (f"e_{edge_type}",)
        ).fetchone()
        assert row[0] == edge_type
    finally:
        db.close()


def test_unknown_edge_type_rejected(tmp_path: Path):
    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
                "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("e_bad", "source", "s_1", "thesis", "t_1", "not_a_real_edge_type",
                 "2026-05-18T14:00:00Z", "agent:default"),
            )
    finally:
        db.close()


@pytest.mark.parametrize("kind", M1_ENDPOINT_KINDS)
def test_m1_endpoint_kinds_accepted_in_schema(tmp_path: Path, kind: str):
    """Every M1 endpoint kind is in the CHECK constraint enum.

    Note: this asserts the SCHEMA allows the kind; the application-layer
    endpoint-id validator (which checks the row actually exists with the
    matching kind) is separate work for the M1 write tools (7lo's downstream)."""

    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        # Use 'about' edge to a thesis target (always seeded) and a source row
        # for the source side (we just need the CHECK to pass).
        # For `playbook_version` / `review` we don't have rows in the seed,
        # but the schema accepts the kind on the edge row — that's the test.
        db.connection.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
            "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"e_{kind}", kind, "any-id", "thesis", "t_1", "about",
             "2026-05-18T14:00:00Z", "agent:default"),
        )
    finally:
        db.close()


def test_unknown_endpoint_kind_rejected(tmp_path: Path):
    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
                "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("e_bad", "made_up_endpoint_kind", "x", "thesis", "t_1", "about",
                 "2026-05-18T14:00:00Z", "agent:default"),
            )
    finally:
        db.close()


def test_source_attachment_edge_pattern(tmp_path: Path):
    """The canonical M1 source-attachment pattern: source → target with
    edge_type derived from sources.stance per PRD §4.5."""

    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        # source.attach_to_thesis with stance='supports' →
        # edges(source=source, target=thesis, edge_type='supports')
        db.connection.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
            "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("e_attach", "source", "s_1", "thesis", "t_1", "supports",
             "2026-05-18T14:00:00Z", "agent:default"),
        )
        cur = db.connection.execute(
            "SELECT source_kind, target_kind, edge_type FROM edges WHERE id = 'e_attach'"
        )
        row = cur.fetchone()
        assert row == ("source", "thesis", "supports")
    finally:
        db.close()


def test_outcome_supersedes_edge_pattern(tmp_path: Path):
    """Per PRD §3.1 outcomes: a correction is a new outcome row + a
    supersedes edge (source_kind=outcome, target_kind=outcome)."""

    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        # Append the corrected outcome.
        db.connection.execute(
            "INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, "
            "status, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("o_2", "i_1", "2026-05-18T14:00:00Z", "NO", "resolved_final",
             "2026-05-19T14:00:00Z", "agent:default"),
        )
        db.connection.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
            "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("e_sup", "outcome", "o_2", "outcome", "o_1", "supersedes",
             "2026-05-19T14:00:00Z", "agent:default"),
        )
        # The supersedes edge points new → old, and both rows still exist.
        cur = db.connection.execute(
            "SELECT source_id, target_id FROM edges WHERE edge_type = 'supersedes' AND id = 'e_sup'"
        )
        row = cur.fetchone()
        assert row == ("o_2", "o_1")
    finally:
        db.close()
