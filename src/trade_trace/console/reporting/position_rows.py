"""Position detail read model for the reporting product
(trade-trace-bbww).

A `PositionDetail` carries everything the per-position audit page
(trade-trace-svp2) needs: the canonical projection row plus the full
`position_events` lineage, linked instrument data, the opening
decision's strategy/playbook, and explicit caveats for missing marks /
risk.

This module is read-only — all queries are SELECTs against the
positions + position_events + decisions tables.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from trade_trace.console.reporting.trade_rows import (
    CAVEAT_MISSING_RISK_BUDGET,
    CAVEAT_NO_STRATEGY,
)

CAVEAT_OPEN_NO_MARK = "open_no_mark"


@dataclass(frozen=True)
class PositionEvent:
    """One row from `position_events`, projected for the detail page."""

    id: str
    event_type: str
    quantity_delta: float | None
    price: float | None
    fees: float | None
    slippage: float | None
    created_at: str
    decision_id: str | None


@dataclass(frozen=True)
class PositionDetail:
    """Full lifecycle of one position. `events` lists every
    `position_events` row in chronological order; `caveats` lists
    machine-readable codes for missing-data states."""

    position_id: str
    instrument_id: str
    instrument_symbol: str | None
    instrument_title: str | None
    venue_id: str
    venue_kind: str
    kind: str  # 'paper' | 'actual' | 'simulation'
    side: str  # 'long' | 'short' | ...
    status: str  # 'open' | 'closed'
    opened_at: str
    closed_at: str | None
    realized_pnl: float | None
    unrealized_pnl: float | None
    avg_entry_price: float | None
    updated_at: str
    initial_risk_amount: float | None
    realized_r_multiple: float | None
    unrealized_r_multiple: float | None
    opening_decision_id: str | None
    opening_strategy_id: str | None
    opening_playbook_version_id: str | None
    events: tuple[PositionEvent, ...] = field(default_factory=tuple)
    caveats: tuple[str, ...] = field(default_factory=tuple)


def position_detail(conn: sqlite3.Connection, position_id: str) -> PositionDetail | None:
    """Return the full `PositionDetail` for `position_id`, or `None`
    if the position is unknown."""

    pos_row = conn.execute(
        """
        SELECT p.id, p.instrument_id, i.symbol, i.title, i.venue_id, v.kind,
               p.kind, p.side, p.status, p.opened_at, p.closed_at,
               p.realized_pnl, p.unrealized_pnl, p.avg_entry_price,
               p.updated_at, p.initial_risk_amount, p.realized_r_multiple,
               p.unrealized_r_multiple
        FROM positions p
        JOIN instruments i ON i.id = p.instrument_id
        JOIN venues v ON v.id = i.venue_id
        WHERE p.id = ?
        """,
        (position_id,),
    ).fetchone()
    if pos_row is None:
        return None

    event_rows = conn.execute(
        """
        SELECT id, event_type, quantity_delta, price, fees, slippage,
               created_at, decision_id
        FROM position_events
        WHERE position_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (position_id,),
    ).fetchall()
    events = tuple(
        PositionEvent(
            id=r[0], event_type=r[1],
            quantity_delta=float(r[2]) if r[2] is not None else None,
            price=float(r[3]) if r[3] is not None else None,
            fees=float(r[4]) if r[4] is not None else None,
            slippage=float(r[5]) if r[5] is not None else None,
            created_at=r[6], decision_id=r[7],
        )
        for r in event_rows
    )

    # The opening decision is the one referenced by the first event with
    # a decision_id (typically the 'open' event). Strategy/playbook on
    # that decision is the position's owner-of-record for reporting.
    opening_decision_id: str | None = None
    for ev in events:
        if ev.decision_id is not None:
            opening_decision_id = ev.decision_id
            break
    strategy_id: str | None = None
    playbook_version_id: str | None = None
    if opening_decision_id is not None:
        dec_row = conn.execute(
            "SELECT strategy_id, playbook_version_id, declared_risk_amount "
            "FROM decisions WHERE id = ?",
            (opening_decision_id,),
        ).fetchone()
        if dec_row is not None:
            strategy_id = dec_row[0]
            playbook_version_id = dec_row[1]

    status = pos_row[8]
    unrealized_pnl = pos_row[12]
    initial_risk_amount = pos_row[15]

    caveats: list[str] = []
    if status == "open" and unrealized_pnl is None:
        caveats.append(CAVEAT_OPEN_NO_MARK)
    if initial_risk_amount is None:
        caveats.append(CAVEAT_MISSING_RISK_BUDGET)
    if strategy_id is None:
        caveats.append(CAVEAT_NO_STRATEGY)

    return PositionDetail(
        position_id=pos_row[0],
        instrument_id=pos_row[1],
        instrument_symbol=pos_row[2],
        instrument_title=pos_row[3],
        venue_id=pos_row[4],
        venue_kind=pos_row[5],
        kind=pos_row[6],
        side=pos_row[7],
        status=status,
        opened_at=pos_row[9],
        closed_at=pos_row[10],
        realized_pnl=float(pos_row[11]) if pos_row[11] is not None else None,
        unrealized_pnl=float(unrealized_pnl) if unrealized_pnl is not None else None,
        avg_entry_price=float(pos_row[13]) if pos_row[13] is not None else None,
        updated_at=pos_row[14],
        initial_risk_amount=float(initial_risk_amount)
        if initial_risk_amount is not None else None,
        realized_r_multiple=float(pos_row[16]) if pos_row[16] is not None else None,
        unrealized_r_multiple=float(pos_row[17]) if pos_row[17] is not None else None,
        opening_decision_id=opening_decision_id,
        opening_strategy_id=strategy_id,
        opening_playbook_version_id=playbook_version_id,
        events=events,
        caveats=tuple(caveats),
    )
