"""`report.risk` per bead trade-trace-8z2 + risk-units.md."""

from __future__ import annotations

import sqlite3
from statistics import median
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import process_filter

DEFAULT_RISK_MIN_SAMPLE = 10
_R_BINS = [float("-inf"), -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, float("inf")]

# One decision collapses to one position via position_events, NOT via the
# shared instrument_id (that many-to-many join double-counted closed P&L and
# landed a decision in both the R histogram and the pending caveat —
# trade-trace-rtxy). The CTE picks the lowest position_id per decision for
# determinism so the SELECT yields exactly one row per decision. Used by both
# `report.risk` (point-in-time) and `report.compare(base_report='risk')`
# (the longitudinal / per-strategy expectancy series — trade-trace-62fj).
_RISK_DECISION_SQL = """
    WITH decision_position AS (
        SELECT pe.decision_id AS decision_id, MIN(p.id) AS position_id
        FROM position_events pe
        JOIN positions p ON p.id = pe.position_id
        WHERE pe.decision_id IS NOT NULL
        GROUP BY pe.decision_id
    )
    SELECT d.id, d.instrument_id, d.declared_risk_amount,
           d.declared_risk_unit, d.expected_edge, d.expected_edge_after_costs,
           d.type, d.created_at, p.realized_pnl, p.realized_r_multiple,
           p.status, d.strategy_id
    FROM decisions d
    LEFT JOIN decision_position dp ON dp.decision_id = d.id
    LEFT JOIN positions p ON p.id = dp.position_id
    ORDER BY d.created_at ASC, d.id ASC
"""


def _classify_risk_rows(rows: list[Any]) -> dict[str, Any]:
    """Split raw decision rows (from `_RISK_DECISION_SQL`) into the resolved /
    missing / pending sets shared by `report.risk` and the `risk` compare base.

    Each decision is counted at most once (the CTE already collapses to one row
    per decision; the dedupe is belt-and-suspenders so a decision can never land
    in both the resolved R histogram and the pending caveat — trade-trace-rtxy).
    Returns total_closed, the resolved R-row dicts, and the missing/pending id
    lists so callers can build coverage caveats consistently.
    """

    total_closed = 0
    missing_risk_ids: list[str] = []
    pending_ids: list[str] = []
    resolved: list[dict[str, Any]] = []
    with_risk_ids: list[str] = []
    seen_decision_ids: set[str] = set()

    for row in rows:
        (decision_id, instrument_id, risk_amount, risk_unit, expected_edge,
         expected_edge_after_costs, decision_type, created_at, realized_pnl,
         stored_r, status, strategy_id) = row
        if decision_id in seen_decision_ids:
            continue
        seen_decision_ids.add(decision_id)
        is_closed = status in ("closed", "resolved") and realized_pnl is not None
        if is_closed:
            total_closed += 1
        if risk_amount is None or risk_amount <= 0:
            if is_closed:
                missing_risk_ids.append(decision_id)
            continue
        with_risk_ids.append(decision_id)
        if not is_closed:
            pending_ids.append(decision_id)
            continue
        assert realized_pnl is not None
        realized_r = float(stored_r) if stored_r is not None else float(realized_pnl) / float(risk_amount)
        resolved.append({
            "decision_id": decision_id,
            "instrument_id": instrument_id,
            "declared_risk_amount": float(risk_amount),
            "declared_risk_unit": risk_unit,
            "expected_edge": expected_edge,
            "expected_edge_after_costs": expected_edge_after_costs,
            "decision_type": decision_type,
            "created_at": created_at,
            "strategy_id": strategy_id,
            "realized_pnl": realized_pnl,
            "realized_r_multiple": realized_r,
        })

    return {
        "total_closed": total_closed,
        "resolved": resolved,
        "missing_risk_ids": missing_risk_ids,
        "pending_ids": pending_ids,
        "with_risk_ids": with_risk_ids,
    }


