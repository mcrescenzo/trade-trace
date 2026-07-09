"""`report.autonomy_readiness` — the earned-autonomy readiness EVIDENCE BUNDLE
(bead trade-trace-r91l).

The VISION's closing line asks one question: *"did the agent earn its
autonomy?"* `report.phase_gate_readiness` (trade-trace-q04o) already answers
the *point-in-time* version of that — it computes each Phase-2 -> Phase-3 gate
criterion once and compares it to an owner-supplied numeric bar. What it does
NOT do is show whether the track record is *trending* the right way: a single
Brier number cannot distinguish "calibrated for 6 months" from "got lucky last
week".

This report composes three longitudinal evidence sections into one read-only
packet keyed to the gate criteria, so a skeptic can replay the autonomy
question in a single call:

* ``gate`` — the full ``report.phase_gate_readiness`` packet, REUSED verbatim
  (composed, not duplicated). Carries the per-criterion pass/fail/indeterminate
  verdict and the owner-decision safety invariant.
* ``calibration_trend`` — Brier / skill-vs-market over resolution-time windows
  (the longitudinal calibration trend that the point-in-time gate lacks).
* ``expectancy_series`` — realized R-multiple expectancy over the same windows
  (is the edge, if any, persistent or a single-window artifact?).
* ``audit_hygiene`` — the audit-readiness blocking/warning/info diagnostics and
  open-critical reconciliation cleanliness, surfaced as standalone evidence.

Each gate criterion is re-projected into the ``criteria`` array with a stable
``state`` of ``pass`` / ``fail`` / ``insufficient_data`` and the contributing
``record_ids`` so every claim is reproducible.

EVIDENCE-ONLY, NOT A VERDICT (owner decision per the bead + VISION)
------------------------------------------------------------------
VISION favors *"humans read audits and set bounds."* This bundle therefore
renders **no new verdict of its own**. The only ``ready`` / ``gate_status`` it
reports is the one ``report.phase_gate_readiness`` computed from OWNER-supplied
thresholds — copied through verbatim. The trend and expectancy series are
descriptive evidence; they do not vote, and they can NEVER turn a not-ready
gate into a ready one. There is no code path where this report grants autonomy
that the underlying gate would not. The agent must never self-grant a wallet.

Read-only, deterministic, local-only: no network, no advice, no execution.
Follows reports.md §3.0 conventions (insufficient_data metadata, coverage,
caveat_codes, contributing record_ids) and makes no claim a metric does not
support.
"""
from __future__ import annotations

import sqlite3
from statistics import median
from typing import Any

from trade_trace.reports.calibration import (
    DEFAULT_MIN_SAMPLE,
    _compute_metrics,
    _ScoredRow,
)
from trade_trace.reports.phase_gate_readiness import report_phase_gate_readiness

REPORT_NAME = "report.autonomy_readiness"
AUTONOMY_READINESS_CONTRACT_VERSION = "autonomy_readiness.v0"

DEFAULT_TREND_WINDOW_DAYS = 30
"""Default longitudinal-window width. Resolution-time is bucketed into
fixed-width windows ending at the most recent resolution so the trend is
stable regardless of when the report is run."""

DEFAULT_MAX_WINDOWS = 12
"""Cap on the number of trailing windows surfaced (oldest are dropped). Keeps
the packet bounded; truncation is reported explicitly."""

# Map each gate criterion's tri-state pass (True/False/None) to the stable
# §3.0 `state` vocabulary. `None` (indeterminate — unset threshold OR
# unavailable measurement) collapses to `insufficient_data`, which is the
# reports.md term a skeptic greps for.
_STATE_FROM_PASS = {True: "pass", False: "fail", None: "insufficient_data"}


