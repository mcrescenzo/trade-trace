"""Path-dependent `report.opportunity` per opportunity-analysis.md.

This is a deliberately small P1 implementation: it replays each decision
against the supplied post-decision snapshot series for the same instrument,
computes favorable/adverse path moves, classifies the documented diagnostic
buckets when the available data supports them, and emits caveats instead of
inventing prices when snapshots are sparse or missing.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.reports._filter_support import process_filter
from trade_trace.timestamps import (
    parse_report_timestamp_lenient_naive_as_utc as _parse_ts,
)

DEFAULT_OPPORTUNITY_MIN_SAMPLE = 20
REPORT_NAME = "report.opportunity"
REPORT_FILTER_SUPPORT: frozenset[str] = frozenset()
_BOUNDARY_CAVEAT = (
    "Retrospective process diagnostics over stored decisions/outcomes/positions and supplied snapshots only; "
    "not a recommendation, backtest, market simulator, broker truth, live execution, settlement, redemption, or advice."
)
_COVERAGE_RANK = {"missing": 0, "sparse": 1, "partial": 2, "complete": 3}
_ENTER_TYPES = {"paper_enter", "actual_enter", "add"}
_SKIP_TYPES = {"skip", "watch"}




def _price(row: sqlite3.Row) -> float | None:
    for key in ("mid", "price", "implied_probability"):
        value = row[key]
        if value is not None:
            return float(value)
    if row["bid"] is not None and row["ask"] is not None:
        return (float(row["bid"]) + float(row["ask"])) / 2.0
    return None


def _direction(side: str | None) -> int | None:
    if side in ("long", "yes"):
        return 1
    if side in ("short", "no"):
        return -1
    return None


def _coverage(decision_at: str, horizon_at: str | None, snapshots: list[sqlite3.Row]) -> str:
    if not snapshots:
        return "missing"
    start = _parse_ts(decision_at)
    end = _parse_ts(horizon_at) or _parse_ts(snapshots[-1]["captured_at"])
    if start is None or end is None or end <= start:
        return "partial"
    span = (end - start).total_seconds()
    times: list[datetime] = [t for s in snapshots if (t := _parse_ts(s["captured_at"])) is not None]
    if not times:
        return "missing"
    covered = max(0.0, (min(max(times), end) - start).total_seconds())
    ratio = covered / span if span > 0 else 1.0
    ordered = [start, *sorted(t for t in times if start < t <= end), end]
    max_gap = max((b - a).total_seconds() for a, b in zip(ordered, ordered[1:], strict=False)) if len(ordered) > 1 else span
    if ratio >= 0.75 and max_gap <= span * 0.25:
        return "complete"
    if ratio >= 0.50:
        return "partial"
    return "sparse"


def _move_unit(delta: float | None, entry: float | None, risk_amount: float | None) -> dict[str, Any]:
    if delta is None:
        return {"value": None, "unit": "price", "r_amount": risk_amount}
    if risk_amount and risk_amount > 0:
        return {"value": round(delta / risk_amount, 6), "unit": "R", "price_delta": round(delta, 6), "r_amount": risk_amount}
    frac = None if not entry else delta / entry
    return {"value": round(delta, 6), "unit": "price", "fraction": None if frac is None else round(frac, 6)}


def _mean(values: list[float]) -> float | None:
    return None if not values else round(sum(values) / len(values), 6)


def _row_metrics(row: sqlite3.Row, snapshots: list[sqlite3.Row]) -> dict[str, Any]:
    side = row["decision_side"] or row["thesis_side"]
    direction = _direction(side)
    entry = row["decision_price"]
    if entry is None and row["decision_snapshot_id"]:
        entry = row["decision_snapshot_price"]
    if entry is None and snapshots:
        entry = _price(snapshots[0])
    if direction is None or entry is None or not snapshots:
        return {
            "max_favorable_delta": None,
            "max_adverse_delta": None,
            "path_best_exit_value": None,
            "path_worst_drawdown": None,
            "exit_efficiency": None,
            "edge_peak": None,
        }
    path_prices: list[tuple[sqlite3.Row, float]] = [(s, p) for s in snapshots if (p := _price(s)) is not None]
    if not path_prices:
        return {
            "max_favorable_delta": None,
            "max_adverse_delta": None,
            "path_best_exit_value": None,
            "path_worst_drawdown": None,
            "exit_efficiency": None,
            "edge_peak": None,
        }
    signed = [direction * (p - float(entry)) for _, p in path_prices]
    max_fav = max(0.0, max(signed))
    max_adv = max(0.0, -min(signed))
    best_exit = max_fav * float(row["quantity"] or 1.0)
    worst_drawdown = 0.0
    peak = signed[0]
    for v in signed:
        peak = max(peak, v)
        worst_drawdown = max(worst_drawdown, peak - v)
    realized = row["realized_pnl"]
    exit_eff = None
    if realized is not None and best_exit > 0:
        exit_eff = round(float(realized) / best_exit, 6)
    edge_values = []
    for snap, p in path_prices:
        if snap["bid"] is not None and snap["ask"] is not None:
            tradable = float(snap["ask"] if direction > 0 else snap["bid"])
            edge_values.append(direction * (p - tradable))
    return {
        "max_favorable_delta": round(max_fav, 6),
        "max_adverse_delta": round(max_adv, 6),
        "path_best_exit_value": round(best_exit, 6),
        "path_worst_drawdown": round(worst_drawdown, 6),
        "exit_efficiency": exit_eff,
        "edge_peak": None if not edge_values else round(max(edge_values), 6),
    }


def _labels(row: sqlite3.Row, metrics: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    fav = metrics["max_favorable_delta"]
    adv = metrics["max_adverse_delta"]
    entry = row["decision_price"] or 1.0
    threshold_pos = max(0.05 * float(entry), 0.5 * float(row["declared_risk_amount"] or 0.0))
    threshold_bad = max(0.03 * float(entry), 0.3 * float(row["declared_risk_amount"] or 0.0))
    favorable_outcome = (row["realized_pnl"] is not None and float(row["realized_pnl"]) > 0) or (row["outcome_value"] is not None and float(row["outcome_value"]) > 0)
    adverse_outcome = (row["realized_pnl"] is not None and float(row["realized_pnl"]) < 0) or (row["outcome_value"] is not None and float(row["outcome_value"]) <= 0)
    playbook_overridden = bool(row["overridden_playbook_rule_count"])
    invalidation_hit_at = None
    if row["decision_type"] in _SKIP_TYPES:
        if fav is not None and fav >= threshold_pos:
            labels.append("missed_positive_edge")
        if adv is not None and adv >= threshold_bad:
            labels.append("good_skip")
    if row["decision_type"] in _ENTER_TYPES:
        risk = row["declared_risk_amount"]
        if risk and adv is not None and adv >= float(risk) and favorable_outcome:
            labels.append("right_thesis_wrong_timing")
        if favorable_outcome and (playbook_overridden or invalidation_hit_at is not None):
            labels.append("bad_process_good_outcome")
        if adverse_outcome and not playbook_overridden and invalidation_hit_at is None:
            labels.append("good_process_bad_outcome")
    return labels or ["unclassified"]


def report_opportunity(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    minimum_coverage: str = "sparse",
    max_records: int = 100,
    include_labels: bool = True,
    min_sample: int = DEFAULT_OPPORTUNITY_MIN_SAMPLE,
) -> dict[str, Any]:
    if minimum_coverage not in _COVERAGE_RANK or minimum_coverage == "missing":
        raise ValueError("minimum_coverage must be one of 'complete', 'partial', or 'sparse'")
    if max_records <= 0 or max_records > 1000:
        raise ValueError("max_records must be between 1 and 1000")
    conn.row_factory = sqlite3.Row
    rf = ReportFilter.model_validate(raw_filter or {})
    filter_view = process_filter(rf, report=REPORT_NAME)

    rows = conn.execute(
        """
        SELECT d.id AS decision_id, d.instrument_id, d.thesis_id, d.forecast_id,
               d.snapshot_id AS decision_snapshot_id, d.type AS decision_type,
               d.side AS decision_side, d.quantity, d.price AS decision_price,
               d.declared_risk_amount, d.created_at AS decision_at,
               t.side AS thesis_side, t.time_horizon_at, f.resolution_at,
               o.id AS outcome_id, o.resolved_at, o.outcome_value,
               p.realized_pnl, ss.price AS decision_snapshot_price,
               COALESCE(dpr_counts.overridden_playbook_rule_count, 0) AS overridden_playbook_rule_count
        FROM decisions d
        LEFT JOIN theses t ON t.id = d.thesis_id
        LEFT JOIN forecasts f ON f.id = d.forecast_id
        -- Pick a single canonical resolved_final outcome per instrument. An
        -- instrument can carry multiple resolved_final rows (e.g. a resolution.add
        -- retry leaves a duplicate); joining on instrument_id alone would fan one
        -- decision into N identical records and inflate sample_size/bucket counts.
        LEFT JOIN outcomes o ON o.id = (
            SELECT o2.id FROM outcomes o2
            WHERE o2.instrument_id = d.instrument_id AND o2.status = 'resolved_final'
            ORDER BY o2.resolved_at DESC, o2.id DESC
            LIMIT 1
        )
        -- Aggregate positions to one row per instrument; an instrument can hold
        -- multiple position rows (paper-entry fragmentation) and only realized_pnl
        -- is consumed downstream, so sum it rather than fanning out the decision.
        LEFT JOIN (
            SELECT instrument_id, SUM(realized_pnl) AS realized_pnl
            FROM positions GROUP BY instrument_id
        ) p ON p.instrument_id = d.instrument_id
        LEFT JOIN snapshots ss ON ss.id = d.snapshot_id
        LEFT JOIN (
            SELECT decision_id, SUM(CASE WHEN status = 'overridden' THEN 1 ELSE 0 END) AS overridden_playbook_rule_count
            FROM decision_playbook_rules
            GROUP BY decision_id
        ) dpr_counts ON dpr_counts.decision_id = d.id
        WHERE d.type IN ('watch','skip','paper_enter','actual_enter','add')
        ORDER BY d.created_at ASC, d.id ASC
        LIMIT ?
        """,
        (max_records,),
    ).fetchall()

    records: list[dict[str, Any]] = []
    caveats: list[str] = []
    duplicate_count = 0
    missing_count = sparse_count = excluded_count = 0
    for row in rows:
        horizon = row["time_horizon_at"] or row["resolution_at"] or row["resolved_at"]
        snap_rows = conn.execute(
            """
            SELECT * FROM snapshots
            WHERE instrument_id = ? AND captured_at > ?
              AND (? IS NULL OR captured_at <= ?)
            ORDER BY captured_at ASC, created_at ASC, id ASC
            """,
            (row["instrument_id"], row["decision_at"], horizon, horizon),
        ).fetchall()
        by_time: dict[str, sqlite3.Row] = {}
        for snap in snap_rows:
            if snap["captured_at"] in by_time:
                duplicate_count += 1
            by_time[snap["captured_at"]] = snap
        snapshots = [by_time[k] for k in sorted(by_time)]
        coverage = _coverage(row["decision_at"], horizon, snapshots)
        if coverage == "missing":
            missing_count += 1
        if coverage == "sparse":
            sparse_count += 1
        metrics = _row_metrics(row, snapshots)
        if _COVERAGE_RANK[coverage] < _COVERAGE_RANK[minimum_coverage]:
            excluded_count += 1
            labels = ["excluded_low_coverage"]
        else:
            labels = _labels(row, metrics) if include_labels else []
        rec = {
            "decision_id": row["decision_id"],
            "instrument_id": row["instrument_id"],
            "outcome_id": row["outcome_id"],
            "decision_type": row["decision_type"],
            "side": row["decision_side"] or row["thesis_side"],
            "decision_at": row["decision_at"],
            "horizon_at": horizon,
            "snapshot_range": {
                "first_captured_at": snapshots[0]["captured_at"] if snapshots else None,
                "last_captured_at": snapshots[-1]["captured_at"] if snapshots else None,
                "snapshot_count": len(snapshots),
            },
            "data_coverage": coverage,
            "metrics": {
                "max_favorable_move": _move_unit(metrics["max_favorable_delta"], row["decision_price"], row["declared_risk_amount"]),
                "max_adverse_move": _move_unit(metrics["max_adverse_delta"], row["decision_price"], row["declared_risk_amount"]),
                "path_best_exit_value": metrics["path_best_exit_value"],
                "path_worst_drawdown": metrics["path_worst_drawdown"],
                "exit_efficiency": metrics["exit_efficiency"],
                "edge_peak": metrics["edge_peak"],
                "invalidation_hit_at": None,
            },
            "classification_labels": labels,
            "caveats": (["no post-decision snapshots; path metrics are null"] if coverage == "missing" else [])
                       + (["sparse snapshot path; metrics may miss extrema"] if coverage == "sparse" else []),
        }
        records.append(rec)

    if missing_count:
        caveats.append(f"{missing_count} decision(s) have no post-decision snapshots; path metrics are null.")
    if sparse_count:
        caveats.append(f"{sparse_count} decision(s) have sparse snapshot coverage; extrema may be understated.")
    if duplicate_count:
        caveats.append(f"{duplicate_count} duplicate captured_at snapshot(s) found; latest-written snapshot per timestamp used.")
    if excluded_count:
        caveats.append(f"{excluded_count} decision(s) are below minimum_coverage={minimum_coverage} and labeled excluded_low_coverage.")

    groups_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        for label in (rec["classification_labels"] or ["metrics_only"]):
            groups_by_label[label].append(rec)
    groups = []
    for label in sorted(groups_by_label):
        members = groups_by_label[label]
        favs = [m["metrics"]["max_favorable_move"]["value"] for m in members if m["metrics"]["max_favorable_move"]["value"] is not None]
        advs = [m["metrics"]["max_adverse_move"]["value"] for m in members if m["metrics"]["max_adverse_move"]["value"] is not None]
        exits = [m["metrics"]["exit_efficiency"] for m in members if m["metrics"]["exit_efficiency"] is not None]
        sample_warning = None
        if 0 < len(members) < min_sample:
            sample_warning = f"only {len(members)} decisions in bucket; opportunity diagnostics are unreliable below {min_sample}"
        groups.append({
            "key": label,
            "label": label,
            "metrics": {
                "count": len(members),
                "mean_max_favorable_move": _mean(favs),
                "mean_max_adverse_move": _mean(advs),
                "mean_exit_efficiency": _mean(exits),
                "invalidation_hit_rate": 0.0,
            },
            "filter": filter_view,
            "record_ids": {
                "decisions": [m["decision_id"] for m in members],
                "snapshots": [],
            },
            "examples": [{"kind": "decision", "id": m["decision_id"], "summary": f"coverage={m['data_coverage']} labels={','.join(m['classification_labels'])}"} for m in members[:3]],
            "sample_size": len(members),
            "sample_warning": sample_warning,
            "truncated": False,
        })

    summary_warning = "no_data" if not records else ("low_sample" if any(g["sample_warning"] for g in groups) else None)
    return {
        "summary": {
            "sample_size": len(records),
            "sample_warning": summary_warning,
            "filter": filter_view,
            "minimum_coverage": minimum_coverage,
            "metrics": {
                "decision_count": len(records),
                "missing_snapshot_count": missing_count,
                "sparse_snapshot_count": sparse_count,
                "duplicate_snapshot_count": duplicate_count,
                "excluded_low_coverage_count": excluded_count,
            },
            "buckets": sorted(groups_by_label),
            "caveats": caveats,
        },
        "records": records,
        "groups": groups,
        "report_kind": "opportunity_process_diagnostics",
        "boundary_caveat": _BOUNDARY_CAVEAT,
        "source_precedence": "local_decisions_outcomes_positions_and_supplied_snapshots_only; external_price_fetching_excluded",
        "local_evidence_only": True,
        "non_executing": True,
        "credential_blind": True,
        "advice_free": True,
        "no_external_price_fetch": True,
        "no_backtest_or_simulation_claims": True,
        "no_live_execution_claims": True,
        "no_settlement_or_redemption_claims": True,
        "not_broker_truth": True,
        "truncated": len(rows) >= max_records,
        "next_cursor": None,
    }


__all__ = ["DEFAULT_OPPORTUNITY_MIN_SAMPLE", "report_opportunity"]