def _coverage_block(*, total_closed: int, n_with_risk: int) -> dict[str, Any]:
    """A prominent denominator/coverage block answering the VISION question:
    of the resolved markets, how many actually carry declared risk units and so
    contribute to expectancy_r (trade-trace-62fj). Mirrors the coverage shape in
    reports.md (eligible/included/missing/coverage_pct/denominator_kind)."""

    missing = max(total_closed - n_with_risk, 0)
    coverage_pct = round((n_with_risk / total_closed) * 100.0, 4) if total_closed else 0.0
    return {
        "eligible_count": total_closed,
        "included_count": n_with_risk,
        "missing_count": missing,
        "coverage_pct": coverage_pct,
        "denominator_kind": "closed_decisions",
        "note": (
            "expectancy_r is computed only over resolved decisions that declared "
            "a positive risk amount; included_count/eligible_count is that "
            "coverage fraction. Resolved markets without declared risk units are "
            "excluded from R metrics (see caveats)."
        ),
    }


def _risk_caveats(
    *, total_closed: int, missing_risk_ids: list[str], pending_ids: list[str],
    coverage: float,
) -> list[str]:
    caveats: list[str] = []
    if missing_risk_ids:
        caveats.append(
            f"{len(missing_risk_ids)} closed decision(s) are missing declared_risk_amount or declared zero R; excluded from R metrics."
        )
    if pending_ids:
        caveats.append(
            f"{len(pending_ids)} decision(s) carry declared risk but have no closed/resolved position P&L yet."
        )
    if total_closed and coverage < 0.5:
        caveats.append("R coverage is below 0.5; metrics are low-coverage and should not be over-interpreted.")
    return caveats


def _histogram(values: list[float]) -> list[dict[str, Any]]:
    buckets: list[dict[str, Any]] = []
    for low, high in zip(_R_BINS, _R_BINS[1:], strict=False):
        count = sum(1 for value in values if value >= low and value < high)
        buckets.append({
            "lower": None if low == float("-inf") else low,
            "upper": None if high == float("inf") else high,
            "count": count,
        })
    return buckets


