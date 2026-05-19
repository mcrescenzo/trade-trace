"""Edge endpoint enums per PRD §3.2 + 7lo M1 minimal endpoint enum."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests._direct_sql_builders import (
    insert_decision,
    insert_forecast,
    insert_instrument,
    insert_outcome,
    insert_source,
    insert_thesis,
    insert_venue,
)
from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path


def _db(tmp_path: Path):
    db = open_database(db_path(tmp_path / "home"))
    apply_pending_migrations(db.connection)
    return db


def _seed_minimal(conn: sqlite3.Connection) -> None:
    """Seed the venues/instruments/theses/forecasts/decisions/outcomes/
    sources subgraph via the shared direct-SQL builders
    (trade-trace-24ia / SIMP-009)."""

    insert_venue(conn)
    insert_instrument(conn)
    insert_thesis(conn, body="thesis body")
    insert_forecast(conn)
    insert_source(conn)
    insert_decision(conn)
    insert_outcome(conn)


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
