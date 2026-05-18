"""tt fixture seed deterministic-dataset tests per bead trade-trace-8dv."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _content_hash(home: Path) -> str:
    """Hash the *table content* (not the file) of the journal. Sorted
    rows from each append-only table → SHA-256."""

    sha = hashlib.sha256()
    db = open_database(db_path(home), create_parent=False)
    try:
        for table in (
            "venues", "instruments", "theses", "forecasts",
            "decisions", "outcomes", "memory_nodes", "edges",
            "sources", "strategies", "playbooks", "playbook_versions",
            "decision_playbook_rules", "events",
        ):
            cur = db.connection.execute(
                f"SELECT * FROM {table} ORDER BY id"
            )
            for row in cur.fetchall():
                sha.update(repr(row).encode("utf-8"))
            sha.update(b"|TABLE|")
    finally:
        db.close()
    return sha.hexdigest()


def _row_counts(home: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    db = open_database(db_path(home), create_parent=False)
    try:
        for table in (
            "decisions", "forecasts", "outcomes", "memory_nodes",
            "sources", "strategies", "playbooks", "playbook_versions",
            "decision_playbook_rules",
        ):
            out[table] = db.connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
    finally:
        db.close()
    return out


# -- 1. row-count acceptance --------------------------------


def test_fixture_seed_meets_row_count_floor(home):
    env = mcp_call("journal.fixture_seed", {
        "home": str(home), "target": "mvp-eval",
    })
    assert env.ok, env
    counts = _row_counts(home)
    # Per bead acceptance: ≥30 decisions, ≥10 reflections (subset of
    # memory_nodes node_type='reflection'), ≥5 forecasts, 2 strategies,
    # 1 playbook with 1 version, ≥1 ambiguous/disputed/void outcomes.
    assert counts["decisions"] >= 30
    assert counts["forecasts"] >= 5
    assert counts["strategies"] == 2
    assert counts["playbooks"] == 1
    assert counts["playbook_versions"] == 1
    assert counts["decision_playbook_rules"] == 2
    # Reflections: count rows in memory_nodes with node_type='reflection'.
    db = open_database(db_path(home), create_parent=False)
    try:
        reflection_count = db.connection.execute(
            "SELECT COUNT(*) FROM memory_nodes WHERE node_type='reflection'"
        ).fetchone()[0]
    finally:
        db.close()
    assert reflection_count >= 10


def test_fixture_seed_includes_ambiguous_and_disputed_outcomes(home):
    mcp_call("journal.fixture_seed", {"home": str(home), "target": "mvp-eval"})
    db = open_database(db_path(home), create_parent=False)
    try:
        statuses = [r[0] for r in db.connection.execute(
            "SELECT status FROM outcomes"
        ).fetchall()]
    finally:
        db.close()
    assert "resolved_final" in statuses
    assert "ambiguous" in statuses
    assert "disputed" in statuses
    assert "resolved_provisional" in statuses


def test_fixture_seed_includes_diagnostic_source_fixtures(home):
    mcp_call("journal.fixture_seed", {"home": str(home), "target": "mvp-eval"})
    db = open_database(db_path(home), create_parent=False)
    try:
        sensitive_count = db.connection.execute(
            "SELECT COUNT(*) FROM sources WHERE redaction_status = 'sensitive'"
        ).fetchone()[0]
    finally:
        db.close()
    assert sensitive_count == 1


# -- 2. determinism (3 invocations → identical content hash) -----


def test_fixture_seed_is_byte_deterministic(tmp_path):
    """Three fresh homes seeded under the same clock produce identical
    table content. SHA-256 of sorted-row dumps must match across all
    three runs."""

    hashes: set[str] = set()
    for i in range(3):
        h = tmp_path / f"home-{i}"
        mcp_call("journal.init", {"home": str(h)})
        env = mcp_call("journal.fixture_seed", {
            "home": str(h), "target": "mvp-eval",
        })
        assert env.ok, env
        hashes.add(_content_hash(h))
    assert len(hashes) == 1, f"non-deterministic: {hashes}"


# -- 3. runtime cap ---------------------------------------


def test_fixture_seed_completes_in_under_five_seconds(home):
    """Bead acceptance: cold-start seed completes in <5s on commodity
    hardware. Generous bound — actual runtime is ~50ms in practice."""

    start = time.monotonic()
    env = mcp_call("journal.fixture_seed", {
        "home": str(home), "target": "mvp-eval",
    })
    elapsed = time.monotonic() - start
    assert env.ok
    assert elapsed < 5.0, f"seed too slow: {elapsed:.2f}s"


# -- 4. unknown target rejected ---------------------------


def test_fixture_seed_unknown_target_rejected(home):
    env = mcp_call("journal.fixture_seed", {
        "home": str(home), "target": "made-up-profile",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "target"
