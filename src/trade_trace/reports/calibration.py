"""`report.calibration` aggregate per trade-trace-0rk + scoring.md §7.

Substrate for the remaining 6 reports — pins the ReportResult envelope
shape (summary + groups[] + meta) and the late-recorded exclusion default
(dogfood-protocol.md §2.2).
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from trade_trace.contracts.report_filter import STRATEGY_NONE_SENTINEL, ReportFilter
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import (
    applied_filter_view,
    enforce_supported_filter,
)

REPORT_NAME = "report.calibration"
"""Module-level report name (trade-trace-x0po / SIMP-007). Pinning the
name once removes the drift risk of three separate string literals
disagreeing on the report's identity."""


DEFAULT_MIN_SAMPLE = 20
"""Per reports.md §3.2 / scoring.md §7.1: N=20 is the calibration floor."""

DEFAULT_BIN_POLICY = "equal_mass"
"""Reliability-bin policy. Equal-mass bins are the v0.0.2 calibration default."""

LOG_EPS = 1e-9


@dataclass
class _ScoredRow:
    """A single forecast_scores row resolved against its YES probability and
    realized indicator. The substrate for every metric below."""

    forecast_id: str
    score_id: str
    outcome_id: str
    p_yes: float
    y: int  # 0 or 1
    late_recorded: bool
    baseline_probability: float | None = None


