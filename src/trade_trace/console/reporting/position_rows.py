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
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from trade_trace.console.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Page,
    _decode_cursor,
    _encode_cursor,
)
from trade_trace.console.reporting.metric_glossary import CaveatEntry, caveat_copy
from trade_trace.console.reporting.trade_rows import (
    CAVEAT_MISSING_RISK_BUDGET,
    CAVEAT_NO_STRATEGY,
)

CAVEAT_OPEN_NO_MARK = "open_no_mark"


@dataclass(frozen=True)
class PositionRow:
    """Slim scan row for the paginated positions index.

    Quantity and lifecycle counters are derived from append-only
    `position_events`; the mutable `positions` projection has no quantity
    column. `outcome` is a simple read-model category: open positions are
    `open`, closed rows with positive/negative/zero realized P&L are
    `win`/`loss`/`breakeven`, and closed rows without realized P&L are
    `unknown`.
    """

    position_id: str
    instrument_id: str
    instrument_symbol: str | None
    instrument_title: str | None
    venue_id: str
    venue_kind: str
    kind: str
    side: str
    status: str
    outcome: str
    opened_at: str
    closed_at: str | None
    realized_pnl: float | None
    unrealized_pnl: float | None
    avg_entry_price: float | None
    updated_at: str
    initial_risk_amount: float | None
    realized_r_multiple: float | None
    unrealized_r_multiple: float | None
    net_quantity: float
    add_count: int
    reduce_count: int
    event_count: int
    opening_decision_id: str | None
    opening_strategy_id: str | None
    opening_strategy_slug: str | None
    opening_playbook_version_id: str | None
    caveats: tuple[str, ...] = field(default_factory=tuple)
    caveat_entries: tuple[CaveatEntry, ...] = field(default_factory=tuple)


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