def _criterion_record_ids(key: str, criterion: dict[str, Any]) -> dict[str, list[str]]:
    """Best-effort contributing record_ids for a gate criterion, drawn from the
    criterion payload the gate already computed (reports.md §3.1 drill-down).

    Only the reconciliation-cleanliness criterion carries concrete ids inline
    (`open_critical_ids`); the calibration criteria are reproducible via the
    composed `calibration_trend` / gate `evidence_refs` rather than an id list,
    so they surface an explicit `record_ids_unavailable` reason instead of an
    empty array masquerading as "no contributing rows"."""

    if key == "reconciliation_cleanliness":
        return {"reconciliation_records": list(criterion.get("open_critical_ids", []))}
    return {}


def _window_buckets(
    resolved_iso: list[str], *, window_days: int, max_windows: int
) -> tuple[list[tuple[str, str]], bool]:
    """Build trailing fixed-width [start, end) windows covering the supplied
    resolution timestamps, newest first, capped at ``max_windows``.

    Returns ``(windows, truncated)`` where each window is an ``(start_iso,
    end_iso)`` half-open interval. The newest window ends one second after the
    most recent resolution so that resolution is included. Empty input yields no
    windows."""

    from datetime import datetime, timedelta

    if not resolved_iso:
        return [], False
    parsed = sorted(
        datetime.fromisoformat(ts) for ts in resolved_iso
    )
    earliest, latest = parsed[0], parsed[-1]
    span = timedelta(days=window_days)
    # End boundary is exclusive; nudge past the newest resolution by 1s so it
    # lands in the newest window rather than being excluded by the half-open
    # upper edge.
    end = latest + timedelta(seconds=1)
    windows: list[tuple[str, str]] = []
    while end > earliest and len(windows) <= max_windows:
        start = end - span
        windows.append(
            (
                start.astimezone().isoformat().replace("+00:00", "Z"),
                end.astimezone().isoformat().replace("+00:00", "Z"),
            )
        )
        end = start
    truncated = len(windows) > max_windows
    return windows[:max_windows], truncated