def _metrics(values: list[float], *, total_closed: int, total_with_risk: int, pending: int) -> dict[str, Any]:
    n = len(values)
    coverage = (n / total_closed) if total_closed else 0.0
    if not values:
        return {
            "n_closed_with_risk": 0,
            "n_closed_total": total_closed,
            "n_decisions_with_risk": total_with_risk,
            "n_pending_with_risk": pending,
            "coverage": round(coverage, 6),
            "mean_r": None,
            "median_r": None,
            "expectancy_r": None,
            "win_rate_r": None,
            "payoff_ratio_r": None,
            "best_r": None,
            "worst_r": None,
            "r_distribution": _histogram([]),
            "win_count": 0,
            "loss_count": 0,
            "breakeven_count": 0,
        }
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    mean_r = sum(values) / n
    payoff = None
    if wins and losses:
        payoff = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
    return {
        "n_closed_with_risk": n,
        "n_closed_total": total_closed,
        "n_decisions_with_risk": total_with_risk,
        "n_pending_with_risk": pending,
        "coverage": round(coverage, 6),
        "mean_r": round(mean_r, 6),
        "median_r": round(float(median(values)), 6),
        "expectancy_r": round(mean_r, 6),
        "win_rate_r": round(len(wins) / n, 6),
        "payoff_ratio_r": None if payoff is None else round(payoff, 6),
        "best_r": round(max(values), 6),
        "worst_r": round(min(values), 6),
        "r_distribution": _histogram(values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "breakeven_count": sum(1 for v in values if v == 0),
    }


def report_risk(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_RISK_MIN_SAMPLE,
) -> dict[str, Any]:
    """Aggregate realized P&L in R units over closed position decisions.

    Empty filters only for now; unsupported non-default filter leaves are
    rejected by the shared report-filter convention rather than silently ignored.
    """

    rf = ReportFilter.model_validate(raw_filter or {})
    filter_view = process_filter(rf, report="report.risk")

    rows = conn.execute(_RISK_DECISION_SQL).fetchall()
    classified = _classify_risk_rows(rows)
    total_closed = classified["total_closed"]
    resolved = classified["resolved"]
    missing_risk_ids = classified["missing_risk_ids"]
    pending_ids = classified["pending_ids"]
    with_risk_ids = classified["with_risk_ids"]

    r_values = [d["realized_r_multiple"] for d in resolved]
    metrics = _metrics(
        r_values,
        total_closed=total_closed,
        total_with_risk=len(with_risk_ids),
        pending=len(pending_ids),
    )
    sample_size = len(r_values)
    sample_warning = None
    if 0 < sample_size < min_sample:
        sample_warning = (
            f"only {sample_size} closed positions with R; risk diagnostics are unreliable below {min_sample}"
        )

    coverage = _coverage_block(total_closed=total_closed, n_with_risk=sample_size)
    caveats = _risk_caveats(
        total_closed=total_closed,
        missing_risk_ids=missing_risk_ids,
        pending_ids=pending_ids,
        coverage=metrics["coverage"],
    )

    policy_summary: dict[str, Any] = {"available": False}
    receipt_summary: dict[str, Any] = {"available": False}
    has_policy_tables = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'risk_check_receipts'"
    ).fetchone() is not None
    if has_policy_tables:
        policies = conn.execute(
            "SELECT id, policy_key, version, policy_hash, effective_from, effective_to "
            "FROM risk_policy_versions ORDER BY effective_from DESC, created_at DESC LIMIT 5"
        ).fetchall()
        recent_receipts = conn.execute(
            "SELECT id, status, outcome, intended_action, policy_version_id, instrument_id, "
            "strategy_id, as_of, created_at FROM risk_check_receipts "
            "WHERE status IN ('fail', 'warn', 'missing_data') OR outcome = 'waived_warning' "
            "ORDER BY created_at DESC, id DESC LIMIT 10"
        ).fetchall()
        rule_rows = conn.execute(
            "SELECT r.receipt_id, r.rule_id, r.reason_code, r.severity, "
            "r.observed_value_json, r.threshold_json, r.waiver_required, r.caveat, "
            "r.missing_data, r.stale_data FROM risk_check_rule_results r "
            "JOIN risk_check_receipts c ON c.id = r.receipt_id "
            "ORDER BY c.created_at DESC, r.rule_id ASC LIMIT 50"
        ).fetchall()
        policy_summary = {
            "available": True,
            "recent_policy_versions": [
                {"id": p[0], "policy_key": p[1], "version": p[2], "policy_hash": p[3],
                 "effective_from": p[4], "effective_to": p[5]}
                for p in policies
            ],
        }
        receipt_summary = {
            "available": True,
            "recent_blocked_or_waived_checks": [
                {"id": r[0], "status": r[1], "outcome": r[2], "intended_action": r[3],
                 "policy_version_id": r[4], "instrument_id": r[5], "strategy_id": r[6],
                 "as_of": r[7], "created_at": r[8]}
                for r in recent_receipts
            ],
            "exposure_vs_limits": [
                {"receipt_id": rr[0], "rule_id": rr[1], "reason_code": rr[2],
                 "severity": rr[3], "observed_value": rr[4], "threshold": rr[5],
                 "waiver_required": bool(rr[6]), "caveat": rr[7],
                 "missing_data": bool(rr[8]), "stale_data": bool(rr[9])}
                for rr in rule_rows
            ],
        }

    summary: dict[str, Any] = {
        "sample_size": sample_size,
        "sample_warning": sample_warning,
        "filter": filter_view,
        "metrics": metrics,
        "coverage": coverage,
        "caveats": caveats,
        "missing_risk_count": len(missing_risk_ids),
        "pending_risk_count": len(pending_ids),
        "decisions_missing_risk_sample": missing_risk_ids[:10],
        "longitudinal_expectancy_report": (
            "report.compare(base_report='risk', group_by='period'|'strategy_id'|"
            "'decision_type') for an over-time / per-strategy expectancy series."
        ),
        "risk_policy_versions": policy_summary,
        "risk_check_receipts": receipt_summary,
        "audit_only_note": "Risk receipts are recorded audit evidence only; this report gives no trading advice and performs no execution action.",
    }
    groups = [{
            "key": "all",
            "label": "All closed positions with declared risk",
            "metrics": metrics,
            "filter": filter_view,
            "record_ids": {"decisions": [d["decision_id"] for d in resolved]},
            "examples": [
                {"kind": "decision", "id": d["decision_id"],
                 "summary": f"realized_pnl={d['realized_pnl']}; R={d['declared_risk_amount']}; realized_r={round(d['realized_r_multiple'], 6)}"}
                for d in resolved[:3]
            ],
            "sample_size": sample_size,
            "sample_warning": sample_warning,
            "truncated": False,
        }]
    return standard_report_result(summary=summary, groups=groups)


__all__ = [
    "DEFAULT_RISK_MIN_SAMPLE",
    "_RISK_DECISION_SQL",
    "_classify_risk_rows",
    "_coverage_block",
    "_metrics",
    "report_risk",
]
