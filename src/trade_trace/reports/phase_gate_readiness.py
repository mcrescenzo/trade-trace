"""Phase-2 -> Phase-3 gate-readiness report (bead trade-trace-q04o).

Operationalizes the VISION "autonomy is earned" bar into deterministic,
queryable measurements. This report answers the VISION question -- "did the
agent earn its autonomy?" -- *with data*, by computing each gate criterion
from the local journal and comparing the measured value against an
owner-supplied numeric threshold.

Read-only, deterministic, local-only: no network, no advice, no execution.

OWNER-DECISION SAFETY INVARIANT (see docs/architecture/phase-gates.md)
----------------------------------------------------------------------
The *numeric thresholds* (minimum resolved-N, maximum Brier, minimum skill
vs market baseline, mismatch budget, paper-fill coverage) are a genuine
OWNER decision. The agent must never pick the bar that grants itself a
wallet. Therefore:

* This report does NOT embed a default "pass" bar. When the owner has not
  supplied thresholds, every criterion reports ``threshold=None`` and
  ``pass=None`` (indeterminate, NOT pass), the overall ``gate_status`` is
  ``"owner_thresholds_unset"``, and ``ready`` is ``False``.
* ``ready`` can only be ``True`` when (a) the owner supplied a threshold for
  every criterion AND (b) every criterion's measured value clears its
  owner-supplied threshold. There is no code path where an unset threshold
  results in a passing gate.

The report is therefore a *measurement*, not an authorization. It tells an
owner exactly where the track record stands against numbers the owner set.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from trade_trace.reports.audit_readiness import report_audit_readiness
from trade_trace.reports.calibration import (
    DEFAULT_MIN_SAMPLE,
    _market_baseline_anchored,
)

# Critical reconciliation mismatch codes mirror tools/reconciliation.py
# `_severity`: any record carrying one of these is `critical` severity. A
# clean gate requires zero such codes left in an *unresolved* state.
CRITICAL_MISMATCH_CODES = (
    "POLICY_WAIVER_BREACH",
    "DUPLICATE_FILL",
    "REJECTED_APPROVED_INTENT",
)

# Reconciliation `resolution_status` values that count as still-open. A
# critical record that has been explained / accepted-with-caveat /
# superseded / marked not-applicable is no longer an open breach.
OPEN_RESOLUTION_STATUSES = ("unresolved",)

# Criterion keys, in report order. Each is a measurable gate dimension.
CRITERION_KEYS = (
    "resolved_n",
    "brier",
    "skill_vs_market",
    "reconciliation_cleanliness",
    "audit_readiness",
    "paper_fill_coverage",
)

# The threshold direction for each criterion: ">=" means measured must be at
# least the threshold; "<=" means measured must be at most the threshold.
_DIRECTION = {
    "resolved_n": ">=",
    "brier": "<=",
    "skill_vs_market": ">=",
    "reconciliation_cleanliness": "<=",
    "audit_readiness": "==",
    "paper_fill_coverage": ">=",
}


def _passes(direction: str, measured: float | int | bool, threshold: Any) -> bool | None:
    """Compare a measured value against an owner-supplied threshold.

    Returns ``None`` (indeterminate) when either the threshold is unset or the
    measured value is unavailable. An indeterminate criterion never counts as
    a pass.
    """
    if threshold is None or measured is None:
        return None
    if direction == ">=":
        return float(measured) >= float(threshold)
    if direction == "<=":
        return float(measured) <= float(threshold)
    if direction == "==":
        return bool(measured) == bool(threshold)
    raise ValueError(f"unknown threshold direction {direction!r}")


def _criterion(
    key: str,
    *,
    measured: Any,
    threshold: Any,
    unit: str,
    description: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    direction = _DIRECTION[key]
    result: dict[str, Any] = {
        "key": key,
        "measured": measured,
        "threshold": threshold,
        "direction": direction,
        "unit": unit,
        "pass": _passes(direction, measured, threshold),
        "description": description,
    }
    if extra:
        result.update(extra)
    return result


def _resolved_n(conn: sqlite3.Connection) -> int:
    """Count of scored binary forecasts that make up the resolved track record.

    Mirrors the calibration loaders' base definition (brier_binary score
    present, binary forecast, not on a superseded forecast or outcome) but
    does NOT require a market baseline -- a resolved forecast still counts
    toward the track record even when no anchored/terminal baseline exists.
    Brier/skill *vs the market baseline* are reported separately from the
    anchored panel, which legitimately excludes unanchored rows.
    """
    row = conn.execute(
        """
        SELECT COUNT(*)
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
          AND NOT EXISTS (
              SELECT 1 FROM edges e
              WHERE e.source_kind = 'forecast' AND e.target_kind = 'forecast'
                AND e.edge_type = 'supersedes' AND e.target_id = f.id
          )
        """
    ).fetchone()
    return int(row[0]) if row else 0


def _reconciliation_open_critical(conn: sqlite3.Connection) -> dict[str, Any]:
    """Count reconciliation records that are both unresolved AND critical.

    A record is counted when its ``resolution_status`` is open AND it either
    carries ``diff_severity='critical'``, contains a critical *derived* mismatch
    code, or carries an operator-supplied critical code on the
    ``manually_flagged`` channel (stored under ``diff_json['manually_flagged']``
    since bead trade-trace-opoc separated caller-supplied codes from the
    deterministically derived set). Returns the count plus the sample ids and the
    distinct critical codes seen.
    """
    placeholders = ",".join("?" for _ in OPEN_RESOLUTION_STATUSES)
    rows = conn.execute(
        "SELECT id, diff_severity, mismatch_codes_json, diff_json, resolution_status "
        "FROM reconciliation_records "
        f"WHERE resolution_status IN ({placeholders}) "
        "ORDER BY recorded_at, id",
        OPEN_RESOLUTION_STATUSES,
    ).fetchall()
    open_ids: list[str] = []
    codes_seen: set[str] = set()
    for rec_id, severity, codes_json, diff_json, _status in rows:
        try:
            codes = json.loads(codes_json or "[]")
        except (TypeError, ValueError):
            codes = []
        try:
            diff = json.loads(diff_json or "{}")
        except (TypeError, ValueError):
            diff = {}
        manually_flagged = diff.get("manually_flagged", []) if isinstance(diff, dict) else []
        critical_codes = [c for c in (*codes, *manually_flagged) if c in CRITICAL_MISMATCH_CODES]
        if severity == "critical" or critical_codes:
            open_ids.append(rec_id)
            codes_seen.update(critical_codes)
    return {
        "count": len(open_ids),
        "open_critical_ids": open_ids[:100],
        "critical_codes": sorted(codes_seen),
        "truncated": len(open_ids) > 100,
    }


def _paper_fill_coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    """Fraction of approved pretrade intents that have at least one linked
    paper fill record. Measures whether the paper-fill layer actually tracked
    what would have happened for the trades the agent proposed.

    Coverage is ``filled_intents / total_intents``; an empty journal yields a
    coverage of ``0.0`` and ``total_intents=0`` so callers can detect no-data.
    """
    total = conn.execute("SELECT COUNT(*) FROM pretrade_intents").fetchone()[0]
    if total == 0:
        return {"coverage": 0.0, "filled_intents": 0, "total_intents": 0}
    filled = conn.execute(
        """
        SELECT COUNT(DISTINCT pi.id)
        FROM pretrade_intents pi
        JOIN paper_fill_records pf ON pf.pretrade_intent_id = pi.id
        """
    ).fetchone()[0]
    return {
        "coverage": round(filled / total, 6),
        "filled_intents": int(filled),
        "total_intents": int(total),
    }


def report_phase_gate_readiness(
    conn: sqlite3.Connection,
    *,
    thresholds: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    """Compute Phase-2 -> Phase-3 gate readiness from the local journal.

    Parameters
    ----------
    thresholds:
        Owner-supplied numeric bar, keyed by criterion (see CRITERION_KEYS).
        Any criterion left unset reports ``threshold=None`` / ``pass=None``
        and forces the overall gate to NOT ready (``owner_thresholds_unset``).
        The agent must never default these to a self-granting bar.
    min_sample:
        Sample-size floor passed through to the underlying anchored
        calibration report (does NOT gate readiness; the resolved_n criterion
        is gated by the owner-supplied ``resolved_n`` threshold).
    """
    thresholds = thresholds or {}

    anchored = _market_baseline_anchored(conn, min_sample=min_sample)
    cal_summary = anchored["summary"]
    metrics = cal_summary.get("metrics", {})
    anchored_n = cal_summary.get("sample_size", 0)
    resolved_n = _resolved_n(conn)
    brier = metrics.get("brier")
    brier_baseline = metrics.get("brier_baseline")
    skill = metrics.get("skill")

    audit = report_audit_readiness(conn)
    audit_summary = audit["summary"]
    audit_ready = bool(audit_summary.get("ready"))

    recon = _reconciliation_open_critical(conn)
    coverage = _paper_fill_coverage(conn)

    criteria = [
        _criterion(
            "resolved_n",
            measured=resolved_n,
            threshold=thresholds.get("resolved_n"),
            unit="forecasts",
            description=(
                "Scored binary forecasts in the resolved track record "
                "(non-superseded brier_binary scores). Owner sets the minimum "
                "N below which the track record is too thin to judge."
            ),
        ),
        _criterion(
            "brier",
            measured=brier,
            threshold=thresholds.get("brier"),
            unit="brier_score",
            description=(
                "Mean Brier score over scored binary forecasts with a market "
                "baseline (lower is better). Owner sets the maximum acceptable "
                "Brier. Computed over anchored_n forecasts."
            ),
            extra={"brier_baseline": brier_baseline, "anchored_n": anchored_n},
        ),
        _criterion(
            "skill_vs_market",
            measured=skill,
            threshold=thresholds.get("skill_vs_market"),
            unit="skill_ratio",
            description=(
                "Brier skill versus the market baseline (1 - brier / "
                "brier_baseline; >0 beats the market). Owner sets the minimum "
                "skill the agent must demonstrate over the market. Computed "
                "over anchored_n forecasts."
            ),
            extra={"anchored_n": anchored_n},
        ),
        _criterion(
            "reconciliation_cleanliness",
            measured=recon["count"],
            threshold=thresholds.get("reconciliation_cleanliness"),
            unit="open_critical_records",
            description=(
                "Count of reconciliation records that are simultaneously "
                "unresolved AND critical (open critical mismatches). Owner "
                "sets the mismatch budget; the natural bar is 0 over a "
                "window."
            ),
            extra={
                "open_critical_ids": recon["open_critical_ids"],
                "critical_codes": recon["critical_codes"],
                "truncated": recon["truncated"],
            },
        ),
        _criterion(
            "audit_readiness",
            measured=audit_ready,
            threshold=thresholds.get("audit_readiness"),
            unit="boolean",
            description=(
                "report.audit_readiness `ready` flag: a populated sample with "
                "zero blocking provenance issues. Owner sets the required "
                "value (true)."
            ),
            extra={"blocking_count": audit_summary.get("blocking_count", 0)},
        ),
        _criterion(
            "paper_fill_coverage",
            measured=coverage["coverage"],
            threshold=thresholds.get("paper_fill_coverage"),
            unit="fraction",
            description=(
                "Fraction of pretrade intents that have a linked paper fill "
                "record. Owner sets the minimum coverage required."
            ),
            extra={
                "filled_intents": coverage["filled_intents"],
                "total_intents": coverage["total_intents"],
            },
        ),
    ]

    thresholds_complete = all(c["threshold"] is not None for c in criteria)
    no_data = resolved_n == 0
    passes = [c["pass"] for c in criteria]
    all_pass = thresholds_complete and all(p is True for p in passes)

    if not thresholds_complete:
        gate_status = "owner_thresholds_unset"
    elif no_data:
        gate_status = "insufficient_data"
    elif all_pass:
        gate_status = "ready"
    else:
        gate_status = "not_ready"

    failing = [c["key"] for c in criteria if c["pass"] is False]
    indeterminate = [c["key"] for c in criteria if c["pass"] is None]

    summary = {
        "ready": gate_status == "ready",
        "gate_status": gate_status,
        "owner_thresholds_complete": thresholds_complete,
        "criteria_total": len(criteria),
        "criteria_pass": sum(1 for p in passes if p is True),
        "criteria_fail": len(failing),
        "criteria_indeterminate": len(indeterminate),
        "failing_criteria": failing,
        "indeterminate_criteria": indeterminate,
        "min_sample": min_sample,
        "owner_decision_required": not thresholds_complete,
        "note": (
            "Numeric thresholds are an OWNER decision (VISION 'autonomy is "
            "earned'). An unset threshold yields pass=None and NEVER a passing "
            "gate; the agent must not self-grant a wallet. See "
            "docs/architecture/phase-gates.md."
        ),
    }
    return {
        "summary": summary,
        "criteria": criteria,
        "evidence_refs": {
            "calibration_market_baseline": "phase_gate_readiness.anchored_market_baseline",
            "audit_readiness": "report.audit_readiness",
            "reconciliation": "reconciliation.report",
        },
        "non_executing": True,
        "local_evidence_only": True,
    }
