"""Calibration integrity diagnostics per bead trade-trace-jzn.

`report.calibration` reports the Brier/log-score/ECE panel, but those
numbers can look comforting on a dataset that is small, ambiguous, or
contaminated by post-hoc forecasts. This module emits six deterministic
*hygiene* diagnostics so the agent sees the same data the panel was
computed on — what the denominator is, what fraction is unsupported,
how many outcomes are ambiguous/disputed/void, and whether any forecasts
were filed *after* the outcome resolved.

The diagnostics are framed as coverage/hygiene warnings, not as accusations
of cheating (scoring.md §9): the goal is to make the calibration panel
honest about its denominator, not to second-guess intent. Per acceptance:

    (1) forecast_coverage      — decisions vs forecasts vs scored
    (2) unsupported_rate       — forecasts where scoring_support='unsupported'
    (3) ambiguous_rate         — outcomes.status='ambiguous'
    (4) disputed_rate          — outcomes.status='disputed'
    (5) void_cancelled_rate    — outcomes.status in (void, cancelled)
    (6) suspicious_late_rate   — forecasts.created_at > outcomes.resolved_at

Each diagnostic emits record-linked sample IDs (capped at MAX_SAMPLE_IDS)
so the agent can drill into the specific decisions/forecasts/outcomes
producing the metric. Empty databases surface `sample_warning="no_data"`.
"""

from __future__ import annotations

import sqlite3
from typing import Any

MAX_SAMPLE_IDS = 100
"""Cap for `sample_ids` per diagnostic to keep the envelope bounded;
the truncated flag fires when the underlying set exceeds the cap."""


def report_calibration_integrity(conn: sqlite3.Connection) -> dict[str, Any]:
    """Compute the six anti-goodhart diagnostics over the full journal.

    Returns the `data` portion of the report envelope. Per jzn acceptance,
    each diagnostic emits its own `{count, total, rate_pct, sample_ids,
    truncated}` block; the top-level `summary` aggregates denominator
    context. An empty journal returns zero counts with
    `summary.sample_warning="no_data"`.

    Filtering is NOT applied here — integrity diagnostics are intentionally
    *global*. Per-filter diagnostics would mask known dirty data behind a
    filter, defeating the hygiene purpose.
    """

    total_decisions = _count(conn, "SELECT COUNT(*) FROM decisions")
    total_forecasts = _count(conn, "SELECT COUNT(*) FROM forecasts")
    scored_forecasts = _count(
        conn,
        "SELECT COUNT(*) FROM forecast_scores WHERE score IS NOT NULL",
    )
    total_outcomes = _count(conn, "SELECT COUNT(*) FROM outcomes")

    forecast_coverage = _forecast_coverage(
        total_decisions=total_decisions,
        total_forecasts=total_forecasts,
        scored_forecasts=scored_forecasts,
    )
    unsupported = _rate_with_samples(
        conn,
        diagnostic="unsupported_rate",
        sample_sql=(
            "SELECT id FROM forecasts WHERE scoring_support = 'unsupported' "
            "ORDER BY created_at"
        ),
        total=total_forecasts,
        sample_kind="forecasts",
    )
    ambiguous = _rate_with_samples(
        conn,
        diagnostic="ambiguous_rate",
        sample_sql=(
            "SELECT id FROM outcomes WHERE status = 'ambiguous' "
            "ORDER BY resolved_at"
        ),
        total=total_outcomes,
        sample_kind="outcomes",
    )
    disputed = _rate_with_samples(
        conn,
        diagnostic="disputed_rate",
        sample_sql=(
            "SELECT id FROM outcomes WHERE status = 'disputed' "
            "ORDER BY resolved_at"
        ),
        total=total_outcomes,
        sample_kind="outcomes",
    )
    void_cancelled = _rate_with_samples(
        conn,
        diagnostic="void_cancelled_rate",
        sample_sql=(
            "SELECT id FROM outcomes WHERE status IN ('void','cancelled') "
            "ORDER BY resolved_at"
        ),
        total=total_outcomes,
        sample_kind="outcomes",
    )
    suspicious_late = _suspicious_late_rate(conn, total_forecasts=total_forecasts)
    abstention_coverage = _abstention_coverage(conn, total_forecasts=total_forecasts)

    sample_warning = "no_data" if (
        total_decisions == 0 and total_forecasts == 0 and total_outcomes == 0
    ) else None

    return {
        "summary": {
            "total_decisions": total_decisions,
            "total_forecasts": total_forecasts,
            "scored_forecasts": scored_forecasts,
            "total_outcomes": total_outcomes,
            "denominator_coverage_pct": forecast_coverage[
                "denominator_coverage_pct"
            ],
            "sample_warning": sample_warning,
        },
        "diagnostics": {
            "forecast_coverage": forecast_coverage,
            "unsupported_rate": unsupported,
            "ambiguous_rate": ambiguous,
            "disputed_rate": disputed,
            "void_cancelled_rate": void_cancelled,
            "suspicious_late_rate": suspicious_late,
            "abstention_coverage": abstention_coverage,
        },
    }


