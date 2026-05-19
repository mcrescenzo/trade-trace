"""`report.decision_velocity` per trade-trace-5ud.

Counts decisions over a time window grouped by bucket (day or week).
Useful for trend lines — "am I deciding more, fewer, or stalling?" —
and as a denominator for downstream reports like pnl coverage.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.reports._filter_support import (
    applied_filter_view,
    enforce_supported_filter,
)

_VALID_BUCKETS = ("day", "week")


def report_decision_velocity(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    bucket: str = "day",
) -> dict[str, Any]:
    """Return decision counts bucketed by day or week over the filter's
    `time_window.decision_at_*` window.

    Bucket boundaries are UTC-aligned (midnight UTC). A missing
    `decision_at_*` window defaults to the full DB range.
    """

    if bucket not in _VALID_BUCKETS:
        raise ValueError(f"bucket must be one of {_VALID_BUCKETS}, got {bucket!r}")

    rf = ReportFilter.model_validate(raw_filter or {})
    enforce_supported_filter(rf, report="report.decision_velocity")
    lo = rf.time_window.decision_at_gte
    hi = rf.time_window.decision_at_lt
    filter_view = applied_filter_view(rf, report="report.decision_velocity")

    where_clauses: list[str] = []
    params: list[Any] = []
    if lo is not None:
        where_clauses.append("created_at >= ?")
        params.append(lo)
    if hi is not None:
        where_clauses.append("created_at < ?")
        params.append(hi)
    decision_types = rf.decision.decision_type
    if decision_types:
        placeholders = ",".join("?" for _ in decision_types)
        where_clauses.append(f"type IN ({placeholders})")
        params.extend(decision_types)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    cur = conn.execute(
        f"SELECT id, created_at, type FROM decisions {where_sql} ORDER BY created_at ASC",
        params,
    )
    rows = cur.fetchall()

    buckets: dict[str, list[tuple[str, str]]] = {}
    for did, created_at, dtype in rows:
        key = _bucket_key(created_at, bucket=bucket)
        buckets.setdefault(key, []).append((did, dtype))

    groups: list[dict[str, Any]] = []
    for key in sorted(buckets):
        bucket_rows = buckets[key]
        groups.append({
            "key": key,
            "label": f"{bucket} starting {key}",
            "metrics": {
                "count": len(bucket_rows),
                "by_type": _count_by_type(bucket_rows),
            },
            "filter": filter_view,
            "record_ids": {"decisions": [r[0] for r in bucket_rows]},
            "examples": [],
            "sample_size": len(bucket_rows),
            "sample_warning": None,
            "truncated": False,
        })

    summary: dict[str, Any] = {
        "sample_size": len(rows),
        "sample_warning": None,
        "filter": filter_view,
        "metrics": {
            "total_decisions": len(rows),
            "bucket": bucket,
            "bucket_count": len(groups),
        },
        "caveats": [],
    }
    return {
        "summary": summary,
        "groups": groups,
        "bucket": bucket,
        "truncated": False,
        "next_cursor": None,
    }


def _bucket_key(created_at: str, *, bucket: str) -> str:
    """Return the canonical bucket label (UTC-aligned)."""

    ts = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(UTC)
    if bucket == "day":
        return ts.date().isoformat()
    # week: ISO week starting Monday
    monday = ts - timedelta(days=ts.weekday())
    return monday.date().isoformat()


def _count_by_type(rows: list[tuple[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _id, dtype in rows:
        counts[dtype] = counts.get(dtype, 0) + 1
    return counts
