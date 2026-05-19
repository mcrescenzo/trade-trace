"""`report.mistakes` and `report.strengths` per trade-trace-nxn.

Both reports group decisions by tag and surface recurring patterns:

- `mistakes` ranks tags by mean Brier of their scored forecasts (worst
  first); high mean = pattern is associated with poor calibration.
- `strengths` ranks tags by mean Brier (best first); low mean = pattern
  is associated with well-calibrated forecasts.

A tag falls below the report's `min_sample` (default 10 per reports.md
§3.2) is flagged via `sample_warning` but still ranked.

Decisions without an attached `forecast_id` are excluded from both
aggregates — there's no Brier to attribute. The `record_ids[decisions]`
list still enumerates the decisions in each tag group so the agent can
drill into the qualitative side.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter

DEFAULT_TAG_MIN_SAMPLE = 10


def report_mistakes(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_TAG_MIN_SAMPLE,
) -> dict[str, Any]:
    return _tag_ranked_report(
        conn, raw_filter=raw_filter, min_sample=min_sample,
        order="desc", label="recurring mistakes",
    )


def report_strengths(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_TAG_MIN_SAMPLE,
) -> dict[str, Any]:
    return _tag_ranked_report(
        conn, raw_filter=raw_filter, min_sample=min_sample,
        order="asc", label="recurring strengths",
    )


def _tag_ranked_report(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None,
    min_sample: int,
    order: str,
    label: str,
) -> dict[str, Any]:
    rf = ReportFilter.model_validate(raw_filter or {})

    rows = conn.execute(
        """
        SELECT dt.tag, d.id AS decision_id, d.forecast_id, fs.score
        FROM decision_tags dt
        JOIN decisions d ON d.id = dt.decision_id
        LEFT JOIN forecast_scores fs
          ON fs.forecast_id = d.forecast_id
          AND fs.score IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE e.source_kind = 'outcome' AND e.target_kind = 'outcome'
              AND e.edge_type = 'supersedes' AND e.target_id = fs.outcome_id
          )
        """
    ).fetchall()

    by_tag: dict[str, list[tuple[str, str | None, float | None]]] = {}
    for tag, did, fid, score in rows:
        by_tag.setdefault(tag, []).append((did, fid, score))

    groups: list[dict[str, Any]] = []
    for tag, items in by_tag.items():
        scored = [s for (_d, _f, s) in items if s is not None]
        decision_ids = sorted({d for (d, _f, _s) in items})
        forecast_ids = sorted({f for (_d, f, _s) in items if f is not None})
        sample_size = len(scored)
        mean_brier = sum(scored) / sample_size if sample_size else None
        sample_warning = (
            f"only {sample_size} scored forecasts on tag {tag!r}; "
            f"unreliable below {min_sample}"
        ) if sample_size and sample_size < min_sample else None
        groups.append({
            "key": tag,
            "label": f"Decisions tagged {tag!r}",
            "metrics": {
                "decision_count": len(decision_ids),
                "scored_forecast_count": sample_size,
                "mean_brier": (
                    round(mean_brier, 6) if mean_brier is not None else None
                ),
            },
            "filter": rf.model_dump(),
            "record_ids": {
                "decisions": decision_ids,
                "forecasts": forecast_ids,
            },
            "examples": [
                {"kind": "decision", "id": d, "summary": f"tag {tag!r}"}
                for d, _f, _s in items[:3]
            ],
            "sample_size": len(decision_ids),
            "sample_warning": sample_warning,
            "truncated": False,
        })

    reverse = (order == "desc")
    groups.sort(
        key=lambda g: (
            -1 if g["metrics"]["mean_brier"] is None else g["metrics"]["mean_brier"]
        ),
        reverse=reverse,
    )

    summary: dict[str, Any] = {
        "sample_size": len(rows),
        "sample_warning": None,
        "filter": rf.model_dump(),
        "metrics": {"tag_count": len(by_tag), "ordering": order, "label": label},
        "caveats": [],
    }
    return {
        "summary": summary,
        "groups": groups,
        "truncated": False,
        "next_cursor": None,
    }
