"""`report.mistakes` and `report.strengths` per trade-trace-nxn.

Both reports group decisions by tag and surface recurring patterns:

- `mistakes` ranks tags by mean Brier of their scored forecasts (worst
  first); high mean = pattern is associated with poor calibration.
- `strengths` ranks tags by mean Brier (best first); low mean = pattern
  is associated with well-calibrated forecasts.

A tag falls below the report's `min_sample` (default 10 per reports.md
§3.2) is flagged via `sample_warning` but still ranked.

A tag with no scored forecasts is excluded from both aggregates — there's
no Brier to attribute, so it is neither a mistake nor a strength. This
covers both decisions without an attached `forecast_id` and decisions
whose forecast is not yet scored (open/pending). For surfaced (scored)
tags, the `record_ids[decisions]` list still enumerates the decisions in
each tag group so the agent can drill into the qualitative side. Mirrors
the scored-evidence gate that `report.mistake_tripwire` and
`report.coach` (top_mistakes/top_strengths) already apply.
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


_TAG_BRIER_ROWS_SQL = """
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
"""The decision_tags→decisions→forecast_scores join shared by the
mistakes / strengths ranked reports (and, via report.coach, both at
once). Pinned as a single string so the SQL is executed from exactly
one place — see `_load_tag_brier_rows`."""


def _load_tag_brier_rows(
    conn: sqlite3.Connection,
) -> list[tuple[str, str, str | None, float | None]]:
    """Run the tag→Brier join exactly once and return its raw rows.

    The mistakes and strengths reports differ only in the Python-side
    sort order and label string, so report.coach loads the rows once
    here and feeds them to both `_build_tag_ranked_report` orderings
    instead of paying for two identical DB round-trips (trade-trace-bg12).
    """

    return conn.execute(_TAG_BRIER_ROWS_SQL).fetchall()


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
    rows = _load_tag_brier_rows(conn)
    return _build_tag_ranked_report(
        rows,
        filter_view=filter_view,
        min_sample=min_sample,
        order=order,
        label=label,
    )


def _build_tag_ranked_report(
    rows: list[tuple[str, str, str | None, float | None]],
    *,
    filter_view: dict[str, Any],
    min_sample: int,
    order: str,
    label: str,
) -> dict[str, Any]:
    """Group, rank, and envelope already-loaded tag→Brier rows.

    Pure in-memory transform over `rows` (no DB access) so a single
    `_load_tag_brier_rows` call can build both the mistake-ranked
    (`order='desc'`) and strength-ranked (`order='asc'`) views from one
    query — see report.coach (trade-trace-bg12)."""

    by_tag: dict[str, list[tuple[str, str | None, float | None]]] = {}
    for tag, did, fid, score in rows:
        by_tag.setdefault(tag, []).append((did, fid, score))

    groups: list[dict[str, Any]] = []
    for tag, items in by_tag.items():
        scored = [s for (_d, _f, s) in items if s is not None]
        sample_size = len(scored)
        # A tag with no scored forecasts has no Brier to attribute, so it is
        # neither a recurring mistake nor a recurring strength — surfacing it
        # under either label is a false signal (and the same null-Brier tag
        # would otherwise appear identically in BOTH reports). Exclude it, in
        # line with this module's stated "there's no Brier to attribute"
        # exclusion and the sibling report.mistake_tripwire / report.coach
        # top_mistakes/top_strengths, which both gate on scored evidence.
        if sample_size == 0:
            continue
        decision_ids = sorted({d for (d, _f, _s) in items})
        forecast_ids = sorted({f for (_d, f, _s) in items if f is not None})
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
            # sample_size must count SCORED FORECASTS, not decisions, so it
            # agrees with sample_warning (which gates on the scored-forecast
            # count vs min_sample). Previously this was len(decision_ids),
            # making a tag with many decisions but few scored forecasts look
            # well-sampled while still carrying a low-N warning (trade-trace-1k5d).
            "sample_size": sample_size,
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

    # summary.sample_size counts UNIQUE SCORED FORECASTS across the whole
    # report, matching the per-group sample_size basis (scored forecasts) rather
    # than len(rows) — which over-counted every raw tag→decision join row,
    # including null-Brier rows that contribute no scored evidence
    # (trade-trace-1k5d). A forecast that carries multiple tags is counted once.
    scored_forecast_ids = {
        fid for (_tag, _did, fid, score) in rows if fid is not None and score is not None
    }
    summary: dict[str, Any] = {
        "sample_size": len(scored_forecast_ids),
        "sample_warning": None,
        "filter": filter_view,
        "metrics": {"tag_count": len(groups), "ordering": order, "label": label},
        "caveats": [],
    }
    return standard_report_result(summary=summary, groups=groups)


def load_mistakes_and_strengths(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_TAG_MIN_SAMPLE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the mistakes (desc) and strengths (asc) reports from ONE query.

    report.coach consumes both ranked views with the same filter; they
    differ only in Python-side sort order and label, so the underlying
    decision_tags→forecast_scores join is executed exactly once here and
    fed to both orderings (trade-trace-bg12). Each returned report is
    byte-for-byte identical to calling `report_mistakes` /
    `report_strengths` separately with the same `raw_filter`.

    Returns `(mistakes, strengths)`.
    """

    mistakes_filter_view = process_filter(
        ReportFilter.model_validate(raw_filter or {}), report="report.mistakes"
    )
    strengths_filter_view = process_filter(
        ReportFilter.model_validate(raw_filter or {}), report="report.strengths"
    )
    rows = _load_tag_brier_rows(conn)
    mistakes = _build_tag_ranked_report(
        rows,
        filter_view=mistakes_filter_view,
        min_sample=min_sample,
        order="desc",
        label="recurring mistakes",
    )
    strengths = _build_tag_ranked_report(
        rows,
        filter_view=strengths_filter_view,
        min_sample=min_sample,
        order="asc",
        label="recurring strengths",
    )
    return mistakes, strengths
