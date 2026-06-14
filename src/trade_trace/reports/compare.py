"""`report.compare`.

The compare report is intentionally allowlist-driven: public `group_by` values map
to fixed SQL expressions, never interpolated from caller input. Metric calculation
reuses the existing base-report kernels (`report_calibration` private metric
helpers and `report_pnl` row aggregation helper) so grouped output stays aligned
with the standalone reports.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, cast

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.projections import remark_open_positions
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import applied_filter_view, enforce_supported_filter
from trade_trace.reports.calibration import (
    DEFAULT_MIN_SAMPLE,
    _apply_scored_row_filters,
    _build_examples,
    _bulk_fetch_forecast_outcomes,
    _compute_metrics,
    _empty_metrics,
    _materialize_scored_row,
    _scored_row_base_where,
    _ScoredRow,
)
from trade_trace.reports.calibration import (
    REPORT_NAME as CALIBRATION_REPORT_NAME,
)
from trade_trace.reports.pnl import (
    DEFAULT_PNL_MIN_SAMPLE,
    _apply_open_remark,
    _pnl_metrics_for_rows,
)
from trade_trace.reports.risk import (
    _RISK_DECISION_SQL,
    DEFAULT_RISK_MIN_SAMPLE,
    _classify_risk_rows,
    _coverage_block,
)
from trade_trace.reports.risk import (
    _metrics as _risk_metrics_for_values,
)

CALIBRATION_GROUP_SQL: dict[str, str] = {
    "actor_id": "f.actor_id",
    "agent_id": "f.agent_id",
    "model_id": "f.model_id",
    "run_id": "f.run_id",
    "strategy_id": "t.strategy_id",
    "decision_type": "d.type",
    "venue_id": "i.venue_id",
    "asset_class": "i.asset_class",
    "environment": "f.environment",
    "instrument_id": "i.id",
    "outcome_status": "o.status",
    "status": "o.status",
    # trade-trace-txjn: longitudinal calibration-over-time. The VISION's
    # "its calibration curve visibly improves over MONTHS" is point-in-time
    # today — report.calibration emits one aggregate panel and CALIBRATION_GROUP_SQL
    # had no calendar dimension. `resolution_month` / `resolution_week` bucket
    # scored forecasts by the CALENDAR PERIOD they RESOLVED in (basis = the
    # outcome's `resolved_at`, the owner-decided basis — it keys the trend to when
    # the question was answered, matching report.autonomy_readiness's
    # resolution-time calibration_trend). The expression is a FIXED SQL fragment
    # (`strftime` over `o.resolved_at`), never interpolated from caller input, so
    # the allowlist-driven safety contract is preserved. NOTE: this is calendar
    # time, distinct from report.time_decay_sharpening's hours-to-resolution
    # (forecast-horizon) buckets. Per-period N frequently falls below the N=20
    # calibration floor (DEFAULT_MIN_SAMPLE); `_compare_calibration` flags every
    # under-floor period via `sample_warning` and the period-specific summary
    # caveat so a thin month is read as noisy, not as a real calibration shift.
    "resolution_month": "strftime('%Y-%m', o.resolved_at)",
    "resolution_week": "strftime('%Y-W%W', o.resolved_at)",
}

# trade-trace-txjn: calendar-period calibration group_by keys (resolved_at basis).
# Used to attach the low-N-per-period caveat to the compare summary when the
# trend dimension is requested.
CALIBRATION_PERIOD_GROUP_BY: frozenset[str] = frozenset(
    {"resolution_month", "resolution_week"}
)

PNL_GROUP_SQL: dict[str, str] = {
    "instrument_id": "p.instrument_id",
    "status": "p.status",
    "venue_id": "i.venue_id",
    "asset_class": "i.asset_class",
    # strategy_id is supported by the pnl compare (the SQL joins theses t via
    # the earliest decision), but it lived only in a special-case branch inside
    # _compare_pnl and so was undiscoverable from SUPPORTED_GROUP_BY_BY_BASE_REPORT.
    # Registering it here makes it self-documenting (trade-trace-1k5d).
    "strategy_id": "t.strategy_id",
}

# trade-trace-62fj: `report.compare(base_report='risk')` adds the longitudinal /
# per-strategy expectancy dimension the VISION asks for ("honestly measured
# expectancy over enough resolved markets to mean something"). report.risk alone
# is point-in-time over the whole journal; this base report buckets the same
# R-multiple expectancy by month (`period`), strategy, or decision type so an
# expectancy *series* is observable. Grouping is done in Python over the
# classified decision rows (the SQL — `_RISK_DECISION_SQL` — is fixed and never
# interpolated from caller input), so the keys come from the resolved-row dicts
# rather than a SQL fragment. `period` = `YYYY-MM` from the decision created_at.
RISK_GROUP_KEYS: dict[str, str] = {
    "strategy_id": "strategy_id",
    "decision_type": "decision_type",
    "period": "created_at",
}

# Per trade-trace-cs0r: this set used to advertise group_by values
# that the runtime allowlists rejected. It now reflects the actual
# union of `CALIBRATION_GROUP_SQL` and `PNL_GROUP_SQL`. Per-base-report
# subsets live below so an agent can pick a group_by that matches the
# base it's about to compare. `playbook_version_id`, `liquidity_bucket`,
# and `confidence_bucket` are P1+ design surfaces (PRD §4 lists them as
# the broader analytic ambition); promoting them here requires landing
# the SQL mapping AND a regression test first.
DOCUMENTED_GROUP_BY: set[str] = (
    set(CALIBRATION_GROUP_SQL) | set(PNL_GROUP_SQL) | set(RISK_GROUP_KEYS)
)
SUPPORTED_GROUP_BY_BY_BASE_REPORT: dict[str, set[str]] = {
    "calibration": set(CALIBRATION_GROUP_SQL),
    "pnl": set(PNL_GROUP_SQL),
    "risk": set(RISK_GROUP_KEYS),
}

SUPPORTED_BASE_REPORTS = {"calibration", "pnl", "risk"}


def report_compare(
    conn: sqlite3.Connection,
    *,
    base_report: str = "calibration",
    group_by: str = "strategy_id",
    raw_filter: dict[str, Any] | None = None,
    min_sample: int | None = None,
) -> dict[str, Any]:
    base_report = base_report.strip().lower()
    group_by = group_by.strip().lower()
    if base_report not in SUPPORTED_BASE_REPORTS:
        raise ValueError(
            "report.compare base_report currently supports "
            f"{sorted(SUPPORTED_BASE_REPORTS)!r}; got {base_report!r}"
        )
    if base_report == "calibration":
        return _compare_calibration(conn, group_by=group_by, raw_filter=raw_filter, min_sample=min_sample or DEFAULT_MIN_SAMPLE)
    if base_report == "risk":
        return _compare_risk(conn, group_by=group_by, raw_filter=raw_filter, min_sample=min_sample or DEFAULT_RISK_MIN_SAMPLE)
    return _compare_pnl(conn, group_by=group_by, raw_filter=raw_filter, min_sample=min_sample or DEFAULT_PNL_MIN_SAMPLE)


def _compare_calibration(conn: sqlite3.Connection, *, group_by: str, raw_filter: dict[str, Any] | None, min_sample: int) -> dict[str, Any]:
    if group_by not in CALIBRATION_GROUP_SQL:
        raise ValueError(
            f"unsupported group_by for calibration compare: {group_by!r}; "
            f"allowed group_by values are {sorted(CALIBRATION_GROUP_SQL)!r}"
        )
    rf = ReportFilter.model_validate(raw_filter or {})
    enforce_supported_filter(rf, report=CALIBRATION_REPORT_NAME)
    rows_by_group: dict[str, list[_ScoredRow]] = defaultdict(list)
    labels: dict[str, str] = {}
    for key, label, row in _load_grouped_scored_rows(conn, rf, CALIBRATION_GROUP_SQL[group_by]):
        rows_by_group[key].append(row)
        labels[key] = label
    groups = []
    any_warning = False
    for key in sorted(rows_by_group, key=lambda k: (k == "__none__", k)):
        rows = rows_by_group[key]
        warning = None
        insufficient = len(rows) < min_sample
        if insufficient:
            warning = f"only {len(rows)} scored forecasts; calibration is unreliable below {min_sample}"
            any_warning = True
        metrics = _compute_metrics(rows) if rows else _empty_metrics()
        groups.append({
            "key": key,
            "label": labels[key],
            "metrics": metrics,
            # trade-trace-txjn: explicit per-group below-floor flag so a
            # longitudinal-trend consumer can gate on one boolean rather than
            # re-deriving `sample_size < min_sample`. True for every group under
            # the N=20 calibration floor (the common case for monthly buckets).
            "insufficient": insufficient,
            "filter": _group_filter_view(rf, group_by, key, report="report.calibration"),
            "record_ids": {
                "forecasts": sorted({r.forecast_id for r in rows}),
                "forecast_scores": sorted({r.score_id for r in rows}),
                "outcomes": sorted({r.outcome_id for r in rows}),
            },
            "examples": _build_examples(conn, rows, max_examples=3),
            "sample_size": len(rows),
            "sample_warning": warning,
            "truncated": False,
        })
    total = sum(cast("int", g["sample_size"]) for g in groups)
    # trade-trace-txjn: calendar-period buckets frequently fall below the N=20
    # calibration floor, so the longitudinal trend ships an explicit low-N-per-
    # period caveat. Each thin period already carries its own `sample_warning`;
    # this summary-level note states the policy so a consumer reads a sparse
    # month as noise rather than as a real calibration shift, and points at the
    # `insufficient` flag it should gate on.
    caveats: list[str] = []
    if group_by in CALIBRATION_PERIOD_GROUP_BY:
        caveats.append(
            "Calendar-period calibration is bucketed by the outcome's resolved_at "
            f"({group_by}); monthly/weekly buckets frequently fall below the N={min_sample} "
            "calibration floor. Periods with sample_size < min_sample carry a "
            "sample_warning and `insufficient: true` — read those Brier/ECE values as "
            "noisy, not as a real calibration shift, and compare only periods with "
            "comparable N. Trend direction across well-sampled periods is the signal."
        )
    summary = {
            "base_report": "calibration",
            "group_by": group_by,
            "sample_size": total,
            "sample_warning": "one_or_more_groups_below_min_sample" if any_warning else None,
            "filter": applied_filter_view(rf, report=CALIBRATION_REPORT_NAME),
            "metrics": {"group_count": len(groups), "min_sample": min_sample},
            "caveats": caveats,
    }
    return standard_report_result(summary=summary, groups=groups)


def _compare_pnl(conn: sqlite3.Connection, *, group_by: str, raw_filter: dict[str, Any] | None, min_sample: int) -> dict[str, Any]:
    if group_by in PNL_GROUP_SQL:
        group_expr = PNL_GROUP_SQL[group_by]
    else:
        raise ValueError(
            f"unsupported group_by for pnl compare: {group_by!r}; "
            f"allowed group_by values are {sorted(PNL_GROUP_SQL)!r}"
        )
    rf = ReportFilter.model_validate(raw_filter or {})
    # report.pnl standalone accepts only empty filters today; compare adds safe
    # strategy slicing for its wrapper, handled below via parameters.
    if rf.strategy.strategy_id is None:
        enforce_supported_filter(rf, report="report.pnl")
    where: list[str] = []
    params: list[Any] = []
    if rf.strategy.strategy_id is not None:
        if rf.strategy.strategy_id == "__none__":
            where.append("t.strategy_id IS NULL")
        else:
            where.append("t.strategy_id = ?")
            params.append(rf.strategy.strategy_id)
    sql = f"""
        SELECT p.id, p.instrument_id, p.kind, p.status, p.realized_pnl, p.unrealized_pnl,
               {group_expr} AS group_value
        FROM positions p
        LEFT JOIN instruments i ON i.id = p.instrument_id
        LEFT JOIN position_events pe ON pe.id = (
            SELECT pe2.id FROM position_events pe2
            WHERE pe2.position_id = p.id AND pe2.decision_id IS NOT NULL
            ORDER BY pe2.created_at ASC, pe2.id ASC LIMIT 1
        )
        LEFT JOIN decisions d ON d.id = pe.decision_id
        LEFT JOIN theses t ON t.id = d.thesis_id
        {('WHERE ' + ' AND '.join(where)) if where else ''}
    """
    # Re-mark open positions from the latest snapshot so report.compare's PnL
    # rollups agree with report.pnl / report.open_positions (trade-trace-pr2j):
    # the same single read-layer source of truth, applied before bucketing.
    remark = remark_open_positions(conn)
    buckets: dict[str, list[tuple]] = defaultdict(list)
    for row in _apply_open_remark(conn.execute(sql, params).fetchall(), remark):
        key = row[6] if row[6] is not None else "__none__"
        buckets[str(key)].append(row[:6])
    groups = []
    any_warning = False
    for key in sorted(buckets, key=lambda k: (k == "__none__", k)):
        rows = buckets[key]
        metrics = _pnl_metrics_for_rows(rows)
        closed = metrics["closed_count"]
        warning = None
        if 0 < closed < min_sample:
            warning = f"only {closed} closed positions; pnl trend is unreliable below {min_sample}"
            any_warning = True
        groups.append({
            "key": key,
            "label": f"{group_by}={key}",
            "metrics": metrics,
            "filter": _group_filter_view(rf, group_by, key, report="report.pnl"),
            "record_ids": {"positions": [r[0] for r in rows]},
            "examples": [{"kind": "position", "id": r[0], "summary": f"{r[3]} on {r[1]}"} for r in rows[:3]],
            "sample_size": len(rows),
            "sample_warning": warning,
            "truncated": False,
        })
    summary = {
            "base_report": "pnl",
            "group_by": group_by,
            "sample_size": sum(cast("int", g["sample_size"]) for g in groups),
            "sample_warning": "one_or_more_groups_below_min_sample" if any_warning else None,
            "filter": applied_filter_view(rf, report="report.pnl") if rf.strategy.strategy_id is None else rf.model_dump(),
            "metrics": {"group_count": len(groups), "min_sample": min_sample},
            "caveats": [],
    }
    return standard_report_result(summary=summary, groups=groups)


def _risk_group_key(resolved: dict[str, Any], group_by: str) -> str:
    """Bucket a resolved risk-decision row for `report.compare(base_report=
    'risk')`. `period` collapses the ISO `created_at` to its `YYYY-MM` month so
    the expectancy series is monthly; `strategy_id` / `decision_type` read the
    declared dimension. None values fall into the `__none__` bucket so an
    undeclared strategy is visible rather than silently dropped."""

    if group_by == "period":
        created_at = resolved.get("created_at")
        if isinstance(created_at, str) and len(created_at) >= 7:
            return created_at[:7]
        return "__none__"
    value = resolved.get(RISK_GROUP_KEYS[group_by])
    return str(value) if value is not None else "__none__"


def _compare_risk(conn: sqlite3.Connection, *, group_by: str, raw_filter: dict[str, Any] | None, min_sample: int) -> dict[str, Any]:
    """Longitudinal / per-strategy R-multiple expectancy series (trade-trace-62fj).

    Same resolved-decision set and R-metric kernel as `report.risk`, but bucketed
    by month (`period`), strategy, or decision type so expectancy can be trended
    "over enough resolved markets to mean something" (VISION). Each group carries
    the full risk metric set plus a prominent coverage block (declared-risk
    decisions / closed decisions) so low-denominator groups self-caveat."""

    if group_by not in RISK_GROUP_KEYS:
        raise ValueError(
            f"unsupported group_by for risk compare: {group_by!r}; "
            f"allowed group_by values are {sorted(RISK_GROUP_KEYS)!r}"
        )
    rf = ReportFilter.model_validate(raw_filter or {})
    enforce_supported_filter(rf, report="report.risk")

    rows = conn.execute(_RISK_DECISION_SQL).fetchall()
    classified = _classify_risk_rows(rows)

    # Per-group closed-decision denominators: a closed decision contributes to
    # its group's coverage whether or not it declared risk, so total_closed is
    # counted per bucket from BOTH the resolved (with-risk) and missing-risk
    # decision rows. We re-walk the deduped rows once to derive per-group
    # closed counts without re-running the SQL.
    closed_total_by_group: dict[str, int] = defaultdict(int)
    seen: set[str] = set()
    for row in rows:
        decision_id = row[0]
        created_at, status, strategy_id = row[7], row[10], row[11]
        if decision_id in seen:
            continue
        seen.add(decision_id)
        realized_pnl = row[8]
        if status not in ("closed", "resolved") or realized_pnl is None:
            continue
        proxy = {"created_at": created_at, "strategy_id": strategy_id, "decision_type": row[6]}
        closed_total_by_group[_risk_group_key(proxy, group_by)] += 1

    resolved_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for resolved in classified["resolved"]:
        resolved_by_group[_risk_group_key(resolved, group_by)].append(resolved)

    groups: list[dict[str, Any]] = []
    any_warning = False
    all_keys = sorted(
        set(resolved_by_group) | set(closed_total_by_group),
        key=lambda k: (k == "__none__", k),
    )
    for key in all_keys:
        group_resolved = resolved_by_group.get(key, [])
        total_closed = closed_total_by_group.get(key, len(group_resolved))
        r_values = [d["realized_r_multiple"] for d in group_resolved]
        metrics = _risk_metrics_for_values(
            r_values,
            total_closed=total_closed,
            total_with_risk=len(group_resolved),
            pending=0,
        )
        sample = len(r_values)
        warning = None
        if 0 < sample < min_sample:
            warning = f"only {sample} closed positions with R; risk diagnostics are unreliable below {min_sample}"
            any_warning = True
        groups.append({
            "key": key,
            "label": f"{group_by}={key}",
            "metrics": metrics,
            "coverage": _coverage_block(total_closed=total_closed, n_with_risk=sample),
            "filter": _group_filter_view(rf, group_by, key, report="report.risk"),
            "record_ids": {"decisions": [d["decision_id"] for d in group_resolved]},
            "examples": [
                {"kind": "decision", "id": d["decision_id"],
                 "summary": f"realized_pnl={d['realized_pnl']}; R={d['declared_risk_amount']}; realized_r={round(d['realized_r_multiple'], 6)}"}
                for d in group_resolved[:3]
            ],
            "sample_size": sample,
            "sample_warning": warning,
            "truncated": False,
        })

    total_sample = sum(cast("int", g["sample_size"]) for g in groups)
    summary = {
        "base_report": "risk",
        "group_by": group_by,
        "sample_size": total_sample,
        "sample_warning": "one_or_more_groups_below_min_sample" if any_warning else None,
        "filter": applied_filter_view(rf, report="report.risk"),
        "metrics": {"group_count": len(groups), "min_sample": min_sample},
        "caveats": [
            "Expectancy is R-multiple based: only resolved decisions that declared a "
            "positive risk amount contribute. Each group's coverage block reports the "
            "declared-risk fraction; trend across groups with similar coverage.",
        ],
        "audit_only_note": "Local journal expectancy series; no trading advice and no execution action.",
    }
    return standard_report_result(summary=summary, groups=groups)


def _load_grouped_scored_rows(conn: sqlite3.Connection, rf: ReportFilter, group_expr: str) -> Iterable[tuple[str, str, _ScoredRow]]:
    where = _scored_row_base_where()
    params: list[Any] = []
    _apply_scored_row_filters(
        rf, where, params, include_late_recorded_predicate=True,
    )
    # trade-trace-v526: the `decisions` table is only joined when the grouping
    # expression references the `d` alias (currently `decision_type` -> `d.type`).
    # The old thesis-level `LEFT JOIN decisions d ON d.thesis_id = t.id` fanned
    # every scored forecast out once per decision attached to its thesis: for
    # single-valued groupings it double-counted the same scored row into one
    # group (inflating Brier/ECE/sharpness/sample_size); for `decision_type` it
    # spread one forecast across every decision type on the thesis. We now join
    # via `d.forecast_id = fs.forecast_id` (one decision link per forecast) and
    # omit the join entirely for every grouping that does not reference `d`.
    if "d." in group_expr:
        decision_join = "LEFT JOIN decisions d ON d.forecast_id = fs.forecast_id"
    else:
        decision_join = ""
    # trade-trace-u7j3: `f.probability` (the canonical-probability fast path) is
    # added to the SELECT so the common case resolves with zero extra queries.
    sql = f"""
        SELECT fs.id, fs.forecast_id, fs.outcome_id, fs.metadata_json, f.yes_label,
               f.probability, o.outcome_label, {group_expr} AS group_value
        FROM forecast_scores fs
        JOIN forecasts f ON f.id = fs.forecast_id
        JOIN theses t ON t.id = f.thesis_id
        {decision_join}
        JOIN instruments i ON i.id = t.instrument_id
        JOIN outcomes o ON o.id = fs.outcome_id
        WHERE {' AND '.join(where)}
    """
    fetched = conn.execute(sql, params).fetchall()
    # trade-trace-u7j3: bulk-fetch every forecast's `forecast_outcomes` rows in
    # one IN-list query before the loop, replacing the per-row SELECT.
    outcomes_by_forecast = _bulk_fetch_forecast_outcomes(
        conn, {row[1] for row in fetched},
    )
    # trade-trace-v526: even with the per-forecast decision join, a forecast can
    # carry several decisions of the SAME type (or several `decision_type` rows),
    # so guard `(score_id, group_key)` to yield each scored forecast at most once
    # per group. This keeps single-valued groupings and the summary `total`
    # sample_size from being overcounted.
    seen: set[tuple[str, str]] = set()
    for score_id, forecast_id, outcome_id, metadata_json, yes_label, canonical_probability, outcome_label, group_value in fetched:
        key = str(group_value) if group_value is not None else "__none__"
        if (score_id, key) in seen:
            continue
        materialized = _materialize_scored_row(
            conn,
            score_id=score_id,
            forecast_id=forecast_id,
            outcome_id=outcome_id,
            metadata_json=metadata_json,
            yes_label=yes_label,
            outcome_label=outcome_label,
            canonical_probability=canonical_probability,
            outcome_rows=outcomes_by_forecast.get(forecast_id, []),
        )
        if materialized is None:
            continue
        seen.add((score_id, key))
        yield key, f"group_by={key}", materialized


def _group_filter_view(rf: ReportFilter, group_by: str, key: str, *, report: str) -> dict[str, Any]:
    view = applied_filter_view(rf, report=report) if report != "report.pnl" or rf.strategy.strategy_id is None else rf.model_dump()
    if group_by == "strategy_id":
        view.setdefault("strategy", {})["strategy_id"] = key
    elif group_by == "venue_id":
        view.setdefault("instrument", {})["venue_id"] = [key]
    elif group_by in {"actor_id", "agent_id", "model_id", "environment", "run_id"}:
        view.setdefault("actors", {})[group_by] = [key]
    else:
        view.setdefault("compare", {})["group_by"] = group_by
        view["compare"]["group_value"] = key
    return view


__all__ = [
    "DOCUMENTED_GROUP_BY",
    "RISK_GROUP_KEYS",
    "SUPPORTED_BASE_REPORTS",
    "SUPPORTED_GROUP_BY_BY_BASE_REPORT",
    "report_compare",
]
