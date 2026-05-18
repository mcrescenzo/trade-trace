"""`report.watchlist` per trade-trace-nxn.

Lists outstanding `watch`-type decisions. The `watch.stale` sub-mode
(reports.md naming) surfaces watches whose last update exceeds a
freshness threshold — "I said I'd revisit this and never did."

For MVP, a watch is "stale" when `now - decision.created_at >
stale_threshold_days` (default 14). Future versions tie staleness to
periodic check-in events or per-watch SLA fields.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.tools._helpers import now_iso


DEFAULT_STALE_THRESHOLD_DAYS = 14


def report_watchlist(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    stale: bool = False,
    stale_threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS,
) -> dict[str, Any]:
    rf = ReportFilter.model_validate(raw_filter or {})
    cur = conn.execute(
        "SELECT id, instrument_id, created_at, reason, review_by "
        "FROM decisions WHERE type = 'watch' ORDER BY created_at DESC"
    )
    rows = cur.fetchall()

    threshold_ts = None
    if stale:
        threshold_ts = datetime.now(timezone.utc) - timedelta(days=stale_threshold_days)
        rows = [r for r in rows if _is_stale(r[2], threshold_ts)]

    groups = [
        {
            "key": r[0],
            "label": f"watch on {r[1]}",
            "metrics": {
                "created_at": r[2],
                "review_by": r[4],
                "age_days": _age_days(r[2]),
            },
            "filter": rf.model_dump(),
            "record_ids": {"decisions": [r[0]], "instruments": [r[1]]},
            "examples": [{"kind": "decision", "id": r[0],
                          "summary": r[3] or "(no reason)"}],
            "sample_size": 1,
            "sample_warning": None,
            "truncated": False,
        }
        for r in rows
    ]

    summary = {
        "sample_size": len(rows),
        "sample_warning": None,
        "filter": rf.model_dump(),
        "metrics": {
            "watch_count": len(rows),
            "mode": "stale" if stale else "all",
            "stale_threshold_days": stale_threshold_days if stale else None,
        },
        "caveats": [],
    }
    return {
        "summary": summary,
        "groups": groups,
        "as_of": now_iso(),
        "truncated": False,
        "next_cursor": None,
    }


def _age_days(created_at: str) -> float:
    ts = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    return round(delta.total_seconds() / 86400, 3)


def _is_stale(created_at: str, threshold_ts: datetime) -> bool:
    ts = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    return ts < threshold_ts
