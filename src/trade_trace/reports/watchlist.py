"""`report.watchlist` per trade-trace-nxn.

Lists outstanding `watch`-type decisions. (The historical `watch.stale` name was rolled into this report; see trade-trace-ftnu.) The stale sub-mode
(reports.md naming) surfaces watches whose last update exceeds a
freshness threshold — "I said I'd revisit this and never did."

For MVP, a watch is "stale" when `now - decision.created_at >
stale_threshold_days` (default 14). Per bead trade-trace-gbtj,
watches now also carry first-class `review_by` deadlines: a watch is
`overdue` when `review_by <= as_of`. `stale` (age-based) and
`overdue` (deadline-based) are surfaced independently — the latter is
a per-row flag plus an `overdue_count` summary metric, so a stale
view still works for watches without a scheduled deadline.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import process_filter
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
    filter_view = process_filter(rf, report="report.watchlist")
    # Per bead trade-trace-bew: capture one clock instant at entry so
    # the stale threshold, per-row age_days, and the response's
    # `as_of` field all read from the same clock. Previously each
    # computation read the wall clock independently and a
    # microsecond-boundary cross between reads could flake the
    # exact-threshold tests. `now_iso()` honors the CLOCK_OVERRIDE
    # ContextVar used by the deterministic-replay fixture, so the
    # report stays deterministic under fixture seeding.
    as_of = now_iso()
    as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00")).astimezone(UTC)

    cur = conn.execute(
        "SELECT id, instrument_id, created_at, reason, review_by "
        "FROM decisions WHERE type = 'watch' ORDER BY created_at DESC"
    )
    rows = cur.fetchall()

    threshold_ts = None
    if stale:
        threshold_ts = as_of_dt - timedelta(days=stale_threshold_days)
        rows = [r for r in rows if _is_stale(r[2], threshold_ts)]

    groups = []
    overdue_count = 0
    for r in rows:
        is_overdue = _is_overdue(r[4], as_of_dt)
        if is_overdue:
            overdue_count += 1
        groups.append({
            "key": r[0],
            "label": f"watch on {r[1]}",
            "metrics": {
                "created_at": r[2],
                "review_by": r[4],
                "age_days": _age_days(r[2], now=as_of_dt),
                "overdue": is_overdue,
            },
            "filter": filter_view,
            "record_ids": {"decisions": [r[0]], "instruments": [r[1]]},
            "examples": [{"kind": "decision", "id": r[0],
                          "summary": r[3] or "(no reason)"}],
            "sample_size": 1,
            "sample_warning": None,
            "truncated": False,
        })

    summary: dict[str, Any] = {
        "sample_size": len(rows),
        "sample_warning": None,
        "filter": filter_view,
        "metrics": {
            "watch_count": len(rows),
            "overdue_count": overdue_count,
            "mode": "stale" if stale else "all",
            "stale_threshold_days": stale_threshold_days if stale else None,
        },
        "caveats": [],
    }
    return standard_report_result(
        summary=summary,
        groups=groups,
        extra={"as_of": as_of},
    )


def _age_days(created_at: str, *, now: datetime) -> float:
    ts = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(UTC)
    delta = now - ts
    return round(delta.total_seconds() / 86400, 3)


def _is_stale(created_at: str, threshold_ts: datetime) -> bool:
    ts = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(UTC)
    return ts < threshold_ts


def _is_overdue(review_by: str | None, as_of: datetime) -> bool:
    if not review_by:
        return False
    ts = datetime.fromisoformat(review_by.replace("Z", "+00:00")).astimezone(UTC)
    return ts <= as_of
