"""Projection rebuilders per docs/architecture/persistence.md §7.

Projection tables (`positions`, `memory_node_stats`) are rebuildable from
their source append-only tables. `journal.rebuild_projections` drops and
re-inserts the chosen projection inside one transaction, so the rebuild is
atomic with respect to readers and to other writers serialized behind the
single-writer lock.

This module is the rebuild kernel. It is decoupled from the MCP/CLI tool
surface (`tools/journal.py`) so unit tests can drive it directly against
an in-memory database.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, NamedTuple

from trade_trace.contracts.errors import ErrorCode
from trade_trace.tools.errors import ToolError


@dataclass
class RebuildResult:
    """Summary returned by `rebuild_projections`. Mirrors the success
    envelope `journal.rebuild_projections` surfaces.

    `skipped_corrupt_rows` (trade-trace-iip4) counts append-only source
    rows the rebuild had to skip because their JSON payload would not
    decode. Operators can branch on a non-zero value to investigate
    journal corruption; zero means the rebuild walked every source row
    successfully.
    """

    projection: str
    dropped_rows: int
    rebuilt_rows: int
    skipped_corrupt_rows: int = 0


class PositionEventRow(NamedTuple):
    """Named shape used while replaying `position_events` into `positions`."""

    position_id: str
    instrument_id: str
    event_type: str
    quantity_delta: float | None
    price: float | None
    fees: float | None
    slippage: float | None
    initial_risk_amount: float | None
    realized_r_multiple: float | None
    unrealized_r_multiple: float | None
    created_at: str
    id: str
    decision_id: str | None


def rebuild_positions(conn: sqlite3.Connection) -> RebuildResult:
    """Drop and rebuild the `positions` projection from `position_events`.

    Determinism contract per persistence.md §7 + §8 (the append-only +
    rebuild invariant): running this twice on the same `position_events`
    rows MUST produce row-for-row identical `positions` state.

    Implementation:

    1. Walk `position_events` grouped by `position_id`, ordered by
       `(created_at ASC, id ASC)` so the timestamp tie-break is stable.
    2. For each group, derive:
       - `instrument_id` from the first event (every event for a position
         carries the same instrument_id; we read it once for the
         projection row).
       - `kind` from the decisions joined via `decision_id` of the
         opening event. `paper_enter` / `paper_exit` → `paper`;
         `actual_enter` / `actual_exit` / `add` / `reduce` /
         `close` → `actual`; anything else → `simulation`.
       - `side` from the decisions joined via the opening event
         (or `long` as the safe default for direct event writes that
         omit a decision).
       - cumulative `quantity_delta` to derive open vs closed status and
         the volume-weighted entry price for `avg_entry_price`. Signed
         quantity convention: positive cumulative quantity is long exposure,
         negative cumulative quantity is short exposure. Entries add exposure
         in the position direction; closing fills have the opposite sign.
       - `realized_pnl`: sum of reducing/closing fills, positive for
         profitable closes and negative for losing closes after fees/slippage.
       - `opened_at` = timestamp of the first event.
       - `closed_at` = timestamp of the event that drove cumulative
         quantity to exactly zero. Re-opens (a fresh `open` after a
         close) start a new accumulation in the same position_id —
         the projection captures the latest open interval.
       - `unrealized_pnl`: 0.0 when closed; for open positions, computed
         from the most recent `snapshots.price` for the instrument.
       - `updated_at` = timestamp of the last event in the group.
    3. The mirror R-multiple columns
       (`initial_risk_amount`, `realized_r_multiple`, `unrealized_r_multiple`)
       echo the most recent non-NULL value seen on a `position_events`
       row in the group (P1 risk-units.md §3.4).

    Returns a `RebuildResult` with dropped + rebuilt counts. Caller wraps
    in a transaction; this function does not commit.
    """

    dropped = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    conn.execute("DELETE FROM positions")

    groups = conn.execute(
        """
        SELECT pe.position_id,
               pe.instrument_id,
               pe.event_type,
               pe.quantity_delta,
               pe.price,
               pe.fees,
               pe.slippage,
               pe.initial_risk_amount,
               pe.realized_r_multiple,
               pe.unrealized_r_multiple,
               pe.created_at,
               pe.id,
               pe.decision_id
        FROM position_events pe
        ORDER BY pe.position_id ASC, pe.created_at ASC, pe.id ASC
        """
    ).fetchall()

    by_position: dict[str, list[PositionEventRow]] = {}
    for row in groups:
        event = PositionEventRow(*row)
        by_position.setdefault(event.position_id, []).append(event)

    rebuilt = 0
    for position_id, events in by_position.items():
        projection = _accumulate_position(conn, position_id, events)
        if projection is None:
            continue
        conn.execute(
            """
            INSERT INTO positions(
                id, instrument_id, kind, side, status, opened_at, closed_at,
                resolved_at, realized_pnl, unrealized_pnl, avg_entry_price,
                updated_at, initial_risk_amount, realized_r_multiple,
                unrealized_r_multiple
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                projection["id"],
                projection["instrument_id"],
                projection["kind"],
                projection["side"],
                projection["status"],
                projection["opened_at"],
                projection["closed_at"],
                None,  # resolved_at: M1 has no resolved-by-outcome wiring
                projection["realized_pnl"],
                projection["unrealized_pnl"],
                projection["avg_entry_price"],
                projection["updated_at"],
                projection["initial_risk_amount"],
                projection["realized_r_multiple"],
                projection["unrealized_r_multiple"],
            ),
        )
        rebuilt += 1

    return RebuildResult(projection="positions", dropped_rows=int(dropped), rebuilt_rows=rebuilt)


