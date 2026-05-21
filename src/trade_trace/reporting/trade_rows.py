"""Trade row enumeration + external detail helper for the reporting product
(trade-trace-bbww).

A *trade* per
[`docs/architecture/reporting-product.md`](../../../../docs/architecture/reporting-product.md)
§2 is a decision whose type opens, grows, reduces, or closes a position
(`actual_enter`, `paper_enter`, `add`, `actual_exit`, `paper_exit`,
`reduce`). `watch`/`skip`/`hold`/`invalidate_thesis` etc. are decisions
but not trades; they are excluded from `list_trades`.

The row shape pulls together fields scattered across `decisions`,
`instruments`, `venues`, `strategies`, plus aggregate counts for tags
and attached sources. Missing data is represented with named caveats
(per the bead acceptance "missing data is represented with caveats, not
silently zero-filled").

Pagination uses the shared cursor helper in
`trade_trace.reporting.pagination`.

`trade_detail(conn, decision_id)` is a supported exported Python
read-model API for callers that already have a database connection. It
is intentionally not wired as a Console HTTP endpoint or React route;
the shipped Console UI currently exposes the paginated trades list and
position/event/raw detail routes only.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from trade_trace.reporting.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Page,
    _decode_cursor,
    _encode_cursor,
)

TRADING_DECISION_TYPES: tuple[str, ...] = (
    "actual_enter",
    "actual_exit",
    "paper_enter",
    "paper_exit",
    "add",
    "reduce",
)
"""Decision types whose rows are counted as trades for the reporting
product. The matrix in `src/trade_trace/tools/decision_matrix.py` is
the source of truth; this set is the subset that moves a position.
Update both together if a new trading type is added."""

CAVEAT_MISSING_RISK_BUDGET = "missing_risk_budget"
CAVEAT_MISSING_PRICE = "missing_price"
CAVEAT_MISSING_QUANTITY = "missing_quantity"
CAVEAT_NO_STRATEGY = "no_strategy"
CAVEAT_NO_THESIS = "no_thesis"
CAVEAT_NO_SOURCES = "no_sources"

ALL_CAVEAT_CODES: tuple[str, ...] = (
    CAVEAT_MISSING_RISK_BUDGET,
    CAVEAT_MISSING_PRICE,
    CAVEAT_MISSING_QUANTITY,
    CAVEAT_NO_STRATEGY,
    CAVEAT_NO_THESIS,
    CAVEAT_NO_SOURCES,
)


@dataclass(frozen=True)
class TradeRow:
    """One trade-typed decision row, joined with instrument / venue /
    strategy data and per-decision aggregates.

    Every field is read-only. `caveats` carries machine-readable codes
    from `ALL_CAVEAT_CODES`; the UI maps them to copy via the metric
    glossary system (trade-trace-4nux).
    """

    decision_id: str
    decision_type: str
    decision_at: str
    instrument_id: str
    instrument_symbol: str | None
    instrument_title: str | None
    venue_id: str
    venue_kind: str
    side: str | None
    quantity: float | None
    price: float | None
    declared_risk_amount: float | None
    declared_risk_unit: str | None
    strategy_id: str | None
    strategy_slug: str | None
    playbook_version_id: str | None
    thesis_id: str | None
    actor_id: str
    agent_id: str | None
    tag_count: int
    source_count: int
    caveats: tuple[str, ...] = field(default_factory=tuple)


def _row_to_trade(row: tuple[Any, ...]) -> TradeRow:
    """Convert one SELECT row from `_TRADE_COLUMNS` to a `TradeRow`."""

    (
        decision_id, decision_type, decision_at, instrument_id,
        instrument_symbol, instrument_title, venue_id, venue_kind,
        side, quantity, price, declared_risk_amount, declared_risk_unit,
        strategy_id, strategy_slug, playbook_version_id, thesis_id,
        actor_id, agent_id, tag_count, source_count,
    ) = row

    caveats: list[str] = []
    if declared_risk_amount is None:
        caveats.append(CAVEAT_MISSING_RISK_BUDGET)
    if price is None:
        caveats.append(CAVEAT_MISSING_PRICE)
    if quantity is None:
        caveats.append(CAVEAT_MISSING_QUANTITY)
    if strategy_id is None:
        caveats.append(CAVEAT_NO_STRATEGY)
    if thesis_id is None:
        caveats.append(CAVEAT_NO_THESIS)
    if (source_count or 0) == 0:
        caveats.append(CAVEAT_NO_SOURCES)

    return TradeRow(
        decision_id=decision_id,
        decision_type=decision_type,
        decision_at=decision_at,
        instrument_id=instrument_id,
        instrument_symbol=instrument_symbol,
        instrument_title=instrument_title,
        venue_id=venue_id,
        venue_kind=venue_kind,
        side=side,
        quantity=float(quantity) if quantity is not None else None,
        price=float(price) if price is not None else None,
        declared_risk_amount=float(declared_risk_amount)
        if declared_risk_amount is not None else None,
        declared_risk_unit=declared_risk_unit,
        strategy_id=strategy_id,
        strategy_slug=strategy_slug,
        playbook_version_id=playbook_version_id,
        thesis_id=thesis_id,
        actor_id=actor_id,
        agent_id=agent_id,
        tag_count=int(tag_count or 0),
        source_count=int(source_count or 0),
        caveats=tuple(caveats),
    )


_TRADE_TYPES_PLACEHOLDERS = ",".join("?" * len(TRADING_DECISION_TYPES))

_TRADE_BASE_SQL = f"""
    SELECT
        d.id,
        d.type,
        d.created_at,
        d.instrument_id,
        i.symbol,
        i.title,
        i.venue_id,
        v.kind,
        d.side,
        d.quantity,
        d.price,
        d.declared_risk_amount,
        d.declared_risk_unit,
        d.strategy_id,
        s.slug,
        d.playbook_version_id,
        d.thesis_id,
        d.actor_id,
        d.agent_id,
        (SELECT COUNT(*) FROM decision_tags dt WHERE dt.decision_id = d.id) AS tag_count,
        (SELECT COUNT(*) FROM edges e
           WHERE e.target_kind = 'decision'
             AND e.target_id = d.id
             AND (
                 e.edge_type = 'cites'
                 OR (
                     e.source_kind = 'source'
                     AND e.edge_type IN ('about', 'supports', 'contradicts')
                 )
             )) AS source_count
    FROM decisions d
    JOIN instruments i ON i.id = d.instrument_id
    JOIN venues v ON v.id = i.venue_id
    LEFT JOIN strategies s ON s.id = d.strategy_id
    WHERE d.type IN ({_TRADE_TYPES_PLACEHOLDERS})
