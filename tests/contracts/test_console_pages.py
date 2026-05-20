"""Console page context handlers (trade-trace-1kkv.6/.7/.8/.9).

The handlers in `trade_trace.console.pages` are pure functions
over a read-only SQLite connection. These tests pin the context
shape, empty-state CTA, and pagination conformance without
needing the `[console]` extra installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.storage.paths import db_path


@pytest.fixture
def seeded_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok
    seed = mcp_call(
        "journal.fixture_seed", {"home": str(home), "target": "mvp-eval"},
        actor_id="agent:test",
    )
    assert seed.ok
    return home


@pytest.fixture
def empty_home(tmp_path: Path) -> Path:
    home = tmp_path / "empty"
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok
    return home


@pytest.fixture
def conn(seeded_home: Path):
    from trade_trace.storage.database import open_database_readonly

    db = open_database_readonly(db_path(seeded_home))
    try:
        yield db.connection
    finally:
        db.close()


@pytest.fixture
def empty_conn(empty_home: Path):
    from trade_trace.storage.database import open_database_readonly

    db = open_database_readonly(db_path(empty_home))
    try:
        yield db.connection
    finally:
        db.close()


def test_overview_context_includes_record_counts(conn, seeded_home: Path):
    from trade_trace.console.pages import overview_context

    ctx = overview_context(conn, db_path=db_path(seeded_home))
    assert ctx["page_title"] == "Overview"
    assert ctx["row_counts"]["events"] > 0
    assert ctx["empty_state"] is None


def test_overview_empty_state_offers_concrete_cli_hints(empty_conn, empty_home: Path):
    from trade_trace.console.pages import overview_context

    ctx = overview_context(empty_conn, db_path=db_path(empty_home))
    assert ctx["empty_state"] is not None
    cmds = [cmd for _, cmd in ctx["empty_state"]["next_steps"]]
    assert any("fixture" in c for c in cmds), cmds


def test_journal_context_paginates_with_next_cursor(conn):
    from trade_trace.console.pages import journal_context

    page1 = journal_context(conn, cursor=None, limit=5)
    assert len(page1["rows"]) == 5
    assert page1["next_cursor"] is not None
    page2 = journal_context(conn, cursor=page1["next_cursor"], limit=5)
    assert {r["id"] for r in page1["rows"]}.isdisjoint({r["id"] for r in page2["rows"]})


def test_journal_empty_state_has_seed_hint(empty_conn):
    from trade_trace.console.pages import journal_context

    ctx = journal_context(empty_conn, cursor=None, limit=50)
    assert ctx["empty_state"] is not None
    assert any("fixture" in c for _, c in ctx["empty_state"]["next_steps"])


def test_decisions_context_paginates(conn):
    from trade_trace.console.pages import decisions_context

    ctx = decisions_context(conn, cursor=None, limit=50)
    assert ctx["page_title"] == "Decisions"


def test_decisions_context_consumes_filters(conn):
    from trade_trace.console.pages import decisions_context

    row = conn.execute(
        "SELECT type, instrument_id FROM decisions WHERE instrument_id IS NOT NULL LIMIT 1"
    ).fetchone()
    ctx = decisions_context(
        conn,
        cursor=None,
        limit=50,
        filters={"decision_type": row[0], "instrument_id": row[1]},
    )
    assert ctx["filters"] == {"decision_type": row[0], "instrument_id": row[1]}
    assert ctx["rows"]
    assert all(r["type"] == row[0] and r["instrument_id"] == row[1] for r in ctx["rows"])


def test_decision_detail_returns_none_for_missing_id(conn):
    from trade_trace.console.pages import decision_detail_context

    assert decision_detail_context(conn, decision_id="does-not-exist") is None


def test_decision_detail_returns_row_for_existing_id(conn):
    from trade_trace.console.pages import decision_detail_context

    decision_id = conn.execute("SELECT id FROM decisions LIMIT 1").fetchone()[0]
    ctx = decision_detail_context(conn, decision_id=decision_id)
    assert ctx is not None
    assert ctx["decision"]["id"] == decision_id
    assert "related_events" in ctx


def test_trades_context_lists_trading_decisions_per_q2li(conn):
    """The Trades index page (trade-trace-q2li) surfaces every
    trade-typed decision from `list_trades`. Empty fixture (mvp-eval
    has watch/skip/etc. but few trades) is still a valid response."""

    from trade_trace.console.pages import trades_context

    ctx = trades_context(conn, cursor=None, limit=50)
    assert ctx["page_title"] == "Trades"
    assert "rows" in ctx
    # Every row carries the caveat list (possibly empty).
    for row in ctx["rows"]:
        assert "caveats" in row
        assert "decision_id" in row
        assert "decision_type" in row


def test_trades_context_against_rich_fixture_includes_caveats(tmp_path: Path):
    """With mvp-eval-rich seeded, the Trades index must surface rows
    AND attach the named caveats to rows missing data."""

    from trade_trace.console.pages import trades_context
    from trade_trace.storage.database import open_database_readonly

    home = tmp_path / "rich"
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok
    seed = mcp_call(
        "journal.fixture_seed", {"home": str(home), "target": "mvp-eval-rich"},
        actor_id="agent:test",
    )
    assert seed.ok

    db = open_database_readonly(db_path(home))
    try:
        ctx = trades_context(db.connection, cursor=None, limit=500)
    finally:
        db.close()

    assert ctx["rows"], "rich fixture must produce trade rows"
    with_risk = [r for r in ctx["rows"] if r["declared_risk_amount"] is not None]
    without_risk = [r for r in ctx["rows"] if r["declared_risk_amount"] is None]
    assert with_risk
    assert without_risk
    # Caveat chip data shape: missing-risk rows carry the code.
    assert any("missing_risk_budget" in r["caveats"] for r in without_risk)


def test_trades_context_filter_narrows_results(conn):
    from trade_trace.console.pages import trades_context

    ctx_all = trades_context(conn, cursor=None, limit=500)
    # `watch` is not a trading type — must return zero rows.
    ctx_watch = trades_context(conn, cursor=None, limit=500, decision_type="watch")
    assert ctx_watch["rows"] == []
    assert ctx_watch["filters"]["decision_type"] == "watch"
    # And the empty filter must not include `watch` rows from the all-types page.
    assert all(r["decision_type"] != "watch" for r in ctx_all["rows"])


def test_trades_pagination_query_preserves_filters(conn):
    from trade_trace.console.pages import trades_context

    ctx = trades_context(
        conn,
        cursor=None,
        limit=1,
        strategy_id="strat alpha/beta",
        instrument_id="ins:btc",
        decision_type="paper_enter",
    )
    assert "cursor=" in ctx["next_query"]
    assert "limit=1" in ctx["next_query"]
    assert "strategy_id=strat+alpha%2Fbeta" in ctx["next_query"]
    assert "instrument_id=ins%3Abtc" in ctx["next_query"]
    assert "decision_type=paper_enter" in ctx["next_query"]


def test_reports_context_omits_lazy_write_handlers(conn):
    from trade_trace.console.pages import reports_context

    ctx = reports_context(conn)
    assert "report.coach" not in ctx["report_tools"]
    assert "report.coach" in ctx["lazy_write_handlers_blocked"]
    assert "signal.scan" in ctx["lazy_write_handlers_blocked"]


def test_calibration_context_reports_counts(conn):
    from trade_trace.console.pages import calibration_context

    ctx = calibration_context(conn)
    assert "forecasts_total" in ctx
    assert "forecasts_scored" in ctx


def test_calibration_empty_state(empty_conn):
    from trade_trace.console.pages import calibration_context

    ctx = calibration_context(empty_conn)
    assert ctx["empty_state"] is not None


def test_strategies_context_paginates(conn):
    from trade_trace.console.pages import strategies_context

    ctx = strategies_context(conn, cursor=None, limit=10)
    assert ctx["page_title"] == "Strategies"


def test_playbooks_context_paginates(conn):
    from trade_trace.console.pages import playbooks_context

    ctx = playbooks_context(conn, cursor=None, limit=10)
    assert ctx["page_title"] == "Playbooks"


def test_integrity_context_returns_audit_counts(conn):
    from trade_trace.console.pages import integrity_context

    ctx = integrity_context(conn)
    for key in ("sources_total", "attached_decisions", "events_total", "outbox_pending"):
        assert key in ctx, key


def test_raw_index_returns_latest_events(conn):
    from trade_trace.console.pages import raw_context

    ctx = raw_context(conn)
    assert ctx["page_title"] == "Raw JSON"
    assert ctx["selected_event"] is None
    assert len(ctx["rows"]) > 0


def test_raw_event_detail_returns_payload(conn):
    from trade_trace.console.pages import raw_context

    event_id = conn.execute("SELECT id FROM events LIMIT 1").fetchone()[0]
    ctx = raw_context(conn, event_id=event_id)
    assert ctx["selected_event"] is not None
    assert ctx["selected_event"]["id"] == event_id