_PAPER_DECISION_TYPES = frozenset({"paper_enter", "paper_exit"})
_ACTUAL_DECISION_TYPES = frozenset(
    {"actual_enter", "actual_exit", "add", "reduce", "hold", "resolved"}
)


def _derive_kind_and_side(
    conn: sqlite3.Connection, events: list[PositionEventRow]
) -> tuple[str, str]:
    """Pull kind/side from the opening event's decision when present.

    Defaults to `simulation` / `long` so a direct position_events fixture
    that doesn't reference a decision still produces a deterministic
    projection row."""

    kind = "simulation"
    side = "long"
    for row in events:
        decision_id = row.decision_id
        if decision_id is None:
            continue
        decision = conn.execute(
            "SELECT type, side FROM decisions WHERE id = ?", (decision_id,)
        ).fetchone()
        if decision is None:
            continue
        dtype, dside = decision
        if dtype in _PAPER_DECISION_TYPES:
            kind = "paper"
        elif dtype in _ACTUAL_DECISION_TYPES:
            kind = "actual"
        if dside is not None:
            side = dside
        break
    return kind, side


def _accumulate_position(
    conn: sqlite3.Connection,
    position_id: str,
    events: list[PositionEventRow],
) -> dict[str, Any] | None:
    """Walk one position_id's event sequence and return the projection
    row. Returns None when the sequence is empty (defensive — the SQL
    query above shouldn't produce empty groups)."""

    if not events:
        return None

    instrument_id = events[0].instrument_id
    opened_at = events[0].created_at
    updated_at = events[-1].created_at
    closed_at: str | None = None

    qty = 0.0
    weighted_entry_price_qty = 0.0  # sum of (price * |qty|) for entries
    abs_entry_qty = 0.0
    realized_pnl = 0.0
    initial_risk_amount: float | None = None
    realized_r_multiple: float | None = None
    unrealized_r_multiple: float | None = None

    avg_entry_price: float | None = None

    for row in events:
        event_type = row.event_type
        qty_delta = row.quantity_delta or 0.0
        price = row.price
        fees = row.fees or 0.0
        slippage = row.slippage or 0.0
        if row.initial_risk_amount is not None:
            initial_risk_amount = float(row.initial_risk_amount)
        if row.realized_r_multiple is not None:
            realized_r_multiple = float(row.realized_r_multiple)
        if row.unrealized_r_multiple is not None:
            unrealized_r_multiple = float(row.unrealized_r_multiple)

        is_entry = event_type in {"open", "add"}
        is_exit = event_type in {"reduce", "close", "expire", "assigned"}

        if is_entry and price is not None:
            weighted_entry_price_qty += price * abs(qty_delta)
            abs_entry_qty += abs(qty_delta)
            if abs_entry_qty > 0:
                avg_entry_price = weighted_entry_price_qty / abs_entry_qty
        elif is_exit:
            # Signed quantity convention: an exit/reducing fill must move
            # cumulative exposure toward zero without crossing it. Reversals
            # (e.g. +100 then close -150) require explicit split events;
            # otherwise realized P&L would be overstated and avg_entry_price
            # would remain tied to the stale pre-reversal side.
            exit_qty = abs(qty_delta)
            if not _approx_zero(qty_delta):
                if (
                    (qty > 0 and qty_delta > 0)
                    or (qty < 0 and qty_delta < 0)
                    or _approx_zero(qty)
                ):
                    raise ToolError(
                        ErrorCode.INVARIANT_VIOLATION,
                        "position exit quantity_delta does not reduce current exposure",
                        details={
                            "position_id": position_id,
                            "event_id": row.id,
                            "event_type": event_type,
                            "current_quantity": qty,
                            "quantity_delta": qty_delta,
                        },
                    )
                if exit_qty > abs(qty) + 1e-9:
                    raise ToolError(
                        ErrorCode.INVARIANT_VIOLATION,
                        "position exit quantity exceeds current exposure; split reversal fills into close plus open/add events",
                        details={
                            "position_id": position_id,
                            "event_id": row.id,
                            "event_type": event_type,
                            "current_quantity": qty,
                            "quantity_delta": qty_delta,
                        },
                    )

        if is_exit and price is not None and avg_entry_price is not None:
            # Signed quantity convention: positive cumulative `qty` is long
            # exposure, negative cumulative `qty` is short exposure. Exit
            # events carry the opposite sign from the exposure they reduce,
            # so realized P&L must be signed from the pre-fill position side
            # rather than from `qty_delta` directly:
            #   long close  (+qty, -delta): (exit - entry) * |delta|
            #   short close (-qty, +delta): (entry - exit) * |delta|
            if qty > 0:
                realized_pnl += (price - avg_entry_price) * exit_qty
            elif qty < 0:
                realized_pnl += (avg_entry_price - price) * exit_qty
            realized_pnl -= fees + slippage

        qty += qty_delta
        if event_type in {"close", "expire", "assigned"} or _approx_zero(qty):
            closed_at = row.created_at

    status = "closed" if _approx_zero(qty) else "open"

    kind, side = _derive_kind_and_side(conn, events)

    unrealized_pnl: float | None = None
    if status == "open" and avg_entry_price is not None:
        snap_price = _latest_snapshot_price(conn, instrument_id)
        if snap_price is not None:
            unrealized_pnl = _unrealized_pnl(side, snap_price, avg_entry_price, qty)

    return {
        "id": position_id,
        "instrument_id": instrument_id,
        "kind": kind,
        "side": side,
        "status": status,
        "opened_at": opened_at,
        "closed_at": closed_at if status == "closed" else None,
        "realized_pnl": realized_pnl if realized_pnl != 0.0 else None,
        "unrealized_pnl": unrealized_pnl,
        "avg_entry_price": avg_entry_price,
        "updated_at": updated_at,
        "initial_risk_amount": initial_risk_amount,
        "realized_r_multiple": realized_r_multiple,
        "unrealized_r_multiple": unrealized_r_multiple,
    }


