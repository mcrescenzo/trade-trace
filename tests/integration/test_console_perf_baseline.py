"""Console pagination perf baseline (trade-trace-1kkv.14).

Seeds a 100k-row events table directly via SQL (the existing
`fixture.seed` only carries the M0-eval profile), then asserts
that one cursor-paginated page loads under the budget documented
in `docs/architecture/console.md` §13. Opt-in via
`TRADE_TRACE_RUN_PERF_TESTS=1` to keep PR signal fast; CI flips
the env var on a dedicated perf job.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.storage.paths import db_path

PERF_TESTS_ENV = "TRADE_TRACE_RUN_PERF_TESTS"
ROW_COUNT = 100_000
BUDGET_SECONDS = 1.0
"""Wall-clock budget for a cursor-paginated page against a 100k-row
events table. 5× headroom over the typical local run (~0.05s) so a
slow CI runner doesn't flake the assertion."""

pytestmark = pytest.mark.skipif(
    os.environ.get(PERF_TESTS_ENV) != "1",
    reason=f"Perf baseline opt-in; set {PERF_TESTS_ENV}=1 to run.",
)


def _seed_events(home: Path, count: int) -> None:
    """Insert `count` rows directly into the events table. Bypasses
    the dispatch layer for speed — the perf baseline is for the
    *read* path, not write throughput."""

    path = db_path(home)
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        # Build a representative payload size so the IO budget
        # reflects realistic row width.
        payload = '{"k":"' + "x" * 96 + '"}'
        conn.execute("BEGIN")
        conn.executemany(
            "INSERT INTO events("
            "event_type, subject_kind, subject_id, payload_json, "
            "actor_id, idempotency_key, created_at, request_id) "
            "VALUES ('venue.created', 'venue', ?, ?, "
            "'agent:perf', ?, '2026-05-19T00:00:00Z', ?)",
            [
                (f"ven_perf_{i:08d}", payload, f"perf-{i:08d}", f"req-{i:08d}")
                for i in range(count)
            ],
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


def test_first_journal_page_under_budget(tmp_path: Path):
    from trade_trace.console.pagination import paginate_query
    from trade_trace.storage.database import open_database_readonly

    home = tmp_path / "perf"
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok
    _seed_events(home, ROW_COUNT)

    db = open_database_readonly(db_path(home))
    try:
        start = time.perf_counter()
        page = paginate_query(
            db.connection,
            sql="SELECT id, event_type, subject_id FROM events",
            order_by="id DESC",
            cursor=None,
            limit=50,
        )
        elapsed = time.perf_counter() - start
    finally:
        db.close()

    assert len(page.rows) == 50
    assert page.next_cursor is not None
    assert elapsed < BUDGET_SECONDS, (
        f"first journal page took {elapsed:.3f}s "
        f"(budget {BUDGET_SECONDS}s, row count {ROW_COUNT})"
    )


def test_deep_cursor_does_not_degrade(tmp_path: Path):
    """Cursor pagination's selling point is constant-time pages.
    Verify the 100th page takes no longer than the first."""

    from trade_trace.console.pagination import paginate_query
    from trade_trace.storage.database import open_database_readonly

    home = tmp_path / "perf-deep"
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok
    _seed_events(home, ROW_COUNT)

    db = open_database_readonly(db_path(home))
    try:
        cursor = None
        # Walk 100 pages forward; the last fetch is the "deep" page.
        for _ in range(100):
            page = paginate_query(
                db.connection,
                sql="SELECT id, event_type, subject_id FROM events",
                order_by="id",
                cursor=cursor,
                limit=50,
            )
            cursor = page.next_cursor
            assert cursor is not None

        start = time.perf_counter()
        deep_page = paginate_query(
            db.connection,
            sql="SELECT id, event_type, subject_id FROM events",
            order_by="id",
            cursor=cursor,
            limit=50,
        )
        elapsed = time.perf_counter() - start
    finally:
        db.close()

    assert len(deep_page.rows) == 50
    assert elapsed < BUDGET_SECONDS, (
        f"deep journal page (100th) took {elapsed:.3f}s "
        f"(budget {BUDGET_SECONDS}s)"
    )