def _multi(value: str | Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(v for v in value if v is not None)


def _outcome(status: str, realized_pnl: Any) -> str:
    if status in {"open", "partial"}:
        return "open"
    if realized_pnl is None:
        return "unknown"
    pnl = float(realized_pnl)
    if pnl > 0:
        return "win"
    if pnl < 0:
        return "loss"
    return "breakeven"


def _caveats(*, status: str, unrealized_pnl: Any, initial_risk_amount: Any,
             strategy_id: str | None) -> tuple[str, ...]:
    caveats: list[str] = []
    if status == "open" and unrealized_pnl is None:
        caveats.append(CAVEAT_OPEN_NO_MARK)
    if initial_risk_amount is None:
        caveats.append(CAVEAT_MISSING_RISK_BUDGET)
    if strategy_id is None:
        caveats.append(CAVEAT_NO_STRATEGY)
    return tuple(caveats)


def _row_to_position(row: tuple[Any, ...]) -> PositionRow:
    (
        position_id, instrument_id, instrument_symbol, instrument_title,
        venue_id, venue_kind, kind, side, status, opened_at, closed_at,
        realized_pnl, unrealized_pnl, avg_entry_price, updated_at,
        initial_risk_amount, realized_r_multiple, unrealized_r_multiple,
        net_quantity, add_count, reduce_count, event_count,
        opening_decision_id, opening_strategy_id, opening_strategy_slug,
        opening_playbook_version_id,
    ) = row
    caveats = _caveats(
        status=status,
        unrealized_pnl=unrealized_pnl,
        initial_risk_amount=initial_risk_amount,
        strategy_id=opening_strategy_id,
    )
    entries = tuple(entry for code in caveats if (entry := caveat_copy(code)) is not None)
    return PositionRow(
        position_id=position_id,
        instrument_id=instrument_id,
        instrument_symbol=instrument_symbol,
        instrument_title=instrument_title,
        venue_id=venue_id,
        venue_kind=venue_kind,
        kind=kind,
        side=side,
        status=status,
        outcome=_outcome(status, realized_pnl),
        opened_at=opened_at,
        closed_at=closed_at,
        realized_pnl=float(realized_pnl) if realized_pnl is not None else None,
        unrealized_pnl=float(unrealized_pnl) if unrealized_pnl is not None else None,
        avg_entry_price=float(avg_entry_price) if avg_entry_price is not None else None,
        updated_at=updated_at,
        initial_risk_amount=float(initial_risk_amount) if initial_risk_amount is not None else None,
        realized_r_multiple=float(realized_r_multiple) if realized_r_multiple is not None else None,
        unrealized_r_multiple=float(unrealized_r_multiple) if unrealized_r_multiple is not None else None,
        net_quantity=float(net_quantity or 0),
        add_count=int(add_count or 0),
        reduce_count=int(reduce_count or 0),
        event_count=int(event_count or 0),
        opening_decision_id=opening_decision_id,
        opening_strategy_id=opening_strategy_id,
        opening_strategy_slug=opening_strategy_slug,
        opening_playbook_version_id=opening_playbook_version_id,
        caveats=caveats,
        caveat_entries=entries,
    )


_POSITION_BASE_SQL = """
    WITH event_aggs AS (
        SELECT position_id,
               COALESCE(SUM(quantity_delta), 0) AS net_quantity,
               SUM(CASE WHEN event_type = 'add' THEN 1 ELSE 0 END) AS add_count,
               SUM(CASE WHEN event_type = 'reduce' THEN 1 ELSE 0 END) AS reduce_count,
               COUNT(*) AS event_count
        FROM position_events
        GROUP BY position_id
    ), opening_events AS (
        SELECT pe.position_id, pe.decision_id
        FROM position_events pe
        WHERE pe.decision_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM position_events earlier
              WHERE earlier.position_id = pe.position_id
                AND earlier.decision_id IS NOT NULL
                AND (earlier.created_at < pe.created_at
                     OR (earlier.created_at = pe.created_at AND earlier.id < pe.id))
          )
    )
    SELECT p.id, p.instrument_id, i.symbol, i.title, i.venue_id, v.kind,
           p.kind, p.side, p.status, p.opened_at, p.closed_at,
           p.realized_pnl, p.unrealized_pnl, p.avg_entry_price,
           p.updated_at, p.initial_risk_amount, p.realized_r_multiple,
           p.unrealized_r_multiple,
           COALESCE(ea.net_quantity, 0), COALESCE(ea.add_count, 0),
           COALESCE(ea.reduce_count, 0), COALESCE(ea.event_count, 0),
           oe.decision_id, d.strategy_id, s.slug, d.playbook_version_id
    FROM positions p
    JOIN instruments i ON i.id = p.instrument_id
    JOIN venues v ON v.id = i.venue_id
    LEFT JOIN event_aggs ea ON ea.position_id = p.id
    LEFT JOIN opening_events oe ON oe.position_id = p.id
    LEFT JOIN decisions d ON d.id = oe.decision_id
    LEFT JOIN strategies s ON s.id = d.strategy_id
    WHERE 1 = 1
"""


def list_positions(
    conn: sqlite3.Connection,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
    status: str | Sequence[str] | None = None,
    kind: str | Sequence[str] | None = None,
    instrument_id: str | Sequence[str] | None = None,
    strategy_id: str | Sequence[str] | None = None,
    opened_from: str | None = None,
    opened_to: str | None = None,
    outcome: str | Sequence[str] | None = None,
) -> Page:
    """Return paginated `PositionRow`s ordered by opened_at DESC, id DESC."""

    if limit < 1:
        limit = DEFAULT_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT

    sql = _POSITION_BASE_SQL
    params: list[Any] = []
    for column, values in (
        ("p.status", _multi(status)),
        ("p.kind", _multi(kind)),
        ("p.instrument_id", _multi(instrument_id)),
        ("d.strategy_id", _multi(strategy_id)),
    ):
        if values:
            sql += f" AND {column} IN ({','.join('?' * len(values))})"
            params.extend(values)
    if opened_from is not None:
        sql += " AND p.opened_at >= ?"
        params.append(opened_from)
    if opened_to is not None:
        sql += " AND p.opened_at <= ?"
        params.append(opened_to)
    outcome_values = _multi(outcome)
    if outcome_values:
        outcome_expr = (
            "CASE "
            "WHEN p.status IN ('open','partial') THEN 'open' "
            "WHEN p.realized_pnl IS NULL THEN 'unknown' "
            "WHEN p.realized_pnl > 0 THEN 'win' "
            "WHEN p.realized_pnl < 0 THEN 'loss' "
            "ELSE 'breakeven' END"
        )
        sql += f" AND {outcome_expr} IN ({','.join('?' * len(outcome_values))})"
        params.extend(outcome_values)
    if cursor is not None:
        after = _decode_cursor(cursor)
        if not isinstance(after, list) or len(after) != 2:
            after_ts, after_id = after, ""
        else:
            after_ts, after_id = after
        sql += " AND (p.opened_at < ? OR (p.opened_at = ? AND p.id < ?))"
        params.extend([after_ts, after_ts, after_id])
    sql += " ORDER BY p.opened_at DESC, p.id DESC LIMIT ?"
    params.append(limit + 1)

    rows = list(conn.execute(sql, tuple(params)))
    position_rows = [_row_to_position(r) for r in rows]

    next_cursor: str | None = None
    if len(position_rows) > limit:
        position_rows = position_rows[:limit]
        last = position_rows[-1]
        next_cursor = _encode_cursor([last.opened_at, last.position_id])
    return Page(rows=position_rows, next_cursor=next_cursor, limit=limit)


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