def _approx_zero(value: float) -> bool:
    return abs(value) < 1e-9


# Prediction-market sides whose `decision.add price` is the side-NATIVE
# contract price (the price actually paid for the NO contract), not the
# YES-contract price. Snapshots store the YES-contract price, so the mark
# for these sides must be complemented (1 - yes_price) before it is
# compared against the side-native entry price. See the canonical price
# convention documented on `decision.add` via
# `decision_matrix.PRICE_CONVENTION` (trade-trace-ctvb).
_COMPLEMENT_SIDES = frozenset({"no"})


def _unrealized_pnl(
    side: str | None,
    snap_price: float,
    avg_entry_price: float,
    qty: float,
) -> float:
    """Compute side-aware unrealized P&L for an open position.

    Canonical price convention (trade-trace-ctvb): `decision.add price` is
    the SIDE-NATIVE price the bot paid for the contract — for a `no`
    prediction-market side that is the NO-contract price (1 - yes_price),
    not the YES-contract price. Snapshots (`snapshots.price`) always store
    the YES-contract price (the YES implied probability / mid). So:

    * Long / yes (qty > 0): mark and entry are both YES-contract prices
      already, so ``(yes_mark - entry) * qty``.
    * No prediction-market side (qty < 0, side == 'no'): the entry is a
      NO-contract price; convert the YES mark to NO terms
      (``1 - yes_mark``) and price the NO contracts the bot holds:
      ``((1 - yes_mark) - entry) * |qty|``.
    * Generic short (qty < 0, side == 'short'): there is no
      complement — the short was opened and is marked against the SAME
      instrument price, so the signed convention ``(mark - entry) * qty``
      already yields a profit when the mark falls below entry.

    Without this conversion a flat `no` position entered at the NO price
    while the YES mark is unchanged reported a phantom P&L of
    ``(yes_mark - no_entry) * (-qty)`` (e.g. (0.125 - 0.875) * (-100) =
    +75.5) instead of ~0.

    `side` is matched case-insensitively as defense-in-depth. The real
    guarantee is upstream: ``decisions.side`` carries a CHECK constraint
    admitting only the lowercase enum (m003_m1_ledger.py), so a ``'No'`` /
    ``'NO'`` side is rejected at write time and never reaches this pure
    function. The ``.lower()`` here keeps the math correct even if a future
    caller marks a position from a path that does not go through that
    constraint.
    """

    if side is not None and side.strip().lower() in _COMPLEMENT_SIDES:
        side_native_mark = 1.0 - snap_price
        return (side_native_mark - avg_entry_price) * abs(qty)
    return (snap_price - avg_entry_price) * qty


