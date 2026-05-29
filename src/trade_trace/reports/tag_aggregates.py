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
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import process_filter

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
        report="report.mistakes",
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
        report="report.strengths",
    )


DEFAULT_TRIPWIRE_BRIER_THRESHOLD = 0.25
"""Mean-Brier bar above which a tag counts as a recurring mistake pattern.
0.25 is the Brier of an always-0.5 forecast; a tag worse than that has been
associated with systematically poor calibration."""


def report_mistake_tripwire(
    conn: sqlite3.Connection,
    *,
    tags: list[str],
    instrument_id: str | None = None,
    min_sample: int = DEFAULT_TAG_MIN_SAMPLE,
    brier_threshold: float = DEFAULT_TRIPWIRE_BRIER_THRESHOLD,
) -> dict[str, Any]:
    """Decision-time mistake trip-wire (trade-trace-4kec.10).

    Given the fingerprint (tag set) of a decision the agent is ABOUT to make,
    fire — unprompted, without an explicit recall query — the candidate tags
    that match the agent's own recurring-mistake patterns: tags whose prior
    scored forecasts have a mean Brier at or above `brier_threshold` over at
    least `min_sample` scored forecasts. Surfaces the prior failing
    decisions/forecasts so the agent sees the pattern before committing.
    Read-only, deterministic, no trade advice."""

    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("tags must be a list of strings")
    candidate = {t for t in tags if t}

    placeholders = ", ".join("?" for _ in candidate)
    where = [f"dt.tag IN ({placeholders})"] if candidate else ["0"]
    params: list[Any] = list(candidate)
    if instrument_id is not None:
        where.append("t.instrument_id = ?")
        params.append(instrument_id)
    rows = conn.execute(
        f"""
        SELECT dt.tag, d.id AS decision_id, d.forecast_id, fs.score
        FROM decision_tags dt
        JOIN decisions d ON d.id = dt.decision_id
        JOIN forecasts f ON f.id = d.forecast_id
        JOIN theses t ON t.id = f.thesis_id
        LEFT JOIN forecast_scores fs
          ON fs.forecast_id = d.forecast_id
          AND fs.score IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE e.source_kind = 'outcome' AND e.target_kind = 'outcome'
              AND e.edge_type = 'supersedes' AND e.target_id = fs.outcome_id
          )
        WHERE {' AND '.join(where)}
        """,
        params,
    ).fetchall()

    by_tag: dict[str, list[tuple[str, str | None, float | None]]] = {}
    for tag, did, fid, score in rows:
        by_tag.setdefault(tag, []).append((did, fid, score))

    groups: list[dict[str, Any]] = []
    for tag in sorted(by_tag):
        items = by_tag[tag]
        scored = [s for (_d, _f, s) in items if s is not None]
        sample_size = len(scored)
        if sample_size < min_sample:
            continue
        mean_brier = sum(scored) / sample_size
        if mean_brier < brier_threshold:
            continue
        decision_ids = sorted({d for (d, _f, _s) in items})
        forecast_ids = sorted({f for (_d, f, _s) in items if f is not None})
        groups.append({
            "key": tag,
            "label": f"Recurring mistake pattern on tag {tag!r}",
            "metrics": {
                "mean_brier": round(mean_brier, 6),
                "scored_forecast_count": sample_size,
                "threshold": brier_threshold,
            },
            "record_ids": {"decisions": decision_ids, "forecasts": forecast_ids},
            "examples": [
                {"kind": "decision", "id": d, "summary": f"prior decision tagged {tag!r}"}
                for d, _f, _s in items[:3]
            ],
            "sample_size": sample_size,
            "sample_warning": None,
            "truncated": False,
        })
    groups.sort(key=lambda g: g["metrics"]["mean_brier"], reverse=True)

    summary = {
        "triggered": bool(groups),
        "candidate_tags": sorted(candidate),
        "instrument_id": instrument_id,
        "match_count": len(groups),
        "brier_threshold": brier_threshold,
        "min_sample": min_sample,
        "caveats": [
            "Matches are the caller's own past poorly-calibrated tag patterns "
            "(mean Brier at or above the threshold); this is a calibration "
            "trip-wire, not trade advice, a signal, or an edge/profit claim.",
        ],
    }
    return standard_report_result(summary=summary, groups=groups)


def _tag_ranked_report(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None,
    min_sample: int,
    order: str,
    label: str,
    report: str,
) -> dict[str, Any]:
    rf = ReportFilter.model_validate(raw_filter or {})
    filter_view = process_filter(rf, report=report)

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
            "filter": filter_view,
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
        "filter": filter_view,
        "metrics": {"tag_count": len(by_tag), "ordering": order, "label": label},
        "caveats": [],
    }
    return standard_report_result(summary=summary, groups=groups)
