"""Console reporting read model contract tests per trade-trace-bbww.

The read model lives in `src/trade_trace/console/reporting/`. The
shipped Console UI consumes the Trades index and Position detail pages;
`trade_detail` remains an exported external Python read-model helper,
not a Console HTTP/UI route. These tests pin the row shape, the
pagination contract, and the missing-data caveat surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import trade_trace.console.reporting as reporting
from trade_trace.console.reporting import (
    CAVEAT_OPEN_NO_MARK,
    PositionDetail,
    TradeRow,
    list_trades,
    position_detail,
    trade_detail,
)
from trade_trace.console.reporting.trade_rows import (
    CAVEAT_MISSING_RISK_BUDGET,
    TRADING_DECISION_TYPES,
)
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


@pytest.fixture
def rich_home(tmp_path: Path) -> Path:
    """Fresh home seeded with mvp-eval-rich so the read model has the
    full lifecycle coverage (winners/losers/breakevens + open marked/
    unmarked + risk-budget mix)."""

    home = tmp_path / "rich"
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok, init
    seed = mcp_call("journal.fixture_seed", {
        "home": str(home), "target": "mvp-eval-rich",
    })
    assert seed.ok, seed
    return home


# -- list_trades -----------------------------------------------------


def test_list_trades_returns_only_trading_decision_types(rich_home: Path) -> None:
    db = open_database(db_path(rich_home), create_parent=False)
    try:
        page = list_trades(db.connection, limit=500)
    finally:
        db.close()
    assert page.rows, "rich fixture must produce trade rows"
    for r in page.rows:
        assert isinstance(r, TradeRow)
        assert r.decision_type in TRADING_DECISION_TYPES, (
            f"non-trading decision_type {r.decision_type!r} leaked into list_trades"
        )


def test_list_trades_pagination_yields_next_cursor_and_stable_walk(rich_home: Path) -> None:
    db = open_database(db_path(rich_home), create_parent=False)
    try:
        all_rows = list_trades(db.connection, limit=500).rows
        first = list_trades(db.connection, limit=2)
    finally:
        db.close()

    assert len(first.rows) == 2
    assert first.next_cursor is not None, "expect next_cursor when more rows remain"

    seen_ids: list[str] = [r.decision_id for r in first.rows]
    cursor = first.next_cursor
    while cursor is not None:
        db = open_database(db_path(rich_home), create_parent=False)
        try:
            page = list_trades(db.connection, limit=2, cursor=cursor)
        finally:
            db.close()
        for r in page.rows:
            assert r.decision_id not in seen_ids, (
                "cursor walk surfaced a duplicate row"
            )
            seen_ids.append(r.decision_id)
        cursor = page.next_cursor

    assert sorted(seen_ids) == sorted(r.decision_id for r in all_rows)


def test_list_trades_strategy_filter_narrows_results(rich_home: Path) -> None:
    db = open_database(db_path(rich_home), create_parent=False)
    try:
        strat_row = db.connection.execute(
            "SELECT id FROM strategies WHERE slug = 'rich-only-n1'",
        ).fetchone()
        assert strat_row is not None, "fixture must include rich-only-n1 strategy"
        strategy_id = strat_row[0]
        page = list_trades(db.connection, strategy_id=strategy_id, limit=100)
        all_trades = list_trades(db.connection, limit=500).rows
    finally:
        db.close()

    assert all(r.strategy_id == strategy_id for r in page.rows)
    assert len(page.rows) < len(all_trades), (
        "narrowing to one strategy must return strictly fewer rows"
    )


def test_list_trades_decision_type_filter_excludes_non_trading_types(rich_home: Path) -> None:
    """Passing a non-trading type returns an empty page rather than
    raising — keeps the caller filter loop simple."""

    db = open_database(db_path(rich_home), create_parent=False)
    try:
        page = list_trades(db.connection, decision_type="watch", limit=10)
    finally:
        db.close()
    assert page.rows == []
    assert page.next_cursor is None


def test_list_trades_includes_missing_data_caveats(rich_home: Path) -> None:
    """mvp-eval-rich has trades with and without declared_risk_amount.
    Every trade missing risk must surface CAVEAT_MISSING_RISK_BUDGET."""

    db = open_database(db_path(rich_home), create_parent=False)
    try:
        page = list_trades(db.connection, limit=500)
    finally:
        db.close()

    with_risk = [r for r in page.rows if r.declared_risk_amount is not None]
    without_risk = [r for r in page.rows if r.declared_risk_amount is None]
    assert with_risk, "fixture must include at least one trade with declared risk"
    assert without_risk, "fixture must include at least one trade without declared risk"

    for r in with_risk:
        assert CAVEAT_MISSING_RISK_BUDGET not in r.caveats
    for r in without_risk:
        assert CAVEAT_MISSING_RISK_BUDGET in r.caveats


# -- trade_detail ----------------------------------------------------


def test_trade_detail_remains_exported_python_read_model_api() -> None:
    assert reporting.trade_detail is trade_detail


def test_trade_detail_returns_named_decision(rich_home: Path) -> None:
    db = open_database(db_path(rich_home), create_parent=False)
    try:
        page = list_trades(db.connection, limit=1)
        target = page.rows[0]
        detail = trade_detail(db.connection, target.decision_id)
    finally:
        db.close()
    assert detail is not None
    assert detail.decision_id == target.decision_id


def test_trade_detail_returns_none_for_unknown_id(rich_home: Path) -> None:
    db = open_database(db_path(rich_home), create_parent=False)
    try:
        assert trade_detail(db.connection, "dec_does_not_exist") is None
    finally:
        db.close()


def test_trade_detail_returns_none_for_non_trading_decision(rich_home: Path) -> None:
    """A `watch` decision id MUST return None — list_trades excludes
    them, and detail must agree."""

    db = open_database(db_path(rich_home), create_parent=False)
    try:
        watch_id = db.connection.execute(
            "SELECT id FROM decisions WHERE type = 'watch' LIMIT 1",
        ).fetchone()[0]
        assert trade_detail(db.connection, watch_id) is None
    finally:
        db.close()


# -- position_detail -------------------------------------------------


def test_position_detail_open_unmarked_surfaces_open_no_mark_caveat(rich_home: Path) -> None:
    db = open_database(db_path(rich_home), create_parent=False)
    try:
        unmarked_rows = db.connection.execute(
            "SELECT id FROM positions "
            "WHERE status = 'open' AND unrealized_pnl IS NULL",
        ).fetchall()
        assert unmarked_rows, "fixture must include >= 1 unmarked open position"
        pid = unmarked_rows[0][0]
        detail = position_detail(db.connection, pid)
    finally:
        db.close()
    assert isinstance(detail, PositionDetail)
    assert detail.status == "open"
    assert detail.unrealized_pnl is None
    assert CAVEAT_OPEN_NO_MARK in detail.caveats


def test_position_detail_open_marked_does_not_surface_open_no_mark_caveat(rich_home: Path) -> None:
    db = open_database(db_path(rich_home), create_parent=False)
    try:
        marked_rows = db.connection.execute(
            "SELECT id FROM positions "
            "WHERE status = 'open' AND unrealized_pnl IS NOT NULL",
        ).fetchall()
        assert marked_rows, "fixture must include >= 1 marked open position"
        pid = marked_rows[0][0]
        detail = position_detail(db.connection, pid)
    finally:
        db.close()
    assert detail is not None
    assert detail.status == "open"
    assert detail.unrealized_pnl is not None
    assert CAVEAT_OPEN_NO_MARK not in detail.caveats


def test_position_detail_closed_position_carries_realized_pnl(rich_home: Path) -> None:
    db = open_database(db_path(rich_home), create_parent=False)
    try:
        closed_row = db.connection.execute(
            "SELECT id FROM positions WHERE status = 'closed' LIMIT 1",
        ).fetchone()
        assert closed_row is not None
        detail = position_detail(db.connection, closed_row[0])
    finally:
        db.close()
    assert detail is not None
    assert detail.status == "closed"
    assert detail.closed_at is not None
    # All closed positions in the rich fixture either won, lost, or
    # broke even; only the breakeven row may have realized_pnl == None.
    assert detail.realized_pnl is None or isinstance(detail.realized_pnl, float)


def test_position_detail_returns_none_for_unknown_id(rich_home: Path) -> None:
    db = open_database(db_path(rich_home), create_parent=False)
    try:
        assert position_detail(db.connection, "pos_does_not_exist") is None
    finally:
        db.close()


def test_position_detail_includes_event_lineage(rich_home: Path) -> None:
    db = open_database(db_path(rich_home), create_parent=False)
    try:
        closed_row = db.connection.execute(
            "SELECT id FROM positions WHERE status = 'closed' LIMIT 1",
        ).fetchone()
        detail = position_detail(db.connection, closed_row[0])
    finally:
        db.close()
    assert detail is not None
    assert len(detail.events) >= 2, "closed positions need at least open+close events"
    # Lineage is chronological.
    timestamps = [ev.created_at for ev in detail.events]
    assert timestamps == sorted(timestamps), "events must be chronological"
