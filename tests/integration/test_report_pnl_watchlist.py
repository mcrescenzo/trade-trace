"""`report.pnl` + `report.watchlist` per trade-trace-nxn."""

from __future__ import annotations

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


# -- report.pnl ------------------------------------------------------


def test_pnl_registered():
    assert "report.pnl" in default_registry().names()


def test_pnl_empty_db(home):
    env = _envelope(home, "report.pnl", {})
    assert env["ok"] is True
    assert env["data"]["summary"]["metrics"]["closed_position_count"] == 0


def test_pnl_rolls_up_positions(home):
    """Inject a closed position via the projection rebuild path so we
    exercise the same code reports consume in production."""

    from trade_trace.tools._helpers import new_id

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    instrument_id = inst["data"]["id"]
    position_id = new_id("pos")
    db = open_database(db_path(home))
    try:
        with db.transaction():
            db.connection.execute(
                "INSERT INTO position_events(id, position_id, instrument_id, "
                "event_type, quantity_delta, price, fees, slippage, created_at, "
                "actor_id) VALUES (?, ?, ?, 'open', 100, 0.40, 0.5, 0, ?, ?)",
                (new_id("pev"), position_id, instrument_id,
                 "2026-05-18T14:00:00Z", "agent:default"),
            )
            db.connection.execute(
                "INSERT INTO position_events(id, position_id, instrument_id, "
                "event_type, quantity_delta, price, fees, slippage, created_at, "
                "actor_id) VALUES (?, ?, ?, 'close', -100, 0.60, 0.5, 0, ?, ?)",
                (new_id("pev"), position_id, instrument_id,
                 "2026-05-18T16:00:00Z", "agent:default"),
            )
    finally:
        db.close()
    _envelope(home, "journal.rebuild_projections", {"projection": "positions"})

    env = _envelope(home, "report.pnl", {})
    summary = env["data"]["summary"]["metrics"]
    assert summary["closed_position_count"] == 1
    # signed-qty convention: positive cumulative qty is long exposure and
    # close fills have the opposite sign. A profitable long close is positive:
    # realized = (0.60 - 0.40) * abs(-100) - 0.5 = 19.5
    assert summary["realized_pnl"] == pytest.approx(19.5, rel=1e-3)


def test_pnl_open_mark_coverage_counts_only_open_positions(home):
    """Closed positions do not need marks, so they must not depress the
    open-position mark coverage denominator. One of two open positions has
    unrealized_pnl, therefore coverage is 1 / 2 regardless of closed rows.
    """

    venue = _envelope(home, "venue.add", {
        "name": "PM-Coverage", "kind": "prediction_market"
    })
    instruments = [
        _envelope(home, "instrument.add", {
            "venue_id": venue["data"]["id"],
            "asset_class": "prediction_market",
            "title": f"Coverage {idx}",
        })["data"]["id"]
        for idx in range(3)
    ]
    db = open_database(db_path(home))
    try:
        with db.transaction():
            rows = [
                ("pos_closed_a", instruments[0], "closed", 12.0, None),
                ("pos_closed_b", instruments[0], "closed", -2.0, None),
                ("pos_open_marked", instruments[1], "open", None, 3.5),
                ("pos_open_unmarked", instruments[2], "open", None, None),
            ]
            for pos_id, instrument_id, status, realized, unrealized in rows:
                db.connection.execute(
                    "INSERT INTO positions(id, instrument_id, kind, side, "
                    "status, opened_at, closed_at, resolved_at, realized_pnl, "
                    "unrealized_pnl, avg_entry_price, updated_at) VALUES "
                    "(?, ?, 'paper', 'long', ?, '2026-05-18T14:00:00Z', "
                    "NULL, NULL, ?, ?, 0.40, '2026-05-18T16:00:00Z')",
                    (pos_id, instrument_id, status, realized, unrealized),
                )
    finally:
        db.close()

    env = _envelope(home, "report.pnl", {})
    assert env["ok"], env
    metrics = env["data"]["summary"]["metrics"]
    assert metrics["closed_position_count"] == 2
    assert metrics["open_position_count"] == 2
    assert metrics["open_mark_coverage"] == pytest.approx(0.5)
    assert "data_coverage" not in metrics


# -- report.watchlist ---------------------------------------------


def test_watchlist_registered():
    assert "report.watchlist" in default_registry().names()


def test_watchlist_empty_db(home):
    env = _envelope(home, "report.watchlist", {})
    assert env["ok"] is True
    assert env["data"]["summary"]["metrics"]["watch_count"] == 0


def test_watchlist_lists_watch_decisions(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "watch",
        "reason": "monitor levels",
    })
    env = _envelope(home, "report.watchlist", {})
    assert env["data"]["summary"]["metrics"]["watch_count"] == 1
    assert env["data"]["groups"][0]["label"].startswith("watch on")