# -- helpers ----------------------------------------------------------


def _count(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row else 0


def _rate_pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 2)


def _forecast_coverage(
    *, total_decisions: int, total_forecasts: int, scored_forecasts: int,
) -> dict[str, Any]:
    """(1) forecast_coverage: scored vs total forecasts vs total decisions."""

    return {
        "total_decisions": total_decisions,
        "total_forecasts": total_forecasts,
        "scored_forecasts": scored_forecasts,
        "denominator_coverage_pct": _rate_pct(scored_forecasts, total_decisions),
        "sample_ids": {},  # forecast_coverage rolls up denominator context,
                            # not a sampled subset; per-record drilldown
                            # belongs in unsupported_rate or
                            # suspicious_late_rate.
        "truncated": False,
    }


def _rate_with_samples(
    conn: sqlite3.Connection,
    *,
    diagnostic: str,
    sample_sql: str,
    total: int,
    sample_kind: str,
) -> dict[str, Any]:
    rows = conn.execute(sample_sql).fetchall()
    sample_ids = [row[0] for row in rows]
    count = len(sample_ids)
    truncated = count > MAX_SAMPLE_IDS
    if truncated:
        sample_ids = sample_ids[:MAX_SAMPLE_IDS]
    return {
        "diagnostic": diagnostic,
        "count": count,
        "total": total,
        "rate_pct": _rate_pct(count, total),
        "sample_ids": {sample_kind: sample_ids},
        "truncated": truncated,
    }


def _suspicious_late_rate(
    conn: sqlite3.Connection, *, total_forecasts: int,
) -> dict[str, Any]:
    """(6) suspicious_late_rate: forecasts whose `created_at` is after the
    latest `resolved_final` outcome on the same instrument. The metric is
    a hygiene signal (post-hoc bias risk), not a fraud accusation. Mirrors
    the dogfood-protocol §2.2 late_recorded definition."""

    cur = conn.execute(
        """
        SELECT f.id
        FROM forecasts f
        JOIN theses t ON t.id = f.thesis_id
        JOIN outcomes o ON o.instrument_id = t.instrument_id
        WHERE o.status = 'resolved_final'
          AND f.created_at > o.resolved_at
        GROUP BY f.id
        ORDER BY f.id
        """
    )
    sample_ids = [row[0] for row in cur.fetchall()]
    count = len(sample_ids)
    truncated = count > MAX_SAMPLE_IDS
    if truncated:
        sample_ids = sample_ids[:MAX_SAMPLE_IDS]
    return {
        "diagnostic": "suspicious_late_rate",
        "count": count,
        "total": total_forecasts,
        "rate_pct": _rate_pct(count, total_forecasts),
        "sample_ids": {"forecasts": sample_ids},
        "truncated": truncated,
    }


