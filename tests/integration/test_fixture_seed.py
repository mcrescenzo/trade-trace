"""tt fixture seed deterministic-dataset tests per bead trade-trace-8dv."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


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


@pytest.mark.skipif(
    not os.environ.get("TRADE_TRACE_RUN_PERF_TESTS"),
    reason=(
        "Wall-clock perf assertion skipped by default per bead "
        "trade-trace-29u0; set TRADE_TRACE_RUN_PERF_TESTS=1 to opt in "
        "for a perf-only run."
    ),
)
def test_fixture_seed_completes_in_under_five_seconds(home):
    """Bead acceptance: cold-start seed completes in <5s on commodity
    hardware. Generous bound — actual runtime is ~50ms in practice.

    Off by default per bead trade-trace-29u0 / DEBT-034: a wall-clock
    assertion in the default functional suite mixes performance with
    correctness and can produce false failures under constrained
    CI / coverage / virtualized runs. The opt-in env flag lets a
    dedicated perf job run this without contaminating normal pytest.
    """

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


# -- 5. mvp-eval-rich reporting fixture per bead trade-trace-dnwh ---------


def test_fixture_seed_mvp_eval_rich_target_runs(home):
    """`mvp-eval-rich` is the second fixture profile per bead
    trade-trace-dnwh. It extends mvp-eval with traded positions
    (winners/losers/breakevens), open positions with and without
    marks, declared risk amounts, and a low-N strategy — the
    coverage the reporting product overhaul needs to exercise its
    caveat surface."""

    env = mcp_call("journal.fixture_seed", {
        "home": str(home), "target": "mvp-eval-rich",
    })
    assert env.ok, env
    assert env.data["target"] == "mvp-eval-rich"
    assert env.data["counts"]["decisions"] >= 30  # inherits mvp-eval floor


def test_fixture_seed_mvp_eval_rich_creates_closed_and_open_positions(home):
    """The rich fixture must produce a mix of position lifecycle states
    so dashboards can render winners/losers/breakevens AND
    open-with-mark / open-without-mark caveats."""

    env = mcp_call("journal.fixture_seed", {
        "home": str(home), "target": "mvp-eval-rich",
    })
    assert env.ok, env

    db = open_database(db_path(home), create_parent=False)
    try:
        rows = db.connection.execute(
            "SELECT status, realized_pnl, unrealized_pnl FROM positions"
        ).fetchall()
    finally:
        db.close()

    closed = [r for r in rows if r[0] == "closed"]
    open_rows = [r for r in rows if r[0] == "open"]

    assert len(closed) >= 3, (
        f"need >= 3 closed positions for winners/losers/breakeven; "
        f"got {len(closed)}"
    )
    realized = sorted(r[1] for r in closed if r[1] is not None)
    assert realized[0] < 0, f"need a losing closed position; sorted realized: {realized}"
    assert realized[-1] > 0, f"need a winning closed position; sorted realized: {realized}"

    assert len(open_rows) >= 2, (
        f"need >= 2 open positions (with-mark + without-mark); "
        f"got {len(open_rows)}"
    )
    with_mark = [r for r in open_rows if r[2] is not None]
    without_mark = [r for r in open_rows if r[2] is None]
    assert with_mark, "need >= 1 open position WITH a mark"
    assert without_mark, "need >= 1 open position WITHOUT a mark (caveat path)"


def test_fixture_seed_mvp_eval_rich_includes_declared_risk(home):
    """Some decisions must carry declared_risk_amount so report.risk
    can aggregate R-multiples; others must NOT so the missing-risk
    caveat path exercises."""

    env = mcp_call("journal.fixture_seed", {
        "home": str(home), "target": "mvp-eval-rich",
    })
    assert env.ok, env

    db = open_database(db_path(home), create_parent=False)
    try:
        with_risk = db.connection.execute(
            "SELECT COUNT(*) FROM decisions WHERE declared_risk_amount IS NOT NULL"
        ).fetchone()[0]
        without_risk = db.connection.execute(
            "SELECT COUNT(*) FROM decisions WHERE declared_risk_amount IS NULL"
        ).fetchone()[0]
    finally:
        db.close()

    assert with_risk >= 1, "need >= 1 decision with declared_risk_amount"
    assert without_risk >= 1, "need >= 1 decision without declared_risk_amount (caveat path)"


def test_fixture_seed_mvp_eval_rich_is_deterministic(tmp_path):
    """Two fresh runs of mvp-eval-rich must produce byte-identical
    table content (modulo SQLite WAL)."""

    hashes: list[str] = []
    for run in range(2):
        h = tmp_path / f"rich-run-{run}"
        init = mcp_call("journal.init", {"home": str(h)})
        assert init.ok
        env = mcp_call("journal.fixture_seed", {
            "home": str(h), "target": "mvp-eval-rich",
        })
        assert env.ok, env
        hashes.append(_content_hash(h))
    assert hashes[0] == hashes[1], "mvp-eval-rich must be deterministic"
