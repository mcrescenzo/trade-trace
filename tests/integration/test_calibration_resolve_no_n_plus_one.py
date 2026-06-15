"""Regression coverage for trade-trace-u7j3.

`_resolve_p_yes_and_y` used to fire two SELECTs per scored row (one against
`forecast_outcomes WHERE forecast_id = ?`, one against `forecasts WHERE id =
?`). The fix adds `f.probability` to the parent SELECT and bulk-fetches every
forecast's `forecast_outcomes` rows in a single IN-list query before the loop.

These tests pin two things that together make the optimization safe to land:

1. **Output is unchanged.** The fast-path / legacy-path resolution still
   produces byte-for-byte identical `p_yes`/`y` and identical report metrics,
   compared against a reference computed via the original per-row two-query
   `_resolve_p_yes_and_y` calls.
2. **The N+1 is gone.** Loading N scored rows fires zero per-row
   `WHERE forecast_id = ?` / `WHERE id = ?` lookups and at most one bulk
   `WHERE forecast_id IN (...)` query, regardless of N.
"""

from __future__ import annotations

import sqlite3
from itertools import count
from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.mcp_server import mcp_call
from trade_trace.reports import calibration as calib
from trade_trace.reports import compare as cmp_mod
from trade_trace.reports.calibration import _load_scored_rows, _resolve_p_yes_and_y
from trade_trace.reports.compare import _load_grouped_scored_rows
from trade_trace.storage.paths import db_path

_SEED_COUNTER = count(1)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


def _seed_one_scored_forecast(
    home: Path, *, p_yes: float, resolved_label: str = "yes",
    yes_label: str = "yes",
) -> str:
    """Resolve one forecast end-to-end via the public surface. Returns the
    forecast_id. Mirrors test_report_calibration._seed_one_scored_forecast."""

    seed = next(_SEED_COUNTER)
    venue = _envelope(home, "venue.add", {
        "name": f"PM {seed}", "kind": "prediction_market",
        "idempotency_key": f"test:u7j3-venue-{seed}",
    })
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": f"X {seed}",
        "idempotency_key": f"test:u7j3-instrument-{seed}",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
        "idempotency_key": f"test:u7j3-thesis-{seed}",
    })
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": yes_label,
        "idempotency_key": f"test:u7j3-forecast-{seed}",
        "outcomes": [
            {"outcome_label": yes_label, "probability": p_yes},
            {"outcome_label": "no", "probability": 1.0 - p_yes},
        ],
    })
    _envelope(home, "resolution.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": resolved_label, "status": "resolved_final",
        "confidence": 0.99,
        "idempotency_key": f"test:u7j3-outcome-{seed}",
    })
    return f["data"]["id"]


