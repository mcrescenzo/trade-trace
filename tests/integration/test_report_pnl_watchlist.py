"""`report.pnl` + `report.watchlist` per trade-trace-nxn."""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _envelope(home: Path, tool: str, args: dict):
    payload = {"home": str(home), **args}
    return mcp_call(tool, payload, actor_id="agent:default").model_dump(
        mode="json", exclude_none=True
    )


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
