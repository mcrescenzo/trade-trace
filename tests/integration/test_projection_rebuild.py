"""Projection rebuild idempotence per trade-trace-5zg.

`journal.rebuild_projections` drops and rebuilds projection tables from
their source append-only tables. The load-bearing invariant
(persistence.md §7 + §8): rebuilding twice on the same source data
produces byte-identical state, and a rebuild against a fixture event log
matches the live state.

For M1: `positions` is the only live projection. `memory_node_stats` is
deferred until M3; the rebuild is a no-op that surfaces in the result
envelope so an operator can confirm the path exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.projections import rebuild_positions
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


def _seed_minimal_position(
    home: Path,
    *,
    open_qty: float = 100,
    open_price: float = 0.42,
    close_qty: float = -100,
    close_price: float = 0.62,
    close_fees: float = 0.5,
) -> tuple[str, str]:
    """Insert a venue + instrument and two position_events forming one
    open→close cycle. Returns `(position_id, instrument_id)`."""

    from trade_trace.tools._helpers import new_id

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "X",
    })
    instrument_id = inst["data"]["id"]
    position_id = new_id("pos")

    db = open_database(db_path(home))
    try:
        with db.transaction():
            db.connection.execute(
                "INSERT INTO position_events(id, position_id, instrument_id, "
                "event_type, quantity_delta, price, fees, slippage, created_at, "
                "actor_id) VALUES (?, ?, ?, 'open', ?, ?, 0.5, 0, ?, ?)",
                (new_id("pev"), position_id, instrument_id,
                 open_qty, open_price,
                 "2026-05-18T14:00:00Z", "agent:default"),
            )
            db.connection.execute(
                "INSERT INTO position_events(id, position_id, instrument_id, "
                "event_type, quantity_delta, price, fees, slippage, created_at, "
                "actor_id) VALUES (?, ?, ?, 'close', ?, ?, ?, 0, ?, ?)",
                (new_id("pev"), position_id, instrument_id,
                 close_qty, close_price, close_fees,
                 "2026-05-18T16:00:00Z", "agent:default"),
            )
    finally:
        db.close()
    return position_id, instrument_id


def _positions_snapshot(home: Path) -> list[tuple]:
    """Return a deterministic snapshot of every row in `positions` for
    byte-identity comparison."""

    db = open_database(db_path(home))
    try:
        rows = db.connection.execute(
            "SELECT id, instrument_id, kind, side, status, opened_at, closed_at, "
            "resolved_at, realized_pnl, unrealized_pnl, avg_entry_price, "
            "updated_at, initial_risk_amount, realized_r_multiple, "
            "unrealized_r_multiple "
            "FROM positions ORDER BY id ASC"
        ).fetchall()
    finally:
        db.close()
    return rows


# -- core idempotence ------------------------------------------------------


def test_rebuild_idempotent_on_empty_db(home):
    """Two rebuilds on an empty DB produce byte-identical empty state."""

    first = _envelope(home, "journal.rebuild_projections", {"projection": "positions"})
    second = _envelope(home, "journal.rebuild_projections", {"projection": "positions"})
    assert first["ok"] is True
    assert second["ok"] is True
    assert _positions_snapshot(home) == []


def test_rebuild_idempotent_after_seeded_position(home):
    """Two consecutive rebuilds on the same source data produce row-for-row
    identical positions state."""

    _seed_minimal_position(home)
    env_first = _envelope(home, "journal.rebuild_projections", {"projection": "positions"})
    snap_first = _positions_snapshot(home)
    assert env_first["ok"] is True

    env_second = _envelope(home, "journal.rebuild_projections", {"projection": "positions"})
    snap_second = _positions_snapshot(home)
    assert env_second["ok"] is True
    assert snap_first == snap_second
    # And one row got rebuilt.
    assert len(snap_first) == 1
    # Specifically the position closed (status=closed) since open + close netted to zero.
    position_row = snap_first[0]
    assert position_row[4] == "closed"  # status
    # Signed-quantity convention: positive cumulative qty is long exposure;
    # closing fills have the opposite sign. A profitable long close is positive.
    assert position_row[8] == pytest.approx(100 * (0.62 - 0.42) - 0.5, rel=1e-6)


@pytest.mark.parametrize(
    ("open_qty", "open_price", "close_qty", "close_price", "expected_pnl"),
    [
        (100, 0.40, -100, 0.50, 10.0),   # profitable long close
        (100, 0.50, -100, 0.40, -10.0),  # losing long close
        (-100, 0.50, 100, 0.40, 10.0),   # profitable short close
        (-100, 0.40, 100, 0.50, -10.0),  # losing short close
    ],
)
def test_rebuild_realized_pnl_signed_quantity_convention(
    home, open_qty, open_price, close_qty, close_price, expected_pnl
):
    """Positive cumulative qty is long; negative cumulative qty is short.
    Realized P&L is positive for profitable closes and negative for losing
    closes, independent of the closing fill's signed quantity."""

    _seed_minimal_position(
        home,
        open_qty=open_qty,
        open_price=open_price,
        close_qty=close_qty,
        close_price=close_price,
        close_fees=0.0,
    )
    _envelope(home, "journal.rebuild_projections", {"projection": "positions"})

    position_row = _positions_snapshot(home)[0]
    assert position_row[4] == "closed"
    assert position_row[8] == pytest.approx(expected_pnl, rel=1e-6)