"""


def _multi(value: str | Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(item) for item in value if str(item))


def _date_range_bound(value: str, *, end: bool) -> str:
    """Expand date-only bounds from `<input type=date>` to ISO instants.

    Stored decision timestamps are ISO-ish strings. Comparing
    `created_at <= 'YYYY-MM-DD'` would exclude every record later on that
    selected calendar date, so date-only upper bounds must expand to the
    end of the day. Non-date-only values are preserved for callers that
    pass explicit timestamps.
    """

    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        return f"{value}T23:59:59.999999Z" if end else f"{value}T00:00:00.000000Z"
    return value


def list_trades(
    conn: sqlite3.Connection,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
    strategy_id: str | Sequence[str] | None = None,
    instrument_id: str | Sequence[str] | None = None,
    decision_type: str | Sequence[str] | None = None,
    opened_from: str | None = None,
    opened_to: str | None = None,
) -> Page:
    """Return a paginated page of `TradeRow` ordered newest first.

    Filters are intentionally narrow but may contain repeated values for
    strategy, instrument, and decision type. Date bounds accept either
    explicit timestamps or date-only `YYYY-MM-DD` values; date-only upper
    bounds are inclusive of the full selected calendar day.

    `decision_type` must be one of `TRADING_DECISION_TYPES` when set;
    a non-trading type is treated as "no rows" rather than an error
    so a caller cycling through filter values doesn't have to special-case
    the trading subset.
    """

    if limit < 1:
        limit = DEFAULT_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT

    decision_types = _multi(decision_type)
    if any(item not in TRADING_DECISION_TYPES for item in decision_types):
        return Page(rows=[], next_cursor=None, limit=limit, meta={"filter_match": "none"})

    sql = _TRADE_BASE_SQL
    params: list[Any] = list(TRADING_DECISION_TYPES)
    for column, values in (
        ("d.strategy_id", _multi(strategy_id)),
        ("d.instrument_id", _multi(instrument_id)),
        ("d.type", decision_types),
    ):
        if values:
            sql += f" AND {column} IN ({','.join('?' * len(values))})"
            params.extend(values)
    if opened_from is not None:
        sql += " AND d.created_at >= ?"
        params.append(_date_range_bound(opened_from, end=False))
    if opened_to is not None:
        sql += " AND d.created_at <= ?"
        params.append(_date_range_bound(opened_to, end=True))
    if cursor is not None:
        after = _decode_cursor(cursor)
        # The fixture seed runs under CLOCK_OVERRIDE so many decisions
        # share the same `created_at`. A pure `created_at` cursor would
        # skip siblings; the composite `(created_at, id)` lexicographic
        # cursor keeps the walk total.
        if not isinstance(after, list) or len(after) != 2:
            after_ts, after_id = after, ""
        else:
            after_ts, after_id = after
        sql += " AND (d.created_at < ? OR (d.created_at = ? AND d.id < ?))"
        params.extend([after_ts, after_ts, after_id])
    sql += " ORDER BY d.created_at DESC, d.id DESC LIMIT ?"
    params.append(limit + 1)

    rows = list(conn.execute(sql, tuple(params)))
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        # Composite cursor: [created_at, id] of the last returned row.
        last_row = rows[-1]
        next_cursor = _encode_cursor([last_row[2], last_row[0]])
    trade_rows = [_row_to_trade(r) for r in rows]
    return Page(rows=trade_rows, next_cursor=next_cursor, limit=limit)


def trade_detail(conn: sqlite3.Connection, decision_id: str) -> TradeRow | None:
    """Return one `TradeRow` by decision id for Python read-model callers.

    Returns `None` if the id is unknown or if the decision is not a
    trading type. This helper is exported from
    `trade_trace.reporting`; it is not a Console HTTP/UI route.
    """

    sql = _TRADE_BASE_SQL + " AND d.id = ?"
    params = (*TRADING_DECISION_TYPES, decision_id)
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_trade(row)
