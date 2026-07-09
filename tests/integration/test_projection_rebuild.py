"""Projection rebuild idempotence per trade-trace-5zg.

`journal.rebuild_projections` drops and rebuilds projection tables from
their source append-only tables. The load-bearing invariant
(persistence.md §7 + §8): rebuilding twice on the same source data
produces byte-identical state, and a rebuild against a fixture event log
matches the live state.

`positions` and `memory_node_stats` are live projections. Rebuilding
`memory_node_stats` on a fresh home is implemented but yields zero rows.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.mcp_server import mcp_call
from trade_trace.projections import rebuild_positions
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


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


# -- memory_node_stats empty-home rebuild --------------------------------


def test_memory_node_stats_rebuild_on_empty_home_yields_zero_rows(home):
    """The rebuild is implemented; a fresh home simply has no recall rows."""

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


# -- reopen semantics (trade-trace-7h2u + trade-trace-9f8d) -------------


def _seed_open_close_reopen(
    home: Path, *, final_close: bool = False,
) -> tuple[str, str]:
    """Seed a position with an open → close → reopen sequence on the same
    `position_id`. When `final_close` is True the position is closed
    again after the reopen, producing two complete cycles."""

    from trade_trace.tools._helpers import new_id

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "X",
    })
    instrument_id = inst["data"]["id"]
    position_id = new_id("pos")

    sequence = [
        # t0 open 100 @ 0.40
        ("open", 100, 0.40, 0.5, "2026-05-18T14:00:00Z"),
        # t1 close all @ 0.55 → realized = 100 * (0.55 - 0.40) - fees
        ("close", -100, 0.55, 0.5, "2026-05-18T16:00:00Z"),
        # t2 reopen 50 @ 0.60
        ("open", 50, 0.60, 0.5, "2026-05-19T10:00:00Z"),
    ]
    if final_close:
        # t3 close the reopened 50 @ 0.45 → realized = 50 * (0.45 - 0.60) - fees
        sequence.append(
            ("close", -50, 0.45, 0.5, "2026-05-19T15:00:00Z"),
        )

    db = open_database(db_path(home))
    try:
        with db.transaction():
            for evt, qty, price, fees, ts in sequence:
                db.connection.execute(
                    "INSERT INTO position_events(id, position_id, instrument_id, "
                    "event_type, quantity_delta, price, fees, slippage, created_at, "
                    "actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                    (new_id("pev"), position_id, instrument_id, evt,
                     qty, price, fees, ts, "agent:default"),
                )
    finally:
        db.close()
    return position_id, instrument_id


def test_reopen_after_close_uses_first_event_for_opened_at(home):
    """Per docs/architecture/position-reopen-semantics.md (trade-trace-7h2u):
    the `positions` projection is a lifetime aggregate per `position_id`.
    `opened_at` pins to the FIRST event ever (the lifetime origin), not
    the latest open interval — even after the position has fully closed
    and re-opened."""

    _seed_open_close_reopen(home)
    env = _envelope(home, "journal.rebuild_projections", {"projection": "positions"})
    assert env["ok"] is True
    rows = _positions_snapshot(home)
    assert len(rows) == 1, rows
    row = rows[0]
    # opened_at index is 5 per the SELECT order in _positions_snapshot.
    opened_at = row[5]
    status = row[4]
    assert opened_at == "2026-05-18T14:00:00Z", (
        "opened_at must pin to the first event (lifetime origin), not the "
        f"latest open after a close+reopen (got {opened_at!r})"
    )
    # Still open after the reopen.
    assert status == "open"


def test_realized_pnl_accumulates_across_intervals_with_lifetime_vwap(home):
    """Per docs/architecture/position-reopen-semantics.md (trade-trace-7h2u):
    a close after a reopen computes realized P&L against the lifetime
    volume-weighted average entry price (which folded the reopen fill in),
    not a per-interval average. For open100@0.40, close@0.55, open50@0.60,
    close50@0.45 with 0.5 fees per fill, the lifetime VWAP at the second
    close is (100*0.40 + 50*0.60)/150 = 0.4666..., and the realized P&L
    is the sum 14.5 + (0.45 - 0.4666...)*50 - 0.5 = 13.166..."""

    _seed_open_close_reopen(home, final_close=True)
    env = _envelope(home, "journal.rebuild_projections", {"projection": "positions"})
    assert env["ok"] is True
    rows = _positions_snapshot(home)
    assert len(rows) == 1, rows
    row = rows[0]
    realized = row[8]
    status = row[4]
    lifetime_vwap = (100 * 0.40 + 50 * 0.60) / 150
    expected = (0.55 - 0.40) * 100 - 0.5 + (0.45 - lifetime_vwap) * 50 - 0.5
    assert realized == pytest.approx(expected, rel=1e-6), (
        f"realized_pnl must use lifetime VWAP for the second close "
        f"(got {realized!r}; expected {expected!r})"
    )
    assert status == "closed"


# -- corrupt memory_recall_events JSON diagnostics (trade-trace-iip4) ---


def test_rebuild_memory_node_stats_reports_skipped_corrupt_rows(home):
    """Per trade-trace-iip4: `rebuild_memory_node_stats` previously
    silently swallowed `memory_recall_events` rows whose
    `node_ids_returned` failed to decode, making operators unable to
    distinguish 'no recall events' from 'recall rows skipped'. The
    rebuild now reports a `skipped_corrupt_rows` count in the
    envelope's diagnostics so the operator can investigate.

    Behavior chosen: count + warn (rebuild does NOT fail), because the
    primary use-case is corruption recovery — failing the rebuild on
    the first bad row would prevent the operator from extracting
    whatever good state remains."""

    # Seed two real memory_nodes so memory_node_stats FK constraints
    # are satisfied when the rebuild walks the valid recall event.
    node_a = _envelope(home, "memory.retain", {
        "node_type": "observation", "body": "node a",
        "idempotency_key": "iip4-node-a",
    })["data"]["id"]
    node_b = _envelope(home, "memory.retain", {
        "node_type": "observation", "body": "node b",
        "idempotency_key": "iip4-node-b",
    })["data"]["id"]
    valid_node_ids = json.dumps([node_a, node_b])

    # Seed one valid and one corrupt memory_recall_events row by direct
    # SQL: the public memory.recall path never writes a malformed JSON
    # payload, but historical journal data can carry corruption.
    db = open_database(db_path(home))
    try:
        with db.transaction():
            db.connection.execute(
                "INSERT INTO memory_recall_events("
                "recall_id, query, strategies_used, node_ids_returned, "
                "limit_k, created_at, actor_id) "
                "VALUES (?, 'q1', 'bm25', ?, 5, ?, 'agent:default')",
                ("rcl-iip4-valid", valid_node_ids, "2026-05-19T10:00:00Z"),
            )
            db.connection.execute(
                "INSERT INTO memory_recall_events("
                "recall_id, query, strategies_used, node_ids_returned, "
                "limit_k, created_at, actor_id) "
                "VALUES (?, 'q2', 'bm25', ?, 5, ?, 'agent:default')",
                ("rcl-iip4-corrupt", "not valid json {",
                 "2026-05-19T11:00:00Z"),
            )
    finally:
        db.close()

    env = _envelope(home, "journal.rebuild_projections", {"projection": "memory_node_stats"})
    assert env["ok"] is True, env
    # The handler returns a list of per-projection summaries under `results`.
    summaries = env["data"]["results"]
    summary = next(s for s in summaries if s["projection"] == "memory_node_stats")
    assert summary["skipped_corrupt_rows"] == 1, (
        f"rebuild must report the corrupt row count (got {summary!r})"
    )
    # The valid row's two node ids land in the projection.
    assert summary["rebuilt_rows"] == 2


# -- side-aware unrealized P&L (trade-trace-ctvb) -----------------------


def _seed_open_position_with_mark(
    home: Path,
    *,
    side: str,
    open_qty: float,
    entry_price: float,
    yes_mark: float,
) -> tuple[str, str]:
    """Seed an open position (one `open` position_event linked to a
    decision carrying `side`) plus a snapshot whose `price` is the
    YES-contract mark. Returns `(position_id, instrument_id)`.

    `open_qty` is the SIGNED quantity_delta the decision path would write:
    positive for yes/long, negative for no/short (mirrors
    `_paper_enter_quantity_delta`). `entry_price` is the side-native price
    the bot paid; `yes_mark` is the unchanged YES-contract mark."""

    from trade_trace.tools._helpers import new_id

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "X",
    })
    instrument_id = inst["data"]["id"]
    position_id = new_id("pos")
    decision_id = new_id("dec")

    db = open_database(db_path(home))
    try:
        with db.transaction():
            db.connection.execute(
                "INSERT INTO snapshots(id, instrument_id, captured_at, source, "
                "price, implied_probability, created_at, actor_id) "
                "VALUES (?, ?, ?, 'test', ?, ?, ?, 'agent:default')",
                (new_id("snp"), instrument_id, "2026-05-18T13:00:00Z",
                 yes_mark, yes_mark, "2026-05-18T13:00:00Z"),
            )
            db.connection.execute(
                "INSERT INTO decisions(id, instrument_id, type, side, quantity, "
                "price, created_at, actor_id) "
                "VALUES (?, ?, 'paper_enter', ?, ?, ?, ?, 'agent:default')",
                (decision_id, instrument_id, side, abs(open_qty),
                 entry_price, "2026-05-18T14:00:00Z"),
            )
            db.connection.execute(
                "INSERT INTO position_events(id, position_id, instrument_id, "
                "decision_id, event_type, quantity_delta, price, fees, slippage, "
                "created_at, actor_id) "
                "VALUES (?, ?, ?, ?, 'open', ?, ?, 0, 0, ?, 'agent:default')",
                (new_id("pev"), position_id, instrument_id, decision_id,
                 open_qty, entry_price, "2026-05-18T14:00:00Z"),
            )
    finally:
        db.close()
    return position_id, instrument_id


def test_no_side_flat_position_reports_zero_unrealized_pnl(home):
    """trade-trace-ctvb regression: a flat NO position entered at the NO
    price (0.875) while the YES mark is unchanged (0.125) must report
    unrealized_pnl ~= 0, NOT the old phantom +75.5 from marking the
    NO-contract entry against the raw YES mark."""

    _seed_open_position_with_mark(
        home, side="no", open_qty=-100, entry_price=0.875, yes_mark=0.125,
    )
    _envelope(home, "journal.rebuild_projections", {"projection": "positions"})

    row = _positions_snapshot(home)[0]
    assert row[3] == "no"  # side
    assert row[4] == "open"  # status
    # unrealized_pnl index is 9 per _positions_snapshot column order.
    assert row[9] == pytest.approx(0.0, abs=1e-9)


def test_no_side_position_marks_against_complemented_mark(home):
    """A NO position is in profit when the YES mark falls (NO contract
    appreciates). Entered NO @ 0.875 (yes 0.125), YES mark drops to 0.075
    so NO mark = 0.925; unrealized = (0.925 - 0.875) * 100 = +5.0."""

    _seed_open_position_with_mark(
        home, side="no", open_qty=-100, entry_price=0.875, yes_mark=0.075,
    )
    _envelope(home, "journal.rebuild_projections", {"projection": "positions"})

    row = _positions_snapshot(home)[0]
    assert row[9] == pytest.approx((0.925 - 0.875) * 100, rel=1e-6)


@pytest.mark.parametrize("side", ["No", "NO", "Yes", "Long"])
def test_decisions_side_check_constraint_rejects_non_lowercase(home, side):
    """trade-trace-ctvb hardening: the worry that a ``'No'`` / ``'NO'`` side
    would skip the NO-complement and resurrect the phantom +75.5 PnL is not
    reachable — ``decisions.side`` carries a CHECK constraint
    (m003_m1_ledger.py) that admits only the lowercase enum
    ('long','short','yes','no','flat_neutral','pairs_long_short'). A
    non-lowercase side is rejected at write time, so the projection never
    marks an unnormalized side. This pins that contract.

    `_unrealized_pnl` still lowercases defensively (a pure function should
    not assume the schema), but THIS is the boundary that closes the gap."""

    import sqlite3

    db = open_database(db_path(home))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            with db.transaction():
                db.connection.execute(
                    "INSERT INTO decisions(id, instrument_id, type, side, "
                    "quantity, price, created_at, actor_id) VALUES "
                    "(?, NULL, 'paper_enter', ?, 100, 0.5, "
                    "'2026-05-18T14:00:00Z', 'agent:default')",
                    ("dec_badside", side),
                )
    finally:
        db.close()


def test_yes_side_position_marks_against_yes_mark(home):
    """A YES/long position still marks directly against the YES mark:
    entered YES @ 0.40, mark 0.55 => unrealized = (0.55 - 0.40) * 100."""

    _seed_open_position_with_mark(
        home, side="yes", open_qty=100, entry_price=0.40, yes_mark=0.55,
    )
    _envelope(home, "journal.rebuild_projections", {"projection": "positions"})

    row = _positions_snapshot(home)[0]
    assert row[9] == pytest.approx((0.55 - 0.40) * 100, rel=1e-6)


def test_generic_short_side_marks_without_complement(home):
    """A generic `short` (not a prediction-market `no`) is marked against
    the SAME instrument price with no 1-price complement. Short opened @
    0.50, mark falls to 0.40 => profit (0.50 - 0.40) * 100 = +10."""

    _seed_open_position_with_mark(
        home, side="short", open_qty=-100, entry_price=0.50, yes_mark=0.40,
    )
    _envelope(home, "journal.rebuild_projections", {"projection": "positions"})

    row = _positions_snapshot(home)[0]
    # Signed convention: (mark - entry) * qty = (0.40 - 0.50) * -100 = +10.
    assert row[9] == pytest.approx(10.0, rel=1e-6)


def test_rebuild_corrects_existing_no_side_unrealized_pnl(home):
    """Migration/rebuild story (trade-trace-ctvb): positions is rebuildable
    from position_events, so an existing row carrying the old phantom
    unrealized_pnl is corrected in place by re-running the rebuild — no
    position_events migration is needed because the side-native entry price
    was already stored. Simulate a stale projection row, rebuild, and
    confirm the phantom value is replaced with ~0."""

    position_id, _ = _seed_open_position_with_mark(
        home, side="no", open_qty=-100, entry_price=0.875, yes_mark=0.125,
    )
    # Simulate a pre-fix projection row by stamping the old phantom value.
    db = open_database(db_path(home))
    try:
        with db.transaction():
            db.connection.execute(
                "DELETE FROM positions WHERE id = ?", (position_id,)
            )
            db.connection.execute(
                "INSERT INTO positions(id, instrument_id, kind, side, status, "
                "opened_at, unrealized_pnl, avg_entry_price, updated_at) "
                "VALUES (?, ?, 'paper', 'no', 'open', ?, ?, ?, ?)",
                (position_id, _, "2026-05-18T14:00:00Z", 75.5, 0.875,
                 "2026-05-18T14:00:00Z"),
            )
    finally:
        db.close()

    stale = _positions_snapshot(home)[0]
    assert stale[9] == pytest.approx(75.5, rel=1e-6)

    _envelope(home, "journal.rebuild_projections", {"projection": "positions"})

    fixed = _positions_snapshot(home)[0]
    assert fixed[9] == pytest.approx(0.0, abs=1e-9)


def test_rebuild_memory_node_stats_reports_zero_skipped_when_clean(home):
    """A clean DB has no corrupt rows; the diagnostics still surface the
    counter explicitly (zero) so callers can branch on its presence."""

    env = _envelope(home, "journal.rebuild_projections", {"projection": "memory_node_stats"})
    assert env["ok"] is True
    summaries = env["data"]["results"]
    summary = next(s for s in summaries if s["projection"] == "memory_node_stats")
    assert summary["skipped_corrupt_rows"] == 0


# -- batched decisions lookup (trade-trace-6046, N+1 fix) ---------------


def _seed_n_positions_with_decisions(
    home: Path, n: int
) -> tuple[str, list[str]]:
    """Seed `n` distinct open positions on the same instrument, each linked
    to its own `paper_enter` decision (so each carries a non-null
    `decision_id`). Returns `(instrument_id, [position_id, ...])`.

    This is the worst case for the old N+1: every position group had a
    decision, so the pre-fix rebuild issued `n` separate
    `SELECT type, side FROM decisions WHERE id = ?` queries."""

    from trade_trace.tools._helpers import new_id

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "X",
    })
    instrument_id = inst["data"]["id"]

    position_ids: list[str] = []
    db = open_database(db_path(home))
    try:
        with db.transaction():
            for i in range(n):
                position_id = new_id("pos")
                decision_id = new_id("dec")
                # Alternate yes/no so kind/side derivation is exercised for
                # both the complement and direct branches.
                side = "yes" if i % 2 == 0 else "no"
                signed_qty = 100 if side == "yes" else -100
                entry_price = 0.40 if side == "yes" else 0.60
                db.connection.execute(
                    "INSERT INTO decisions(id, instrument_id, type, side, "
                    "quantity, price, created_at, actor_id) VALUES "
                    "(?, ?, 'paper_enter', ?, 100, ?, ?, 'agent:default')",
                    (decision_id, instrument_id, side, entry_price,
                     "2026-05-18T14:00:00Z"),
                )
                db.connection.execute(
                    "INSERT INTO position_events(id, position_id, "
                    "instrument_id, decision_id, event_type, quantity_delta, "
                    "price, fees, slippage, created_at, actor_id) VALUES "
                    "(?, ?, ?, ?, 'open', ?, ?, 0, 0, ?, 'agent:default')",
                    (new_id("pev"), position_id, instrument_id, decision_id,
                     signed_qty, entry_price, "2026-05-18T14:00:00Z"),
                )
                position_ids.append(position_id)
    finally:
        db.close()
    return instrument_id, position_ids


def test_rebuild_issues_single_decisions_query_for_n_positions(home):
    """trade-trace-6046: `rebuild_positions` pre-fetches every referenced
    decision in ONE `SELECT ... WHERE id IN (...)` rather than one query per
    position group. Trace SQL executed during the rebuild and assert exactly
    one decisions SELECT fires regardless of N (here N=5)."""

    n = 5
    _seed_n_positions_with_decisions(home, n)

    decisions_selects: list[str] = []

    db = open_database(db_path(home))
    try:
        def _trace(sql: str) -> None:
            normalized = " ".join(sql.split()).lower()
            if normalized.startswith("select") and "from decisions" in normalized:
                decisions_selects.append(normalized)

        db.connection.set_trace_callback(_trace)
        try:
            with db.transaction():
                rebuild_positions(db.connection)
        finally:
            db.connection.set_trace_callback(None)
    finally:
        db.close()

    assert len(decisions_selects) == 1, (
        "rebuild_positions must batch all decision lookups into a single "
        f"query; saw {len(decisions_selects)} decisions SELECTs: "
        f"{decisions_selects!r}"
    )
    # And it is the batched IN(...) form, not a single-id equality.
    assert " in (" in decisions_selects[0], decisions_selects[0]


def test_rebuild_kind_side_unchanged_with_batched_lookup(home):
    """The batched lookup must produce identical kind/side derivation as the
    old per-position path: yes positions stay `paper`/`yes`, no positions
    stay `paper`/`no`."""

    n = 4
    _, position_ids = _seed_n_positions_with_decisions(home, n)
    env = _envelope(home, "journal.rebuild_projections", {"projection": "positions"})
    assert env["ok"] is True

    rows = _positions_snapshot(home)
    assert len(rows) == n, rows
    # snapshot columns: id(0), instrument_id(1), kind(2), side(3), status(4)
    by_id = {row[0]: row for row in rows}
    for i, position_id in enumerate(position_ids):
        row = by_id[position_id]
        expected_side = "yes" if i % 2 == 0 else "no"
        assert row[2] == "paper", (position_id, row)
        assert row[3] == expected_side, (position_id, row)
        assert row[4] == "open", (position_id, row)


def test_rebuild_with_no_decisions_issues_zero_decisions_queries(home):
    """When no position_events reference a decision, the batched path runs
    NO decisions query at all (empty id set short-circuits), and derivation
    falls back to the `simulation`/`long` defaults."""

    _seed_minimal_position(home)  # direct events, no decision_id

    decisions_selects: list[str] = []

    db = open_database(db_path(home))
    try:
        def _trace(sql: str) -> None:
            normalized = " ".join(sql.split()).lower()
            if normalized.startswith("select") and "from decisions" in normalized:
                decisions_selects.append(normalized)

        db.connection.set_trace_callback(_trace)
        try:
            with db.transaction():
                rebuild_positions(db.connection)
        finally:
            db.connection.set_trace_callback(None)
    finally:
        db.close()

    assert decisions_selects == [], decisions_selects

    row = _positions_snapshot(home)[0]
    assert row[2] == "simulation"  # kind default
    assert row[3] == "long"  # side default