def test_watchlist_mode_validation(home):
    env = _envelope(home, "report.watchlist", {"mode": "active"})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_watchlist_uses_single_clock_instant_for_as_of_age_and_stale(home, monkeypatch):
    """Per bead trade-trace-bew / DEBT-026: report.watchlist must
    capture one clock instant at entry and reuse it for the stale
    threshold, every row's age_days, and the response's `as_of`
    field. Previously each computation read the wall clock
    independently, so a microsecond-boundary read could flake the
    exact-threshold tests.

    Implementation note: the report calls `now_iso()` (which honors
    the CLOCK_OVERRIDE deterministic-replay fixture) and converts
    to a datetime once. The test patches `now_iso` to count calls.
    """

    import trade_trace.reports.watchlist as wl

    call_count = [0]
    real_now_iso = wl.now_iso

    def _counting_now_iso() -> str:
        call_count[0] += 1
        return real_now_iso()

    monkeypatch.setattr(wl, "now_iso", _counting_now_iso)

    env = _envelope(home, "report.watchlist", {"mode": "stale"})
    assert env["ok"], env

    assert call_count[0] == 1, (
        f"watchlist read the wall clock {call_count[0]} times; per "
        "bead bew it must capture one instant at entry"
    )


def test_watchlist_stale_mode_filters_by_age(home):
    """A fresh watch (created just now) is NOT stale; the stale filter
    returns an empty list."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "watch", "reason": "y",
    })
    env = _envelope(home, "report.watchlist", {"mode": "stale", "stale_threshold_days": 14})
    assert env["data"]["summary"]["metrics"]["watch_count"] == 0
    # All-mode still surfaces it.
    env_all = _envelope(home, "report.watchlist", {})
    assert env_all["data"]["summary"]["metrics"]["watch_count"] == 1


# -- watch + review_by per beads trade-trace-gbtj / trade-trace-sjz6 -----


def test_watch_decision_accepts_review_by(home):
    """Watches now accept first-class `review_by` so agents can schedule
    a deferred review without burying the date in metadata."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    env = _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"],
        "type": "watch",
        "review_by": "2026-06-18T00:00:00.000Z",
        "reason": "revisit after CPI",
    })
    assert env["ok"], env
    # The decision is persisted with the normalized review_by timestamp.
    assert env["data"]["review_by"].startswith("2026-06-18")


def test_watch_decision_still_optional(home):
    """`review_by` remains optional for watch — omitting it is still valid."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    env = _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"],
        "type": "watch",
        "reason": "monitor",
    })
    assert env["ok"], env
    # `exclude_none=True` strips the field; either absence or None is fine.
    assert env["data"].get("review_by") is None


def test_watchlist_surfaces_review_by_and_overdue_flag(home):
    """A watch with `review_by <= as_of` is flagged `overdue=True`; one
    without `review_by` or with a future `review_by` is `overdue=False`.
    The summary echoes the overdue_count."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    # 1. Overdue watch — review_by in the deep past.
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "watch",
        "review_by": "2024-01-01T00:00:00.000Z",
        "reason": "overdue",
    })
    # 2. Not-yet-due watch — review_by far in the future.
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "watch",
        "review_by": "2030-01-01T00:00:00.000Z",
        "reason": "future",
    })
    # 3. Watch without review_by.
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "watch",
        "reason": "no schedule",
    })

    env = _envelope(home, "report.watchlist", {})
    assert env["ok"], env
    assert env["data"]["summary"]["metrics"]["watch_count"] == 3
    assert env["data"]["summary"]["metrics"]["overdue_count"] == 1

    # Each row carries an `overdue` flag in its metrics.
    by_reason = {
        g["examples"][0]["summary"]: g["metrics"]
        for g in env["data"]["groups"]
    }
    assert by_reason["overdue"]["overdue"] is True
    assert by_reason["future"]["overdue"] is False
    assert by_reason["no schedule"]["overdue"] is False
    # review_by is preserved on every row (None when not set).
    assert by_reason["overdue"]["review_by"].startswith("2024-01-01")
    assert by_reason["future"]["review_by"].startswith("2030-01-01")
    assert by_reason["no schedule"]["review_by"] is None


def test_watch_decision_add_review_by_validates_iso():
    """An ill-formed `review_by` for a watch returns VALIDATION_ERROR on
    `field='review_by'` — same path used by `type='review'`."""

    import tempfile
    from pathlib import Path as P

    from trade_trace.mcp_server import mcp_call

    with tempfile.TemporaryDirectory() as tmp:
        h = P(tmp) / "home"
        mcp_call("journal.init", {"home": str(h)})
        venue = mcp_call(
            "venue.add", {"home": str(h), "name": "PM", "kind": "prediction_market"},
            actor_id="agent:default",
        ).model_dump(mode="json")
        inst = mcp_call(
            "instrument.add", {
                "home": str(h), "venue_id": venue["data"]["id"],
                "asset_class": "prediction_market", "title": "X",
            },
            actor_id="agent:default",
        ).model_dump(mode="json")
        env = mcp_call(
            "decision.add", {
                "home": str(h), "instrument_id": inst["data"]["id"],
                "type": "watch", "review_by": "not-a-timestamp",
            },
            actor_id="agent:default",
        ).model_dump(mode="json", exclude_none=True)
        assert env["ok"] is False
        assert env["error"]["details"]["field"] == "review_by"