def remark_open_positions(
    conn: sqlite3.Connection,
) -> dict[str, float]:
    """Return the live read-layer re-mark of `unrealized_pnl` for every open
    position, keyed by position_id (trade-trace-pr2j).

    The `positions` projection only computes `unrealized_pnl` at rebuild time
    (`rebuild_positions` -> `_unrealized_pnl`, against whatever snapshot was
    latest then). A snapshot that lands AFTER the last rebuild therefore never
    refreshes the stored column, so a position can keep `unrealized_pnl=NULL`
    (opened before its first snapshot) or hold a value marked against an older
    snapshot even though a fresher mark exists.

    `report.open_positions` / `report.current_exposure` already reconcile this
    in their shared row builder (`_position_row_payload`) by recomputing from
    the latest mark. The other PnL-reading surfaces (`report.pnl`,
    `report.compare`, `review.bundle`) read `positions.unrealized_pnl`
    directly and so disagreed with the exposure surfaces. This function is the
    SINGLE shared read-layer re-mark those surfaces apply so every PnL surface
    reports the same number for the same open position.

    The re-mark uses the canonical side-aware convention (`_unrealized_pnl`,
    trade-trace-ctvb): the latest snapshot's YES-contract price is converted to
    the position's side-native terms before being differenced against the
    side-native `avg_entry_price`. Only open positions with a non-null
    `avg_entry_price`, a non-zero signed `net_quantity` derived from
    `position_events`, and at least one usable snapshot price for the
    instrument are re-marked; positions with no mark are simply absent from the
    returned map (the caller keeps treating them as unmarked).
    """

    rows = conn.execute(
        """
        WITH event_aggs AS (
            SELECT position_id, COALESCE(SUM(quantity_delta), 0) AS net_quantity
            FROM position_events
            GROUP BY position_id
        )
        SELECT p.id, p.instrument_id, p.side, p.avg_entry_price,
               COALESCE(ea.net_quantity, 0)
        FROM positions p
        LEFT JOIN event_aggs ea ON ea.position_id = p.id
        WHERE p.status = 'open' AND p.avg_entry_price IS NOT NULL
        """
    ).fetchall()

    marks: dict[str, float | None] = {}
    remarked: dict[str, float] = {}
    for position_id, instrument_id, side, avg_entry_price, net_quantity in rows:
        if net_quantity is None or _approx_zero(float(net_quantity)):
            continue
        if instrument_id not in marks:
            marks[instrument_id] = _latest_snapshot_price(conn, instrument_id)
        snap_price = marks[instrument_id]
        if snap_price is None:
            continue
        remarked[position_id] = _unrealized_pnl(
            side, snap_price, float(avg_entry_price), float(net_quantity)
        )
    return remarked