def test_rebuild_rejects_over_close_reversal_fill(home):
    """A close/reduce fill may not cross through zero exposure.

    Reversals must be represented as an explicit close-to-zero followed by a
    separate open/add event for the new side; otherwise realized P&L would be
    computed on more units than existed in the pre-fill exposure.
    """

    _seed_minimal_position(
        home,
        open_qty=100,
        open_price=0.40,
        close_qty=-150,
        close_price=0.60,
        close_fees=0.0,
    )

    env = _envelope(home, "journal.rebuild_projections", {"projection": "positions"})

    assert env["ok"] is False
    assert env["error"]["code"] == "INVARIANT_VIOLATION"
    assert "exceeds current exposure" in env["error"]["message"]
    assert env["error"]["details"]["current_quantity"] == 100
    assert env["error"]["details"]["quantity_delta"] == -150
    # The rebuild transaction rolled back; no partial/stale projection row was written.
    assert _positions_snapshot(home) == []


@pytest.mark.parametrize(
    ("open_qty", "close_qty"),
    [
        (100, 50),    # long exposure cannot be reduced by a positive close delta
        (-100, -50),  # short exposure cannot be reduced by a negative close delta
    ],
)
def test_rebuild_rejects_same_sign_exit_quantity_delta(home, open_qty, close_qty):
    """Exit events must move current exposure toward zero, not add to it."""

    _seed_minimal_position(
        home,
        open_qty=open_qty,
        open_price=0.40,
        close_qty=close_qty,
        close_price=0.60,
        close_fees=0.0,
    )

    env = _envelope(home, "journal.rebuild_projections", {"projection": "positions"})

    assert env["ok"] is False
    assert env["error"]["code"] == "INVARIANT_VIOLATION"
    assert "does not reduce current exposure" in env["error"]["message"]
    assert env["error"]["details"]["current_quantity"] == open_qty
    assert env["error"]["details"]["quantity_delta"] == close_qty
    # The rebuild transaction rolled back; no partial/stale projection row was written.
    assert _positions_snapshot(home) == []


# -- live-vs-rebuilt parity (positions) -----------------------------------


def test_live_vs_rebuilt_parity_positions(home):
    """Per persistence.md §7 invariant: the rebuilt projection equals the
    live projection. M1 doesn't run live updates on position_events writes
    yet (the eager projection is wired in a separate bead — see
    trade-trace-vvt followup); for now the live and rebuilt states are
    both 'a single rebuild from the same event tail'. This test seeds
    position_events, runs rebuild, snapshots, runs rebuild AGAIN, and
    asserts both snapshots equal each other (since rebuild is the only
    write path to positions in M1)."""

    _seed_minimal_position(home)
    _envelope(home, "journal.rebuild_projections", {"projection": "positions"})
    snap_live = _positions_snapshot(home)
    # Force a second rebuild (the only thing that could change positions
    # in M1) and confirm parity.
    _envelope(home, "journal.rebuild_projections", {"projection": "positions"})
    snap_rebuilt = _positions_snapshot(home)
    assert snap_live == snap_rebuilt


# -- atomic rebuild rollback ---------------------------------------------


def test_atomic_rebuild_rollback_on_error(home):
    """If the rebuild raises mid-flight, the prior projection state must
    survive (single-transaction atomicity per persistence.md §7)."""

    _seed_minimal_position(home)
    _envelope(home, "journal.rebuild_projections", {"projection": "positions"})
    snap_before = _positions_snapshot(home)
    assert len(snap_before) == 1

    # Drive the rebuild directly so we can inject the failure inside the
    # transaction (the tool wraps the whole call in db.transaction()).
    db = open_database(db_path(home))
    try:
        try:
            with db.transaction():
                rebuild_positions(db.connection)
                # Confirm the rebuild ran (intermediate state visible
                # within the transaction).
                inflight = db.connection.execute(
                    "SELECT COUNT(*) FROM positions"
                ).fetchone()[0]
                assert inflight == 1
                # Now blow up — the transaction must roll back.
                raise RuntimeError("simulated bug")
        except RuntimeError:
            pass
    finally:
        db.close()

    # Pre-rebuild state survived intact (or rather: the prior committed
    # state, which is the same set of rows).
    snap_after = _positions_snapshot(home)
    assert snap_after == snap_before


# -- memory_node_stats deferred ------------------------------------------


def test_memory_node_stats_rebuild_is_noop(home):
    """Until M3 ships, the rebuild is a no-op that still surfaces in the
    result envelope so operators can confirm the path exists."""

    env = _envelope(home, "journal.rebuild_projections", {"projection": "memory_node_stats"})
    assert env["ok"] is True
    results = env["data"]["results"]
    assert len(results) == 1
    res = results[0]
    assert res["projection"] == "memory_node_stats"
    assert res["dropped_rows"] == 0
    assert res["rebuilt_rows"] == 0


def test_all_projection_rebuilds_positions_and_memory_in_one_call(home):
    """`projection=all` covers both projections in one transaction."""

    _seed_minimal_position(home)
    env = _envelope(home, "journal.rebuild_projections", {"projection": "all"})
    assert env["ok"] is True
    projections = {r["projection"] for r in env["data"]["results"]}
    assert projections == {"positions", "memory_node_stats"}


# -- validation ---------------------------------------------------------


def test_rebuild_requires_projection_argument(home):
    env = _envelope(home, "journal.rebuild_projections", {})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "projection"


def test_rebuild_rejects_unknown_projection(home):
    env = _envelope(home, "journal.rebuild_projections", {"projection": "made_up"})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


# -- envelope shape ----------------------------------------------------


def test_rebuild_envelope_carries_duration_ms(home):
    env = _envelope(home, "journal.rebuild_projections", {"projection": "positions"})
    assert env["ok"] is True
    assert "duration_ms" in env["data"]
    assert isinstance(env["data"]["duration_ms"], int)
    assert env["data"]["duration_ms"] >= 0