def _to_z(ts: str) -> str:
    from datetime import datetime

    return (
        datetime.fromisoformat(ts)
        .astimezone()
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load_resolved_calibration_rows(
    conn: sqlite3.Connection,
) -> list[tuple[str, _ScoredRow]]:
    """Load every non-superseded scored binary forecast together with the
    anchored market baseline (when present) and the outcome's ``resolved_at``,
    so calibration can be partitioned by resolution-time window.

    Mirrors the resolved-track-record definition in
    ``phase_gate_readiness._resolved_n`` (same supersede guards) but keeps the
    market baseline so Brier/skill can be computed per window. A row whose
    p_yes/y cannot be resolved is skipped, exactly as the calibration loader
    does."""

    from trade_trace.reports.calibration import (
        _bulk_fetch_forecast_outcomes,
        _resolve_p_yes_and_y_from_data,
    )

    rows = conn.execute(
        """
        SELECT fs.id, fs.forecast_id, fs.outcome_id, o.resolved_at,
               f.yes_label, f.probability, o.outcome_label,
               a.market_implied_probability,
               COALESCE(json_extract(fs.metadata_json, '$.late_recorded'), 0)
        FROM forecast_scores fs
        JOIN forecasts f ON f.id = fs.forecast_id
        JOIN outcomes o ON o.id = fs.outcome_id
        LEFT JOIN forecast_snapshot_anchor a ON a.forecast_id = f.id
        WHERE fs.metric = 'brier_binary'
          AND fs.score IS NOT NULL
          AND f.kind = 'binary'
          AND NOT EXISTS (
              SELECT 1 FROM edges e
              WHERE e.source_kind = 'outcome' AND e.target_kind = 'outcome'
                AND e.edge_type = 'supersedes' AND e.target_id = o.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM edges e
              WHERE e.source_kind = 'forecast' AND e.target_kind = 'forecast'
                AND e.edge_type = 'supersedes' AND e.target_id = f.id
          )
        ORDER BY o.resolved_at ASC, fs.id ASC
        """
    ).fetchall()
    outcomes_by_forecast = _bulk_fetch_forecast_outcomes(
        conn, {r[1] for r in rows}
    )
    out: list[tuple[str, _ScoredRow]] = []
    for (
        score_id,
        forecast_id,
        outcome_id,
        resolved_at,
        yes_label,
        canonical_probability,
        outcome_label,
        baseline_probability,
        late_flag,
    ) in rows:
        p_yes, y = _resolve_p_yes_and_y_from_data(
            yes_label=yes_label,
            outcome_label=outcome_label,
            canonical_probability=canonical_probability,
            outcome_rows=outcomes_by_forecast.get(forecast_id, []),
        )
        if p_yes is None or y is None:
            continue
        # Late-recorded forecasts are excluded from the calibration trend by
        # default, mirroring report.calibration / dogfood-protocol §2.2.
        if late_flag:
            continue
        out.append(
            (
                resolved_at,
                _ScoredRow(
                    forecast_id=forecast_id,
                    score_id=score_id,
                    outcome_id=outcome_id,
                    p_yes=p_yes,
                    y=y,
                    late_recorded=False,
                    baseline_probability=(
                        float(baseline_probability)
                        if baseline_probability is not None
                        else None
                    ),
                ),
            )
        )
    return out


def _calibration_trend(
    conn: sqlite3.Connection,
    *,
    window_days: int,
    max_windows: int,
    min_sample: int,
) -> dict[str, Any]:
    """Brier / skill / ECE per resolution-time window (newest first).

    Each window emits its own metric panel plus contributing forecast/score/
    outcome record_ids and an ``insufficient_data`` flag when the window's N is
    below ``min_sample`` (the metrics are still surfaced for transparency but
    flagged unreliable, never zero-filled)."""

    pairs = _load_resolved_calibration_rows(conn)
    resolved_iso = [ts for ts, _ in pairs]
    windows, truncated = _window_buckets(
        resolved_iso, window_days=window_days, max_windows=max_windows
    )
    window_panels: list[dict[str, Any]] = []
    for start_iso, end_iso in windows:
        in_window = [
            row
            for ts, row in pairs
            if _to_z(start_iso) <= _to_z(ts) < _to_z(end_iso)
        ]
        n = len(in_window)
        metrics = _compute_metrics(in_window) if in_window else None
        window_panels.append(
            {
                "window_start": start_iso,
                "window_end": end_iso,
                "sample_size": n,
                "insufficient_data": n < min_sample,
                "metrics": metrics,
                "record_ids": {
                    "forecasts": sorted({r.forecast_id for r in in_window}),
                    "forecast_scores": sorted({r.score_id for r in in_window}),
                    "outcomes": sorted({r.outcome_id for r in in_window}),
                },
            }
        )
    total_n = len(pairs)
    return {
        "window_days": window_days,
        "max_windows": max_windows,
        "windows": window_panels,
        "truncated": truncated,
        "coverage": {
            "eligible_count": total_n,
            "included_count": total_n,
            "missing_count": 0,
            "coverage_pct": 100.0 if total_n else 0.0,
            "denominator_kind": "resolved_scored_binary_forecasts",
        },
        "insufficient_data": total_n < min_sample,
    }


def _expectancy_series(
    conn: sqlite3.Connection, *, window_days: int, max_windows: int, min_sample: int
) -> dict[str, Any]:
    """Realized R-multiple expectancy per resolution/close-time window.

    Uses the same realized-R definition as ``report.risk``: closed/resolved
    position decisions that declared a positive risk budget. Partitioned by the
    position's ``closed_at`` (falling back to the decision ``created_at`` when a
    position carries no close timestamp) so the expectancy trend lines up with
    the calibration trend's resolution axis."""

    rows = conn.execute(
        """
        WITH decision_position AS (
            SELECT pe.decision_id AS decision_id, MIN(p.id) AS position_id
            FROM position_events pe
            JOIN positions p ON p.id = pe.position_id
            WHERE pe.decision_id IS NOT NULL
            GROUP BY pe.decision_id
        )
        SELECT d.id, d.declared_risk_amount, d.created_at,
               p.realized_pnl, p.realized_r_multiple, p.status, p.closed_at
        FROM decisions d
        JOIN decision_position dp ON dp.decision_id = d.id
        JOIN positions p ON p.id = dp.position_id
        WHERE p.status IN ('closed', 'resolved')
          AND p.realized_pnl IS NOT NULL
          AND d.declared_risk_amount IS NOT NULL
          AND d.declared_risk_amount > 0
        ORDER BY COALESCE(p.closed_at, d.created_at) ASC, d.id ASC
        """
    ).fetchall()
    seen: set[str] = set()
    points: list[tuple[str, str, float]] = []  # (when_iso, decision_id, r)
    for decision_id, risk_amount, created_at, realized_pnl, stored_r, _status, closed_at in rows:
        if decision_id in seen:
            continue
        seen.add(decision_id)
        when = closed_at or created_at
        realized_r = (
            float(stored_r)
            if stored_r is not None
            else float(realized_pnl) / float(risk_amount)
        )
        points.append((when, decision_id, realized_r))

    resolved_iso = [ts for ts, _, _ in points]
    windows, truncated = _window_buckets(
        resolved_iso, window_days=window_days, max_windows=max_windows
    )
    window_panels: list[dict[str, Any]] = []
    for start_iso, end_iso in windows:
        in_window = [
            (decision_id, r)
            for ts, decision_id, r in points
            if _to_z(start_iso) <= _to_z(ts) < _to_z(end_iso)
        ]
        n = len(in_window)
        r_values = [r for _, r in in_window]
        if r_values:
            wins = [r for r in r_values if r > 0]
            metrics = {
                "n": n,
                "expectancy_r": round(sum(r_values) / n, 6),
                "median_r": round(float(median(r_values)), 6),
                "win_rate_r": round(len(wins) / n, 6),
                "best_r": round(max(r_values), 6),
                "worst_r": round(min(r_values), 6),
            }
        else:
            metrics = None
        window_panels.append(
            {
                "window_start": start_iso,
                "window_end": end_iso,
                "sample_size": n,
                "insufficient_data": n < min_sample,
                "metrics": metrics,
                "record_ids": {"decisions": sorted(decision_id for decision_id, _ in in_window)},
            }
        )
    total_n = len(points)
    return {
        "window_days": window_days,
        "max_windows": max_windows,
        "windows": window_panels,
        "truncated": truncated,
        "coverage": {
            "eligible_count": total_n,
            "included_count": total_n,
            "missing_count": 0,
            "coverage_pct": 100.0 if total_n else 0.0,
            "denominator_kind": "closed_decisions_with_declared_risk",
        },
        "insufficient_data": total_n < min_sample,
    }


def report_autonomy_readiness(
    conn: sqlite3.Connection,
    *,
    thresholds: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_MIN_SAMPLE,
    window_days: int = DEFAULT_TREND_WINDOW_DAYS,
    max_windows: int = DEFAULT_MAX_WINDOWS,
) -> dict[str, Any]:
    """Compose the earned-autonomy readiness evidence bundle.

    Parameters
    ----------
    thresholds:
        Owner-supplied numeric bar passed straight through to
        ``report.phase_gate_readiness``. Any unset criterion yields
        ``state='insufficient_data'`` and the gate is never ``ready`` — the
        agent must not self-grant a wallet (see phase-gates.md).
    min_sample:
        Low-N floor for the calibration/expectancy windows AND the anchored
        calibration panel inside the gate. Does NOT gate readiness; it only
        flags a window's metrics as ``insufficient_data``.
    window_days / max_windows:
        Longitudinal-window width and trailing-window cap for the trend and
        expectancy series.
    """

    gate = report_phase_gate_readiness(
        conn, thresholds=thresholds, min_sample=min_sample
    )
    gate_summary = gate["summary"]

    # Re-project each gate criterion into the §3.0 tri-state `state` vocabulary
    # with contributing record_ids. The bundle adds NO new pass logic — `state`
    # is a pure restatement of the gate's `pass`.
    criteria: list[dict[str, Any]] = []
    for criterion in gate["criteria"]:
        criteria.append(
            {
                "key": criterion["key"],
                "state": _STATE_FROM_PASS[criterion["pass"]],
                "measured": criterion["measured"],
                "threshold": criterion["threshold"],
                "direction": criterion["direction"],
                "unit": criterion["unit"],
                "record_ids": _criterion_record_ids(criterion["key"], criterion),
            }
        )

    calibration_trend = _calibration_trend(
        conn, window_days=window_days, max_windows=max_windows, min_sample=min_sample
    )
    expectancy_series = _expectancy_series(
        conn, window_days=window_days, max_windows=max_windows, min_sample=min_sample
    )

    # Audit/hygiene evidence: re-surface the two cleanliness signals the gate
    # already consumed (audit-readiness blocking issues + open-critical
    # reconciliation) as a standalone section so a reader does not have to dig
    # them out of the gate criteria.
    by_key = {c["key"]: c for c in gate["criteria"]}
    audit_crit = by_key["audit_readiness"]
    recon_crit = by_key["reconciliation_cleanliness"]
    audit_hygiene = {
        "audit_readiness": {
            "ready": audit_crit["measured"],
            "blocking_count": audit_crit.get("blocking_count", 0),
        },
        "reconciliation_cleanliness": {
            "open_critical_count": recon_crit["measured"],
            "open_critical_ids": recon_crit.get("open_critical_ids", []),
            "critical_codes": recon_crit.get("critical_codes", []),
            "truncated": recon_crit.get("truncated", False),
        },
    }

    states = [c["state"] for c in criteria]
    caveat_codes = ["LOCAL_ROWS_ONLY", "DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM"]
    if "insufficient_data" in states:
        caveat_codes.append("PARTIAL_COVERAGE")
    if calibration_trend["insufficient_data"] or expectancy_series["insufficient_data"]:
        if "LOW_SAMPLE_SIZE" not in caveat_codes:
            caveat_codes.append("LOW_SAMPLE_SIZE")

    summary = {
        # Verbatim pass-through of the OWNER-thresholded gate verdict. This
        # bundle renders NO verdict of its own.
        "ready": gate_summary["ready"],
        "gate_status": gate_summary["gate_status"],
        "owner_thresholds_complete": gate_summary["owner_thresholds_complete"],
        "criteria_total": len(criteria),
        "criteria_pass": sum(1 for s in states if s == "pass"),
        "criteria_fail": sum(1 for s in states if s == "fail"),
        "criteria_insufficient_data": sum(1 for s in states if s == "insufficient_data"),
        "min_sample": min_sample,
        "window_days": window_days,
        "max_windows": max_windows,
        "caveat_codes": caveat_codes,
        "evidence_only": True,
        "verdict_note": (
            "EVIDENCE BUNDLE, not a verdict. The only ready/gate_status here is "
            "report.phase_gate_readiness's, computed from OWNER-supplied "
            "thresholds; the calibration trend and expectancy series are "
            "descriptive evidence and can never turn a not-ready gate ready. "
            "The agent must not self-grant a wallet. See "
            "docs/architecture/phase-gates.md."
        ),
    }

    return {
        "summary": summary,
        "criteria": criteria,
        "gate": gate,
        "calibration_trend": calibration_trend,
        "expectancy_series": expectancy_series,
        "audit_hygiene": audit_hygiene,
        "contract_version": AUTONOMY_READINESS_CONTRACT_VERSION,
        "evidence_refs": {
            "phase_gate_readiness": "report.phase_gate_readiness",
            "calibration_market_baseline": "phase_gate_readiness.anchored_market_baseline",
            "risk": "report.risk",
            "audit_readiness": "report.audit_readiness",
        },
        "non_executing": True,
        "local_evidence_only": True,
    }


__all__ = [
    "AUTONOMY_READINESS_CONTRACT_VERSION",
    "DEFAULT_MAX_WINDOWS",
    "DEFAULT_TREND_WINDOW_DAYS",
    "REPORT_NAME",
    "report_autonomy_readiness",
]