def _latest_snapshot_price(conn: sqlite3.Connection, instrument_id: str) -> float | None:
    row = conn.execute(
        """
        SELECT price FROM snapshots
        WHERE instrument_id = ? AND price IS NOT NULL
        ORDER BY captured_at DESC, id DESC
        LIMIT 1
        """,
        (instrument_id,),
    ).fetchone()
    return float(row[0]) if row is not None else None


def rebuild_memory_node_stats(conn: sqlite3.Connection) -> RebuildResult:
    """Rebuild `memory_node_stats` from `memory_recall_events`.

    The projection holds two columns — `recall_count` and
    `last_recalled_at` — derived by walking every event row's
    `node_ids_returned` JSON array. Per persistence.md §7, the rebuild
    is the source of truth: dropping the projection and replaying the
    events must yield byte-identical state.

    Inputs: `memory_recall_events.node_ids_returned` (JSON array of node
    ids in top-k order). Output rows: one per distinct node id ever
    surfaced in a recall result.
    """

    import json as _json

    dropped_row = conn.execute(
        "SELECT COUNT(*) FROM memory_node_stats"
    ).fetchone()
    dropped = int(dropped_row[0]) if dropped_row else 0
    conn.execute("DELETE FROM memory_node_stats")

    cur = conn.execute(
        "SELECT node_ids_returned, created_at FROM memory_recall_events "
        "ORDER BY id"
    )
    stats: dict[str, tuple[int, str]] = {}
    skipped_corrupt = 0
    for node_ids_json, created_at in cur.fetchall():
        try:
            node_ids = _json.loads(node_ids_json) or []
        except _json.JSONDecodeError:
            # Per trade-trace-iip4: don't fail the rebuild on a single
            # corrupt event row (recovery is the whole point of this
            # tool), but count the skip so the operator sees that the
            # rebuilt projection underrepresents the source events.
            skipped_corrupt += 1
            continue
        for node_id in node_ids:
            count, _last = stats.get(node_id, (0, ""))
            # last_recalled_at is the max created_at; since we walk in
            # ascending event-id order, the most-recent overwrite wins.
            stats[node_id] = (count + 1, created_at)

    rebuilt = 0
    for node_id, (count, last) in stats.items():
        conn.execute(
            "INSERT INTO memory_node_stats(node_id, recall_count, "
            "last_recalled_at) VALUES (?, ?, ?)",
            (node_id, count, last),
        )
        rebuilt += 1

    return RebuildResult(
        projection="memory_node_stats",
        dropped_rows=dropped,
        rebuilt_rows=rebuilt,
        skipped_corrupt_rows=skipped_corrupt,
    )
