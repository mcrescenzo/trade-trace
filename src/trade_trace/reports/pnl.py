"""`report.pnl` per trade-trace-nxn.

Realized + unrealized P&L over the `positions` projection (rebuildable
per persistence.md §7 / trade-trace-5zg). Per-group metrics: realized,
unrealized, mark-to-market total, count of closed/open positions. Summary
metrics include open_mark_coverage (`open_positions_with_marks / open_positions`).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.projections import remark_open_positions
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import process_filter

DEFAULT_PNL_MIN_SAMPLE = 5
REPORT_NAME = "report.pnl"
REPORT_FILTER_SUPPORT: frozenset[str] = frozenset()


def _apply_open_remark(rows: list[tuple], remark: dict[str, float]) -> list[tuple]:
    """Replace each open row's stored `unrealized_pnl` (index 5) with the live
    read-layer re-mark when one exists (trade-trace-pr2j).

    Position id is at index 0; status at index 3. The re-mark is the same
    single source of truth `report.open_positions` / `report.current_exposure`
    apply, so every PnL surface counts a marked open position consistently and
    never reports null/stale unrealized P&L when a fresh mark exists.
    """

    if not remark:
        return rows
    patched: list[tuple] = []
    for row in rows:
        position_id = row[0]
        if row[3] == "open" and position_id in remark:
            row = (*row[:5], remark[position_id], *row[6:])
        patched.append(row)
    return patched


def _pnl_metrics_for_rows(rows: list[tuple]) -> dict[str, Any]:
    """Shared P&L aggregation kernel for report.pnl.

    Rows must expose position fields in this order:
    (id, instrument_id, kind, status, realized_pnl, unrealized_pnl, ...).
    """
    realized = sum(r[4] or 0.0 for r in rows)
    unrealized = sum(r[5] or 0.0 for r in rows if r[5] is not None)
    return {
        "realized_pnl": round(realized, 6),
        "unrealized_pnl": round(unrealized, 6),
        "mark_to_market_pnl": round(realized + unrealized, 6),
        "closed_count": sum(1 for r in rows if r[3] == "closed"),
        "open_count": sum(1 for r in rows if r[3] == "open"),
    }


def report_pnl(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_PNL_MIN_SAMPLE,
) -> dict[str, Any]:
    rf = ReportFilter.model_validate(raw_filter or {})
    filter_view = process_filter(rf, report=REPORT_NAME)
    cur = conn.execute(
        "SELECT id, instrument_id, kind, status, realized_pnl, unrealized_pnl "
        "FROM positions"
    )
    # Re-mark open positions from the latest snapshot before aggregating so
    # report.pnl agrees with report.open_positions / report.current_exposure
    # (trade-trace-pr2j). The stored projection column is only marked at
    # rebuild time and goes stale/null when a later snapshot lands.
    rows = _apply_open_remark(cur.fetchall(), remark_open_positions(conn))

    closed = [r for r in rows if r[3] == "closed"]
    open_ = [r for r in rows if r[3] == "open"]
    realized = sum(r[4] or 0.0 for r in rows)
    unrealized = sum(r[5] or 0.0 for r in rows if r[5] is not None)
    # Per bead trade-trace-9gs / DEBT-030: a position is "marked" when
    # it has an unrealized_pnl reading. That number only applies to
    # OPEN positions (closed positions don't carry a mark — they
    # have realized_pnl instead). Including closed rows in the
    # denominator made `data_coverage` misleading: a journal full of
    # cleanly closed positions would show low coverage even though
    # every relevant row was up to date.
    marked_open = sum(1 for r in open_ if r[5] is not None)
    open_mark_coverage = (marked_open / len(open_)) if open_ else 0.0

    sample_size = len(closed)
    sample_warning = (
        f"only {sample_size} closed positions; pnl trend is unreliable "
        f"below {min_sample}"
    ) if 0 < sample_size < min_sample else None

    by_instrument: dict[str, list[tuple]] = {}
    for r in rows:
        by_instrument.setdefault(r[1], []).append(r)

    groups: list[dict[str, Any]] = []
    for instr_id, items in by_instrument.items():
        groups.append({
            "key": instr_id,
            "label": f"Positions on {instr_id}",
            "metrics": _pnl_metrics_for_rows(items),
            "filter": filter_view,
            "record_ids": {"positions": [i[0] for i in items]},
            "examples": [
                {"kind": "position", "id": i[0],
                 "summary": f"{i[3]} on {i[1]}"} for i in items[:3]
            ],
            "sample_size": len(items),
            "sample_warning": None,
            "truncated": False,
        })

    summary: dict[str, Any] = {
        "sample_size": len(rows),
        "sample_warning": sample_warning,
        "filter": filter_view,
        "metrics": {
            "realized_pnl": round(realized, 6),
            "unrealized_pnl": round(unrealized, 6),
            "mark_to_market_pnl": round(realized + unrealized, 6),
            "closed_position_count": len(closed),
            "open_position_count": len(open_),
            "open_mark_coverage": round(open_mark_coverage, 6),
        },
        "caveats": [],
        "recommended_current_exposure_report": "report.current_exposure",
        "open_position_detail_report": "report.open_positions",
        "agent_answer_hint": (
            "P&L is a lower-level local projection report. For open trades/current exposure, run "
            "report.current_exposure; for row-level open-position detail, run report.open_positions. "
            "Trade Trace records local journal/projection state only and does not execute trades or prove broker portfolio truth."
        ),
    }
    return standard_report_result(summary=summary, groups=groups)