def _abstention_coverage(
    conn: sqlite3.Connection, *, total_forecasts: int,
) -> dict[str, Any]:
    """Abstention + skip coverage (trade-trace-4kec.8, trade-trace-s7nn): how
    many considered-and-passed records exist alongside committed forecasts.
    Calibration metrics exclude both abstentions and skips by construction
    (neither is a scored forecast); surfacing them here lets the agent see the
    full considered set and judge survivorship bias.

    Two pass-surfaces, reconciled (trade-trace-s7nn). There are TWO documented
    ways an agent records "I considered this market and passed":

      * `abstention.record` -> a first-class `abstentions` row. This is the
        primary survivorship surface (migration m027).
      * `decision.add(type='skip')` -> a `decisions` row, the
        material-non-action path advertised by the decision matrix
        (x-material-non-action-taxonomy). A skip that carries NO linked
        forecast (`forecast_id IS NULL`) is unambiguously a considered-and-
        passed-without-forecasting event that never enters calibration —
        exactly the survivorship hazard this control exists to surface. (A
        skip that DOES link a forecast is already represented through the
        forecast denominator and through forecast_coverage, so it is not
        re-counted here.)

    To avoid double-counting markets that carry BOTH a skip and an
    abstention.record, the two surfaces are reported as DISTINCT lines:
      * `count` / `abstention_share_pct` describe abstentions only (the
        primary surface; unchanged shape for existing consumers).
      * `skip_coverage` describes forecast-less skip decisions only.
      * `considered_total_dedup` is the de-duplicated union denominator:
        forecasts + abstention instruments + forecast-less-skip instruments
        that are not already counted via an abstention, so a market with both
        surfaces contributes once.

    `abstention_share_pct` remains abstentions / (forecasts + abstentions) for
    backward compatibility; `considered_share_pct` is the honest pass-surface
    share over the de-duplicated union."""

    if not _table_exists(conn, "abstentions"):
        abstentions = 0
        sample_ids: list[str] = []
        abstention_instruments: set[str] = set()
    else:
        rows = conn.execute(
            "SELECT id, instrument_id FROM abstentions ORDER BY created_at, id"
        ).fetchall()
        sample_ids = [row[0] for row in rows]
        abstention_instruments = {row[1] for row in rows if row[1] is not None}
        abstentions = len(sample_ids)
    truncated = abstentions > MAX_SAMPLE_IDS
    if truncated:
        sample_ids = sample_ids[:MAX_SAMPLE_IDS]

    skip_coverage = _skip_coverage(conn)

    considered_total = total_forecasts + abstentions

    # De-duplicated union denominator: count each pass surface once. A
    # forecast-less skip on an instrument that ALSO has an abstention.record is
    # the same "I passed on this market" event recorded twice across surfaces;
    # count it once (under the abstention) so the share is not inflated.
    skip_only_instruments = skip_coverage["_instruments"] - abstention_instruments
    considered_passes_dedup = abstentions + len(skip_only_instruments)
    considered_total_dedup = total_forecasts + considered_passes_dedup
    skip_coverage = {k: v for k, v in skip_coverage.items() if k != "_instruments"}

    return {
        "diagnostic": "abstention_coverage",
        "count": abstentions,
        "total": considered_total,
        "abstention_share_pct": _rate_pct(abstentions, considered_total),
        "sample_ids": {"abstentions": sample_ids},
        "truncated": truncated,
        "skip_coverage": skip_coverage,
        "considered_passes_dedup": considered_passes_dedup,
        "considered_total_dedup": considered_total_dedup,
        "considered_share_pct": _rate_pct(
            considered_passes_dedup, considered_total_dedup
        ),
    }


def _skip_coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    """Forecast-less `decision.add(type='skip')` rows — the second
    considered-and-passed surface (trade-trace-s7nn). A skip without a linked
    forecast never enters calibration, so it is a survivorship-relevant pass
    that `abstention.record` alone misses. Skips WITH a linked forecast are
    excluded here (the forecast already carries them into the calibration
    denominator and forecast_coverage)."""

    rows = conn.execute(
        "SELECT id, instrument_id FROM decisions "
        "WHERE type = 'skip' AND forecast_id IS NULL "
        "ORDER BY created_at, id"
    ).fetchall()
    decision_ids = [row[0] for row in rows]
    instruments = {row[1] for row in rows if row[1] is not None}
    count = len(decision_ids)
    truncated = count > MAX_SAMPLE_IDS
    sample_ids = decision_ids[:MAX_SAMPLE_IDS] if truncated else decision_ids
    return {
        "diagnostic": "skip_coverage",
        "count": count,
        "sample_ids": {"decisions": sample_ids},
        "truncated": truncated,
        "_instruments": instruments,
    }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


__all__ = ["MAX_SAMPLE_IDS", "report_calibration_integrity"]
