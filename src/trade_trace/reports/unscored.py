"""`report.unscored_forecasts` per trade-trace-5ud.

Enumerates pending binary forecasts past their `resolution_at` whose
instrument has no `resolved_final` (non-superseded) outcome. Same query
substrate as `signal.scan` for kind=`unscored_forecast` (trade-trace-2ry);
this report returns the rows directly so the agent can act on them.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.tools._helpers import now_iso


def report_unscored_forecasts(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the ReportResult envelope listing pending binary forecasts
    past their `resolution_at` without a resolved_final outcome."""

    rf = ReportFilter.model_validate(raw_filter or {})
    now = now_iso()
    cur = conn.execute(
        """
        SELECT f.id, f.thesis_id, f.resolution_at, t.instrument_id, f.created_at
        FROM forecasts f
        JOIN theses t ON t.id = f.thesis_id
        WHERE f.resolution_at IS NOT NULL
          AND f.resolution_at < ?
          AND f.scoring_state = 'pending'
          AND f.scoring_support = 'supported'
          AND NOT EXISTS (
            SELECT 1 FROM outcomes o
            WHERE o.instrument_id = t.instrument_id
              AND o.status = 'resolved_final'
              AND NOT EXISTS (
                SELECT 1 FROM edges e
                WHERE e.source_kind = 'outcome' AND e.target_kind = 'outcome'
                  AND e.edge_type = 'supersedes' AND e.target_id = o.id
              )
          )
        ORDER BY f.resolution_at ASC, f.id ASC
        """,
        (now,),
    )
    rows = cur.fetchall()
    forecast_ids = [r[0] for r in rows]
    instrument_ids = sorted({r[3] for r in rows})

    examples = [
        {
            "kind": "forecast",
            "id": r[0],
            "summary": (
                f"pending since resolution_at={r[2]} on instrument {r[3]}"
            ),
        }
        for r in rows[:3]
    ]

    summary: dict[str, Any] = {
        "sample_size": len(rows),
        "sample_warning": None,  # no threshold for this report
        "filter": rf.model_dump(),
        "metrics": {"unscored_count": len(rows), "as_of": now},
        "caveats": [],
    }
    groups = [
        {
            "key": "all",
            "label": "Forecasts past resolution_at with no resolved_final outcome",
            "metrics": {"unscored_count": len(rows)},
            "filter": rf.model_dump(),
            "record_ids": {
                "forecasts": forecast_ids,
                "instruments": instrument_ids,
            },
            "examples": examples,
            "sample_size": len(rows),
            "sample_warning": None,
            "truncated": False,
        }
    ]
    return {
        "summary": summary,
        "groups": groups,
        "as_of": now,
        "truncated": False,
        "next_cursor": None,
    }
