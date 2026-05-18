"""`report.pnl` per trade-trace-nxn.

Realized + unrealized P&L over the `positions` projection (rebuildable
per persistence.md §7 / trade-trace-5zg). Per-group metrics: realized,
unrealized, mark-to-market total, count of closed positions, data
coverage (`positions_with_marks / total_positions`).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter


DEFAULT_PNL_MIN_SAMPLE = 5


def report_pnl(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_PNL_MIN_SAMPLE,
) -> dict[str, Any]:
    rf = ReportFilter.model_validate(raw_filter or {})
    cur = conn.execute(
        "SELECT id, instrument_id, kind, status, realized_pnl, unrealized_pnl "
        "FROM positions"
    )
    rows = cur.fetchall()

    closed = [r for r in rows if r[3] == "closed"]
    open_ = [r for r in rows if r[3] == "open"]
    realized = sum(r[4] or 0.0 for r in rows)
    unrealized = sum(r[5] or 0.0 for r in rows if r[5] is not None)
    marked = sum(1 for r in rows if r[5] is not None)
    coverage = (marked / len(rows)) if rows else 0.0

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
        ir = sum(i[4] or 0.0 for i in items)
        iu = sum(i[5] or 0.0 for i in items if i[5] is not None)
        groups.append({
            "key": instr_id,
            "label": f"Positions on {instr_id}",
            "metrics": {
                "realized_pnl": round(ir, 6),
                "unrealized_pnl": round(iu, 6),
                "mark_to_market_pnl": round(ir + iu, 6),
                "closed_count": sum(1 for i in items if i[3] == "closed"),
                "open_count": sum(1 for i in items if i[3] == "open"),
            },
            "filter": rf.model_dump(),
            "record_ids": {"positions": [i[0] for i in items]},
            "examples": [
                {"kind": "position", "id": i[0],
                 "summary": f"{i[3]} on {i[1]}"} for i in items[:3]
            ],
            "sample_size": len(items),
            "sample_warning": None,
            "truncated": False,
        })

    summary = {
        "sample_size": len(rows),
        "sample_warning": sample_warning,
        "filter": rf.model_dump(),
        "metrics": {
            "realized_pnl": round(realized, 6),
            "unrealized_pnl": round(unrealized, 6),
            "mark_to_market_pnl": round(realized + unrealized, 6),
            "closed_position_count": len(closed),
            "open_position_count": len(open_),
            "data_coverage": round(coverage, 6),
        },
        "caveats": [],
    }
    return {
        "summary": summary,
        "groups": groups,
        "truncated": False,
        "next_cursor": None,
    }