class _QueryTrace:
    """Capture every SQL statement a connection executes via the sqlite trace
    callback, so a test can assert the N+1 per-row pattern is absent."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, sql: str) -> None:
        self.statements.append(" ".join(sql.split()))

    def count_substr(self, needle: str) -> int:
        return sum(1 for s in self.statements if needle in s)


def _seed_n(home: Path, n: int) -> None:
    for i in range(n):
        # alternate resolved label so both y=1 and y=0 are represented
        _seed_one_scored_forecast(
            home, p_yes=0.6 if i % 2 == 0 else 0.3,
            resolved_label="yes" if i % 3 else "no",
        )


def test_load_scored_rows_has_no_per_row_queries(home):
    _seed_n(home, 6)
    with sqlite3.connect(db_path(home)) as conn:
        trace = _QueryTrace()
        conn.set_trace_callback(trace)
        rows = _load_scored_rows(conn, ReportFilter.model_validate({}))
        conn.set_trace_callback(None)

    assert len(rows) >= 6
    # No per-row forecast_outcomes lookup keyed by a single forecast_id.
    assert trace.count_substr("forecast_outcomes WHERE forecast_id = ?") == 0
    # No per-row canonical-probability lookup keyed by a single forecast id.
    assert trace.count_substr("FROM forecasts WHERE id = ?") == 0
    # At most one bulk IN-list fetch of forecast_outcomes for the whole set.
    assert trace.count_substr("forecast_outcomes WHERE forecast_id IN") == 1


def test_load_grouped_scored_rows_has_no_per_row_queries(home):
    _seed_n(home, 6)
    with sqlite3.connect(db_path(home)) as conn:
        trace = _QueryTrace()
        conn.set_trace_callback(trace)
        grouped = list(
            _load_grouped_scored_rows(
                conn, ReportFilter.model_validate({}),
                cmp_mod.CALIBRATION_GROUP_SQL["instrument_id"],
            )
        )
        conn.set_trace_callback(None)

    assert len(grouped) >= 6
    assert trace.count_substr("forecast_outcomes WHERE forecast_id = ?") == 0
    assert trace.count_substr("FROM forecasts WHERE id = ?") == 0
    assert trace.count_substr("forecast_outcomes WHERE forecast_id IN") == 1


def test_query_count_does_not_grow_with_n(home):
    """The whole point: query count is independent of row count. Doubling the
    scored-row population must not double (or otherwise scale) the number of
    statements `_load_scored_rows` issues."""

    _seed_n(home, 3)
    with sqlite3.connect(db_path(home)) as conn:
        trace_small = _QueryTrace()
        conn.set_trace_callback(trace_small)
        _load_scored_rows(conn, ReportFilter.model_validate({}))
        conn.set_trace_callback(None)
    small = len(trace_small.statements)

    _seed_n(home, 9)  # population now 12
    with sqlite3.connect(db_path(home)) as conn:
        trace_big = _QueryTrace()
        conn.set_trace_callback(trace_big)
        _load_scored_rows(conn, ReportFilter.model_validate({}))
        conn.set_trace_callback(None)
    big = len(trace_big.statements)

    # Constant query count (the parent SELECT + one bulk fetch) — not O(N).
    assert small == big


def _reference_resolution(conn: sqlite3.Connection, forecast_id: str,
                          yes_label: str | None, outcome_label: str | None):
    """Resolve p_yes/y using the original two-query path (no pre-fetched
    canonical probability / outcome rows), to prove the fast path is identical."""

    return _resolve_p_yes_and_y(
        conn, forecast_id=forecast_id, yes_label=yes_label,
        outcome_label=outcome_label,
    )


def test_fast_path_pyes_y_identical_to_legacy_two_query_path(home):
    _seed_n(home, 6)
    with sqlite3.connect(db_path(home)) as conn:
        rows = _load_scored_rows(conn, ReportFilter.model_validate({}))
        # Build a reference (forecast_id -> (p_yes, y)) from the original
        # per-row two-query resolution.
        for r in rows:
            yes_label, outcome_label = conn.execute(
                """
                SELECT f.yes_label, o.outcome_label
                FROM forecast_scores fs
                JOIN forecasts f ON f.id = fs.forecast_id
                JOIN outcomes o ON o.id = fs.outcome_id
                WHERE fs.id = ?
                """,
                (r.score_id,),
            ).fetchone()
            ref_p, ref_y = _reference_resolution(
                conn, r.forecast_id, yes_label, outcome_label,
            )
            assert r.p_yes == pytest.approx(ref_p)
            assert r.y == ref_y


def test_report_metrics_unchanged_after_n_plus_one_fix(home):
    """End-to-end: the public report metrics must equal a brier computed by
    hand from the known seeded p_yes/y pairs."""

    # p=0.6,y=1 -> 0.16 ; p=0.6,y=1 -> 0.16 ; p=0.3,y=0 -> 0.09
    _seed_one_scored_forecast(home, p_yes=0.6, resolved_label="yes")
    _seed_one_scored_forecast(home, p_yes=0.6, resolved_label="yes")
    _seed_one_scored_forecast(home, p_yes=0.3, resolved_label="no")
    env = _envelope(home, "report.calibration", {})
    data = env["data"]
    expected_brier = (0.16 + 0.16 + 0.09) / 3
    # The report rounds metrics to 6 decimals; compare at that resolution.
    assert data["summary"]["metrics"]["brier"] == pytest.approx(expected_brier, abs=5e-7)
    assert data["summary"]["sample_size"] == 3


def test_canonical_fast_path_zero_extra_queries_when_probability_present(home):
    """When `forecasts.probability` (canonical) is set — the common case — the
    per-row resolution path must touch the DB zero times beyond the parent
    SELECT + the single bulk outcomes fetch."""

    fid = _seed_one_scored_forecast(home, p_yes=0.7, resolved_label="yes")
    with sqlite3.connect(db_path(home)) as conn:
        canonical = conn.execute(
            "SELECT probability FROM forecasts WHERE id = ?", (fid,),
        ).fetchone()[0]
        assert canonical == pytest.approx(0.7)
        trace = _QueryTrace()
        conn.set_trace_callback(trace)
        rows = _load_scored_rows(conn, ReportFilter.model_validate({}))
        conn.set_trace_callback(None)
    assert len(rows) == 1
    assert rows[0].p_yes == pytest.approx(0.7)
    # Exactly: parent SELECT (1) + bulk forecast_outcomes IN-list (1).
    assert len(trace.statements) == 2


def test_calib_module_exposes_bulk_helper():
    """The bulk-fetch helper is the shared seam all three callers import."""

    assert hasattr(calib, "_bulk_fetch_forecast_outcomes")
    assert hasattr(calib, "_resolve_p_yes_and_y_from_data")
