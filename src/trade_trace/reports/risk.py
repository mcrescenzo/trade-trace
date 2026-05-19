"""`report.risk` per bead trade-trace-8z2 + risk-units.md."""

from __future__ import annotations

import sqlite3
from statistics import median
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.reports._filter_support import applied_filter_view, enforce_supported_filter

DEFAULT_RISK_MIN_SAMPLE = 10
_R_BINS = [float("-inf"), -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, float("inf")]


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
    enforce_supported_filter(rf, report="report.risk")
    filter_view = applied_filter_view(rf, report="report.risk")

    rows = conn.execute(
        """
        SELECT d.id, d.instrument_id, d.declared_risk_amount,
               d.declared_risk_unit, d.expected_edge, d.expected_edge_after_costs,
               d.type, d.created_at, p.realized_pnl, p.realized_r_multiple,
               p.status
        FROM decisions d
        LEFT JOIN positions p ON p.instrument_id = d.instrument_id
        ORDER BY d.created_at ASC, d.id ASC
        """
    ).fetchall()

    total_closed = 0
    missing_risk_ids: list[str] = []
    pending_ids: list[str] = []
    resolved: list[dict[str, Any]] = []
    with_risk_ids: list[str] = []

    for row in rows:
        (decision_id, instrument_id, risk_amount, risk_unit, expected_edge,
         expected_edge_after_costs, decision_type, created_at, realized_pnl,
         stored_r, status) = row
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
            "realized_pnl": realized_pnl,
            "realized_r_multiple": realized_r,
        })

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

    caveats: list[str] = []
    if missing_risk_ids:
        caveats.append(
            f"{len(missing_risk_ids)} closed decision(s) are missing declared_risk_amount or declared zero R; excluded from R metrics."
        )
    if pending_ids:
        caveats.append(
            f"{len(pending_ids)} decision(s) carry declared risk but have no closed/resolved position P&L yet."
        )
    if total_closed and metrics["coverage"] < 0.5:
        caveats.append("R coverage is below 0.5; metrics are low-coverage and should not be over-interpreted.")

    summary: dict[str, Any] = {
        "sample_size": sample_size,
        "sample_warning": sample_warning,
        "filter": filter_view,
        "metrics": metrics,
        "caveats": caveats,
        "missing_risk_count": len(missing_risk_ids),
        "pending_risk_count": len(pending_ids),
        "decisions_missing_risk_sample": missing_risk_ids[:10],
    }
    return {
        "summary": summary,
        "groups": [{
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
        }],
        "truncated": False,
        "next_cursor": None,
    }


__all__ = ["DEFAULT_RISK_MIN_SAMPLE", "report_risk"]
