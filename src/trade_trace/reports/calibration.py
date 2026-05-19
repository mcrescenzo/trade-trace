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

from trade_trace.contracts.report_filter import ReportFilter

DEFAULT_MIN_SAMPLE = 20
"""Per reports.md §3.2 / scoring.md §7.1: N=20 is the calibration floor."""

DEFAULT_BIN_POLICY = "equal_width_0.1"
"""Reliability-bin policy. 10 equal-width bins is the MVP per scoring.md §9.2."""

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
    rows = _load_scored_rows(conn)

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
        "filter": rf.model_dump(),
        "metrics": metrics,
        "caveats": caveats,
        "late_recorded_excluded": excluded_late,
    }
    groups = [
        {
            "key": "all",
            "label": "All scored binary forecasts in filter",
            "metrics": metrics,
            "filter": rf.model_dump(),
            "record_ids": group_record_ids,
            "examples": _build_examples(conn, included_rows, max_examples=3),
            "sample_size": sample_size,
            "sample_warning": sample_warning,
            "truncated": truncated,
        }
    ]
    return {
        "summary": summary,
        "groups": groups,
        "bin_policy": DEFAULT_BIN_POLICY,
        "truncated": False,
        "next_cursor": None,
    }


# -- data loading --------------------------------------------------------


def _load_scored_rows(conn: sqlite3.Connection) -> list[_ScoredRow]:
    """Return every scored binary forecast row resolved against its YES
    probability. Excludes scores with `score IS NULL` (failed) and scores
    whose outcome is itself superseded (scoring.md §5.1)."""

    cur = conn.execute(
        """
        SELECT fs.id, fs.forecast_id, fs.outcome_id, fs.score, fs.metadata_json,
               f.yes_label,
               o.outcome_label
        FROM forecast_scores fs
        JOIN forecasts f ON f.id = fs.forecast_id
        JOIN outcomes o ON o.id = fs.outcome_id
        WHERE fs.metric = 'brier_binary'
          AND fs.score IS NOT NULL
          AND f.kind = 'binary'
          AND NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE e.source_kind = 'outcome' AND e.target_kind = 'outcome'
              AND e.edge_type = 'supersedes' AND e.target_id = o.id
          )
        """
    )
    rows: list[_ScoredRow] = []
    for score_id, forecast_id, outcome_id, _score, metadata_json, yes_label, outcome_label in cur.fetchall():
        try:
            meta = json.loads(metadata_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        late = bool(meta.get("late_recorded"))
        # Reconstruct p_yes and y from the forecast_outcomes + resolved label.
        p_yes, y = _resolve_p_yes_and_y(
            conn,
            forecast_id=forecast_id,
            yes_label=yes_label,
            outcome_label=outcome_label,
        )
        if p_yes is None or y is None:
            continue
        rows.append(_ScoredRow(
            forecast_id=forecast_id,
            score_id=score_id,
            outcome_id=outcome_id,
            p_yes=p_yes,
            y=y,
            late_recorded=late,
        ))
    return rows


def _resolve_p_yes_and_y(
    conn: sqlite3.Connection,
    *,
    forecast_id: str,
    yes_label: str | None,
    outcome_label: str,
) -> tuple[float | None, int | None]:
    """Return `(p_yes, y)` for a scored binary forecast. Identifies the YES
    label via the same heuristic as the auto-scorer (scoring.md §3.2)."""

    cur = conn.execute(
        "SELECT outcome_label, probability FROM forecast_outcomes WHERE forecast_id = ?",
        (forecast_id,),
    )
    rows = cur.fetchall()
    if len(rows) != 2:
        return None, None
    labels = {r[0].strip().lower(): r[1] for r in rows}
    resolved_norm = outcome_label.strip().lower()
    yes_norm = yes_label.strip().lower() if yes_label else None
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


def _compute_metrics(rows: list[_ScoredRow]) -> dict[str, Any]:
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
    baseline = sum(y_values) / n
    brier_baseline = baseline * (1 - baseline)
    log_baseline = (
        -baseline * math.log(max(baseline, LOG_EPS))
        - (1 - baseline) * math.log(max(1 - baseline, LOG_EPS))
    )
    skill = 1.0 - (brier / brier_baseline) if brier_baseline > 0 else None

    ece, reliability_bins = _ece_and_bins(rows)

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


def _ece_and_bins(rows: list[_ScoredRow]) -> tuple[float, list[dict[str, Any]]]:
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