def report_calibration(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    """Compute the calibration metric panel over scored binary forecasts in
    the filtered set. Returns the `data` portion of the success envelope —
    the MCP/CLI adapter wraps it with `meta`.

    `raw_filter` is a dict (likely the agent's `ReportFilter` shape) which
    gets validated by the Pydantic model; unknown fields surface as
    `pydantic.ValidationError` (the dispatcher catches and translates).
    """

    rf = ReportFilter.model_validate(raw_filter or {})
    enforce_supported_filter(rf, report=REPORT_NAME)
    rows = _load_scored_rows(conn, rf)

    # Late-recorded default exclusion (dogfood-protocol.md §2.2).
    if rf.outcome.include_late_recorded:
        excluded_late = 0
        included_rows = rows
    else:
        excluded_late = sum(1 for r in rows if r.late_recorded)
        included_rows = [r for r in rows if not r.late_recorded]

    sample_size = len(included_rows)
    sample_warning = None
    caveats: list[str] = []
    if excluded_late > 0:
        caveats.append(
            f"excluded {excluded_late} late-recorded forecast(s) per "
            "dogfood-protocol.md §2.2; pass outcome.include_late_recorded=true to include."
        )
    if sample_size < min_sample:
        sample_warning = (
            f"only {sample_size} scored forecasts; calibration is "
            f"unreliable below {min_sample}"
        )

    metrics = _compute_metrics(included_rows) if included_rows else _empty_metrics()
    metrics["late_recorded_excluded"] = excluded_late

    group_record_ids = {
        "forecasts": sorted({r.forecast_id for r in included_rows}),
        "forecast_scores": sorted({r.score_id for r in included_rows}),
        "outcomes": sorted({r.outcome_id for r in included_rows}),
    }
    truncated = False
    max_ids = 1000
    for key, ids in group_record_ids.items():
        if len(ids) > max_ids:
            group_record_ids[key] = ids[:max_ids]
            truncated = True

    summary = {
        "sample_size": sample_size,
        "sample_warning": sample_warning,
        "filter": applied_filter_view(rf, report=REPORT_NAME),
        "metrics": metrics,
        "caveats": caveats,
        "late_recorded_excluded": excluded_late,
    }
    groups = [
        {
            "key": "all",
            "label": "All scored binary forecasts in filter",
            "metrics": metrics,
            "filter": applied_filter_view(rf, report=REPORT_NAME),
            "record_ids": group_record_ids,
            "examples": _build_examples(conn, included_rows, max_examples=3),
            "sample_size": sample_size,
            "sample_warning": sample_warning,
            "truncated": truncated,
        }
    ]
    return standard_report_result(
        summary=summary,
        groups=groups,
        extra={"bin_policy": DEFAULT_BIN_POLICY},
        # Per bead trade-trace-zgz: top-level truncated must reflect any
        # truncated group so envelope meta.truncated does not under-report
        # capped data (the dispatcher copies this onto ctx.meta_hints).
        truncated=any(g.get("truncated") for g in groups),
    )



def report_calibration_anchored(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    return _market_baseline_report(conn, raw_filter=raw_filter, min_sample=min_sample, mode="anchored")


def report_calibration_terminal(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    return _market_baseline_report(conn, raw_filter=raw_filter, min_sample=min_sample, mode="terminal")


ADVISORY_REPORT_NAME = "report.calibration_advisory"
"""Forward-facing, decision-time recalibration surface (trade-trace-4kec.7).

Unlike the backward-facing `report.calibration*` panels, this answers a
prospective question: "given a forecast I am about to commit at probability p,
how did my past forecasts in this band actually resolve, and what calibration
adjustment does that imply?" It is read-only, deterministic, and emits no trade
advice — only the caller's own historical resolution rate and the
calibration-derived recalibration of the candidate probability."""


def _band_for_probability(probability: float) -> dict[str, Any]:
    """Equal-width 0.1 band the candidate probability falls into, matching the
    `equal_width_0.1` reliability-bin assignment in `_ece_and_bins`
    (lower edge belongs to the upper bin; the top band is closed on the right)."""

    idx = min(int(probability * 10), 9)
    lower = idx / 10.0
    upper = (idx + 1) / 10.0
    return {
        "bin_index": idx,
        "lower": lower,
        "upper": upper,
        "bin_midpoint": (lower + upper) / 2.0,
    }


def report_calibration_advisory(
    conn: sqlite3.Connection,
    *,
    probability: Any,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    """Decision-time recalibration for a candidate forecast probability.

    Returns the caller's historical resolution rate for the equal-width 0.1
    band the candidate falls into, plus a calibration-derived adjustment hint
    (`observed_frequency - mean_probability` in that band) and the resulting
    `suggested_probability`. Deterministic and read-only; no trade advice."""

    if not isinstance(probability, (int, float)) or isinstance(probability, bool):
        raise ValueError("probability must be a number in [0, 1]")
    if not (0.0 <= float(probability) <= 1.0):
        raise ValueError("probability must be in [0, 1]")
    probability = float(probability)

    rf = ReportFilter.model_validate(raw_filter or {})
    enforce_supported_filter(rf, report=ADVISORY_REPORT_NAME)
    rows = _load_scored_rows(conn, rf)
    if rf.outcome.include_late_recorded:
        excluded_late = 0
    else:
        excluded_late = sum(1 for r in rows if r.late_recorded)
        rows = [r for r in rows if not r.late_recorded]

    band = _band_for_probability(probability)
    band_rows = [r for r in rows if min(int(r.p_yes * 10), 9) == band["bin_index"]]

    sample_size = len(band_rows)
    caveats: list[str] = [
        "Recalibration is derived only from the caller's own past resolved "
        "forecasts in this probability band; it is not trade advice, a signal, "
        "or an edge/profit claim.",
    ]
    if excluded_late > 0:
        caveats.append(
            f"excluded {excluded_late} late-recorded forecast(s) per "
            "dogfood-protocol.md §2.2; pass outcome.include_late_recorded=true to include."
        )

    observed_frequency: float | None
    mean_probability: float | None
    calibration_gap: float | None
    suggested_probability: float | None
    sample_warning: str | None
    if sample_size == 0:
        observed_frequency = None
        mean_probability = None
        calibration_gap = None
        suggested_probability = None
        sample_warning = (
            f"no prior resolved forecasts in band {band['lower']}–{band['upper']}; "
            "no calibration adjustment available"
        )
    else:
        observed_frequency = sum(r.y for r in band_rows) / sample_size
        mean_probability = sum(r.p_yes for r in band_rows) / sample_size
        calibration_gap = observed_frequency - mean_probability
        suggested_probability = min(1.0, max(0.0, probability + calibration_gap))
        sample_warning = (
            f"only {sample_size} prior forecast(s) in this band; recalibration "
            f"is unreliable below {min_sample}"
            if sample_size < min_sample
            else None
        )

    summary = {
        "probability": probability,
        "band": band,
        "sample_size": sample_size,
        "observed_frequency": (
            round(observed_frequency, 6) if observed_frequency is not None else None
        ),
        "mean_probability": (
            round(mean_probability, 6) if mean_probability is not None else None
        ),
        "calibration_gap": (
            round(calibration_gap, 6) if calibration_gap is not None else None
        ),
        "suggested_probability": (
            round(suggested_probability, 6) if suggested_probability is not None else None
        ),
        "suggested_adjustment": (
            round(calibration_gap, 6) if calibration_gap is not None else None
        ),
        "filter": applied_filter_view(rf, report=ADVISORY_REPORT_NAME),
        "sample_warning": sample_warning,
        "caveats": caveats,
        "late_recorded_excluded": excluded_late,
    }
    record_ids = {
        "forecasts": sorted({r.forecast_id for r in band_rows}),
        "forecast_scores": sorted({r.score_id for r in band_rows}),
        "outcomes": sorted({r.outcome_id for r in band_rows}),
    }
    groups = [
        {
            "key": f"band_{band['bin_index']}",
            "label": (
                f"Prior resolved forecasts in probability band "
                f"{band['lower']}–{band['upper']}"
            ),
            "metrics": {
                "sample_size": sample_size,
                "observed_frequency": summary["observed_frequency"],
                "mean_probability": summary["mean_probability"],
                "calibration_gap": summary["calibration_gap"],
                "suggested_probability": summary["suggested_probability"],
            },
            "filter": applied_filter_view(rf, report=ADVISORY_REPORT_NAME),
            "record_ids": record_ids,
            "examples": _build_examples(conn, band_rows, max_examples=3),
            "sample_size": sample_size,
            "sample_warning": sample_warning,
            "truncated": False,
        }
    ]
    return standard_report_result(
        summary=summary,
        groups=groups,
        extra={"bin_policy": "equal_width_0.1"},
    )


def _market_baseline_report(conn: sqlite3.Connection, *, raw_filter: dict[str, Any] | None, min_sample: int, mode: str) -> dict[str, Any]:
    rf = ReportFilter.model_validate(raw_filter or {})
    enforce_supported_filter(rf, report=f"report.calibration_{mode}")
    all_rows, unanchored = _load_market_baseline_rows(conn, rf, mode=mode)
    if rf.outcome.include_late_recorded:
        excluded_late = 0
        rows = all_rows
    else:
        excluded_late = sum(1 for r in all_rows if r.late_recorded)
        rows = [r for r in all_rows if not r.late_recorded]
    sample_size = len(rows)
    sample_warning = None if sample_size >= min_sample else f"only {sample_size} scored forecasts; calibration is unreliable below {min_sample}"
    metrics = _compute_metrics(rows) if rows else _empty_metrics()
    metrics["late_recorded_excluded"] = excluded_late
    metrics["unanchored_forecast_count"] = unanchored
    caveats = []
    if unanchored:
        caveats.append(f"{unanchored} scored forecast(s) lacked a {mode} market baseline and were excluded from market-baseline metrics.")
    summary = {"sample_size": sample_size, "sample_warning": sample_warning, "filter": applied_filter_view(rf, report=f"report.calibration_{mode}"), "metrics": metrics, "caveats": caveats, "late_recorded_excluded": excluded_late, "unanchored_forecast_count": unanchored}
    groups = [{"key": "all", "label": f"All scored binary forecasts with {mode} market baseline", "metrics": metrics, "filter": summary["filter"], "record_ids": {"forecasts": sorted({r.forecast_id for r in rows}), "forecast_scores": sorted({r.score_id for r in rows}), "outcomes": sorted({r.outcome_id for r in rows})}, "examples": _build_examples(conn, rows, max_examples=3), "sample_size": sample_size, "sample_warning": sample_warning, "truncated": False}]
    return standard_report_result(summary=summary, groups=groups, extra={"bin_policy": DEFAULT_BIN_POLICY, "baseline_mode": mode})


def _load_market_baseline_rows(conn: sqlite3.Connection, rf: ReportFilter, *, mode: str) -> tuple[list[_ScoredRow], int]:
    base = _load_scored_rows(conn, rf)
    if not base:
        return [], 0
    score_ids = [r.score_id for r in base]
    forecast_ids = [r.forecast_id for r in base]
    probabilities: dict[str, float] = {}
    if mode == "anchored":
        rows = conn.execute(
            f"""
            SELECT forecast_id, market_implied_probability
            FROM forecast_snapshot_anchor
            WHERE forecast_id IN ({_placeholders(len(forecast_ids))})
              AND market_implied_probability IS NOT NULL
            """,
            forecast_ids,
        ).fetchall()
        anchor_probs = {str(forecast_id): float(prob) for forecast_id, prob in rows}
        probabilities = {r.score_id: anchor_probs[r.forecast_id] for r in base if r.forecast_id in anchor_probs}
    else:
        rows = conn.execute(
            f"""
            WITH terminal_candidates AS (
                SELECT fs.id AS score_id,
                       s.implied_probability,
                       ROW_NUMBER() OVER (
                           PARTITION BY fs.id
                           ORDER BY s.captured_at DESC, s.created_at DESC, s.id DESC
                       ) AS rn
                FROM forecast_scores fs
                JOIN forecasts f ON f.id = fs.forecast_id
                JOIN outcomes o ON o.id = fs.outcome_id
                JOIN snapshots s ON s.instrument_id = f.market_id
                WHERE fs.id IN ({_placeholders(len(score_ids))})
                  AND s.implied_probability IS NOT NULL
                  AND (o.resolved_at IS NULL OR s.captured_at <= o.resolved_at)
            )
            SELECT score_id, implied_probability
            FROM terminal_candidates
            WHERE rn = 1
            """,
            score_ids,
        ).fetchall()
        probabilities = {str(score_id): float(prob) for score_id, prob in rows}
    output: list[_ScoredRow] = []
    missing = 0
    for r in base:
        prob = probabilities.get(r.score_id)
        if prob is None:
            missing += 1
            continue
        output.append(_ScoredRow(r.forecast_id, r.score_id, r.outcome_id, r.p_yes, r.y, r.late_recorded, float(prob)))
    return output, missing

# -- data loading --------------------------------------------------------


def _scored_row_base_where() -> list[str]:
    """The base WHERE clauses every scored-row loader applies
    (trade-trace-qnxt). Shared between `_load_scored_rows` (calibration)
    and `_load_grouped_scored_rows` (compare). Returns a fresh list so
    callers can extend it freely."""

    return [
        "fs.metric = 'brier_binary'",
        "fs.score IS NOT NULL",
        "f.kind = 'binary'",
        """NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE e.source_kind = 'outcome' AND e.target_kind = 'outcome'
              AND e.edge_type = 'supersedes' AND e.target_id = o.id
          )""",
    ]


def _apply_scored_row_filters(
    rf: ReportFilter,
    where: list[str],
    params: list[Any],
    *,
    include_late_recorded_predicate: bool = False,
) -> None:
    """Append the ReportFilter-driven WHERE clauses both scored-row
    loaders share (trade-trace-qnxt). Mutates `where` and `params` in
    place to match the original inline behavior."""

    if rf.actors.actor_id:
        where.append(f"f.actor_id IN ({_placeholders(len(rf.actors.actor_id))})")
        params.extend(rf.actors.actor_id)
    if rf.actors.agent_id:
        where.append(f"f.agent_id IN ({_placeholders(len(rf.actors.agent_id))})")
        params.extend(rf.actors.agent_id)
    if rf.actors.model_id:
        where.append(f"f.model_id IN ({_placeholders(len(rf.actors.model_id))})")
        params.extend(rf.actors.model_id)
    if rf.actors.environment:
        where.append(f"f.environment IN ({_placeholders(len(rf.actors.environment))})")
        params.extend(rf.actors.environment)
    if rf.actors.run_id:
        where.append(f"f.run_id IN ({_placeholders(len(rf.actors.run_id))})")
        params.extend(rf.actors.run_id)
    if rf.instrument.venue_id:
        where.append(f"i.venue_id IN ({_placeholders(len(rf.instrument.venue_id))})")
        params.extend(rf.instrument.venue_id)
    if rf.strategy.strategy_id is not None:
        if rf.strategy.strategy_id == STRATEGY_NONE_SENTINEL:
            where.append("t.strategy_id IS NULL")
        else:
            where.append("t.strategy_id = ?")
            params.append(rf.strategy.strategy_id)
    if include_late_recorded_predicate and not rf.outcome.include_late_recorded:
        where.append(
            "COALESCE(json_extract(fs.metadata_json, '$.late_recorded'), 0) = 0"
        )


def _materialize_scored_row(
    conn: sqlite3.Connection,
    *,
    score_id: str,
    forecast_id: str,
    outcome_id: str,
    metadata_json: str | None,
    yes_label: str | None,
    outcome_label: str | None,
    baseline_probability: float | None = None,
) -> _ScoredRow | None:
    """Shared post-fetch reconstruction (trade-trace-qnxt). Returns None
    when the p_yes/y pair can't be resolved (the original loaders both
    `continue`d in that case)."""

    try:
        meta = json.loads(metadata_json or "{}")
    except json.JSONDecodeError:
        meta = {}
    late = bool(meta.get("late_recorded"))
    p_yes, y = _resolve_p_yes_and_y(
        conn,
        forecast_id=forecast_id,
        yes_label=yes_label,
        outcome_label=outcome_label,
    )
    if p_yes is None or y is None:
        return None
    return _ScoredRow(
        forecast_id=forecast_id,
        score_id=score_id,
        outcome_id=outcome_id,
        p_yes=p_yes,
        y=y,
        late_recorded=late,
        baseline_probability=baseline_probability,
    )


def _load_scored_rows(conn: sqlite3.Connection, rf: ReportFilter) -> list[_ScoredRow]:
    """Return every scored binary forecast row resolved against its YES
    probability. Excludes scores with `score IS NULL` (failed) and scores
    whose outcome is itself superseded (scoring.md §5.1)."""

    where = _scored_row_base_where()
    params: list[Any] = []
    _apply_scored_row_filters(rf, where, params)

    sql = f"""
        SELECT fs.id, fs.forecast_id, fs.outcome_id, fs.score, fs.metadata_json,
               f.yes_label,
               o.outcome_label
        FROM forecast_scores fs
        JOIN forecasts f ON f.id = fs.forecast_id
        JOIN theses t ON t.id = f.thesis_id
        JOIN instruments i ON i.id = t.instrument_id
        JOIN outcomes o ON o.id = fs.outcome_id
        WHERE {' AND '.join(where)}
        """
    rows: list[_ScoredRow] = []
    for score_id, forecast_id, outcome_id, _score, metadata_json, yes_label, outcome_label in conn.execute(sql, params).fetchall():
        materialized = _materialize_scored_row(
            conn,
            score_id=score_id,
            forecast_id=forecast_id,
            outcome_id=outcome_id,
            metadata_json=metadata_json,
            yes_label=yes_label,
            outcome_label=outcome_label,
        )
        if materialized is not None:
            rows.append(materialized)
    return rows


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))


def _resolve_p_yes_and_y(
    conn: sqlite3.Connection,
    *,
    forecast_id: str,
    yes_label: str | None,
    outcome_label: str | None,
) -> tuple[float | None, int | None]:
    """Return `(p_yes, y)` for a scored binary forecast. Identifies the YES
    label via the same heuristic as the auto-scorer (scoring.md §3.2)."""

    # `outcomes.outcome_label` and `forecast_outcomes.outcome_label` are
    # declared NOT NULL, but historical / migration-drift data can carry
    # NULLs. Exclude the row instead of crashing the report
    # (trade-trace-rpb8).
    if outcome_label is None:
        return None, None
    cur = conn.execute(
        "SELECT outcome_label, probability FROM forecast_outcomes WHERE forecast_id = ?",
        (forecast_id,),
    )
    rows = cur.fetchall()
    if rows and any(r[0] is None for r in rows):
        return None, None

    canonical_row = conn.execute(
        "SELECT probability FROM forecasts WHERE id = ?", (forecast_id,),
    ).fetchone()
    canonical_probability = canonical_row[0] if canonical_row else None
    resolved_norm = outcome_label.strip().lower()
    yes_norm = yes_label.strip().lower() if yes_label else None
    if canonical_probability is not None:
        legacy_labels = {r[0].strip().lower() for r in rows if r[0] is not None}
        if legacy_labels and resolved_norm not in legacy_labels:
            return None, None
        if yes_norm is None:
            if resolved_norm in {"yes", "true"}:
                yes_norm = resolved_norm
            elif resolved_norm in {"no", "false"}:
                yes_norm = "yes" if resolved_norm == "no" else "true"
        if yes_norm is not None:
            y = 1 if resolved_norm == yes_norm else 0
            return float(canonical_probability), y

    if len(rows) != 2:
        return None, None
    labels = {r[0].strip().lower(): r[1] for r in rows}
    if yes_norm is None:
        if "yes" in labels:
            yes_norm = "yes"
        elif "true" in labels:
            yes_norm = "true"
        elif resolved_norm in labels and len(labels) == 2:
            yes_norm = resolved_norm
    if yes_norm not in labels:
        return None, None
    p_yes = labels[yes_norm]
    y = 1 if resolved_norm == yes_norm else 0
    return p_yes, y


# -- metrics -------------------------------------------------------------


def _compute_metrics(rows: list[_ScoredRow], *, bin_policy: str = DEFAULT_BIN_POLICY) -> dict[str, Any]:
    n = len(rows)
    p_values = [r.p_yes for r in rows]
    y_values = [r.y for r in rows]

    brier = sum((p - y) ** 2 for p, y in zip(p_values, y_values, strict=True)) / n
    log_score = sum(
        -y * math.log(max(p, LOG_EPS)) - (1 - y) * math.log(max(1 - p, LOG_EPS))
        for p, y in zip(p_values, y_values, strict=True)
    ) / n
    p_bar = sum(p_values) / n
    sharpness = sum((p - p_bar) ** 2 for p in p_values) / n
    baseline_values = [r.baseline_probability for r in rows if r.baseline_probability is not None]
    if len(baseline_values) == n:
        baseline = sum(baseline_values) / n
        brier_baseline = sum((p - y) ** 2 for p, y in zip(baseline_values, y_values, strict=True)) / n
        log_baseline = sum(
            -y * math.log(max(p, LOG_EPS)) - (1 - y) * math.log(max(1 - p, LOG_EPS))
            for p, y in zip(baseline_values, y_values, strict=True)
        ) / n
    else:
        baseline = sum(y_values) / n
        brier_baseline = baseline * (1 - baseline)
        log_baseline = (
            -baseline * math.log(max(baseline, LOG_EPS))
            - (1 - baseline) * math.log(max(1 - baseline, LOG_EPS))
        )
    skill = 1.0 - (brier / brier_baseline) if brier_baseline > 0 else None

    ece, reliability_bins = _ece_and_bins(rows, bin_policy=bin_policy)

    return {
        "brier": round(brier, 6),
        "log_score": round(log_score, 6),
        "ece": round(ece, 6),
        "sharpness": round(sharpness, 6),
        "baseline": round(baseline, 6),
        "brier_baseline": round(brier_baseline, 6),
        "log_baseline": round(log_baseline, 6),
        "skill": round(skill, 6) if skill is not None else None,
        "reliability_bins": reliability_bins,
        "sample_size": n,
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "brier": None, "log_score": None, "ece": None, "sharpness": None,
        "baseline": None, "brier_baseline": None, "log_baseline": None,
        "skill": None, "reliability_bins": [], "sample_size": 0,
    }


def _ece_and_bins(rows: list[_ScoredRow], *, bin_policy: str = "equal_width_0.1") -> tuple[float, list[dict[str, Any]]]:
    if bin_policy == "equal_mass":
        return _ece_equal_mass(rows)
    if bin_policy != "equal_width_0.1":
        raise ValueError(f"unsupported ECE bin_policy {bin_policy!r}")
    """Equal-width 10-bin reliability per scoring.md §7.2 default policy.

    Bin assignment is fixed:
    - `p=0.0`   → bin 0
    - `p=0.099` → bin 0
    - `p=0.1`   → bin 1   (the lower edge belongs to the upper bin)
    - `p=0.5`   → bin 5
    - `p=0.999` → bin 9
    - `p=1.0`   → bin 9   (the topmost bin is closed on the right)

    Empty bins are reported with `count=0` and `mean_probability`,
    `observed_frequency`, and `gap` set to `null`. Empty bins do NOT
    contribute to ECE per scoring.md §7.2.
    """

    bins: list[list[_ScoredRow]] = [[] for _ in range(10)]
    for r in rows:
        idx = min(int(r.p_yes * 10), 9)
        bins[idx].append(r)
    n = len(rows)
    ece = 0.0
    panel: list[dict[str, Any]] = []
    for idx, bin_rows in enumerate(bins):
        lower = idx / 10.0
        upper = (idx + 1) / 10.0
        midpoint = (lower + upper) / 2.0
        if not bin_rows:
            panel.append({
                "bin_index": idx,
                "lower": lower,
                "upper": upper,
                "bin_midpoint": midpoint,
                "count": 0,
                "mean_probability": None,
                "observed_frequency": None,
                "gap": None,
            })
            continue
        mean_p = sum(r.p_yes for r in bin_rows) / len(bin_rows)
        mean_y = sum(r.y for r in bin_rows) / len(bin_rows)
        gap = mean_p - mean_y
        ece += (len(bin_rows) / n) * abs(gap)
        panel.append({
            "bin_index": idx,
            "lower": lower,
            "upper": upper,
            "bin_midpoint": midpoint,
            "count": len(bin_rows),
            "mean_probability": round(mean_p, 6),
            "observed_frequency": round(mean_y, 6),
            "gap": round(gap, 6),
        })
    return ece, panel


def _ece_equal_mass(rows: list[_ScoredRow], *, bin_count: int = 10) -> tuple[float, list[dict[str, Any]]]:
    if not rows:
        return 0.0, []
    ordered = sorted(rows, key=lambda r: (r.p_yes, r.forecast_id, r.score_id))
    n = len(ordered)
    bins: list[list[_ScoredRow]] = []
    for idx in range(min(bin_count, n)):
        start = (idx * n) // min(bin_count, n)
        end = ((idx + 1) * n) // min(bin_count, n)
        bins.append(ordered[start:end])
    ece = 0.0
    panel: list[dict[str, Any]] = []
    for idx, bin_rows in enumerate(bins):
        lower = min(r.p_yes for r in bin_rows)
        upper = max(r.p_yes for r in bin_rows)
        mean_p = sum(r.p_yes for r in bin_rows) / len(bin_rows)
        mean_y = sum(r.y for r in bin_rows) / len(bin_rows)
        gap = mean_p - mean_y
        ece += (len(bin_rows) / n) * abs(gap)
        panel.append({
            "bin_index": idx,
            "lower": round(lower, 6),
            "upper": round(upper, 6),
            "bin_midpoint": round((lower + upper) / 2.0, 6),
            "count": len(bin_rows),
            "mean_probability": round(mean_p, 6),
            "observed_frequency": round(mean_y, 6),
            "gap": round(gap, 6),
        })
    return ece, panel


# -- examples ----------------------------------------------------------


def _build_examples(
    conn: sqlite3.Connection, rows: list[_ScoredRow], *, max_examples: int
) -> list[dict[str, Any]]:
    """Return up to `max_examples` records the agent can drill into for
    qualitative inspection. Ordered by Brier descending (worst first)."""

    if not rows:
        return []
    ranked = sorted(rows, key=lambda r: (r.p_yes - r.y) ** 2, reverse=True)
    examples: list[dict[str, Any]] = []
    for r in ranked[:max_examples]:
        examples.append({
            "kind": "forecast",
            "id": r.forecast_id,
            "summary": (
                f"p_yes={r.p_yes:.2f}, y={r.y}, "
                f"brier={(r.p_yes - r.y) ** 2:.4f}"
            ),
        })
    return examples
