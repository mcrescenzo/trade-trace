"""Binary-first caller-supplied forecast diagnostics report.

This report intentionally stays retrospective and local: it compares recorded
binary YES probabilities with recorded outcomes and, when available, the
caller-supplied ``snapshots.implied_probability`` linked through decisions. It
never fetches market/reference data and does not rank opportunities or advice.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from trade_trace.contracts.report_filter import STRATEGY_NONE_SENTINEL, ReportFilter
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import applied_filter_view, enforce_supported_filter
from trade_trace.reports.calibration import (
    DEFAULT_MIN_SAMPLE,
    _compute_metrics,
    _empty_metrics,
    _placeholders,
    _resolve_p_yes_and_y,
)
from trade_trace.storage.database import read_snapshot

REPORT_NAME = "report.forecast_diagnostics"
WIDE_SPREAD_THRESHOLD = 0.10


def report_forecast_diagnostics(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    """Return cautious diagnostics over local binary forecasts and snapshots."""

    rf = ReportFilter.model_validate(raw_filter or {})
    enforce_supported_filter(rf, report=REPORT_NAME)
    # Pin a single read snapshot across all SELECTs so panels and exclusion
    # counts can't disagree under concurrent writes (trade-trace-d8lu).
    with read_snapshot(conn):
        return _compose_forecast_diagnostics(conn, rf, min_sample)


def _compose_forecast_diagnostics(
    conn: sqlite3.Connection, rf: ReportFilter, min_sample: int,
) -> dict[str, Any]:
    loaded = _load_rows(conn, rf)
    included = [r for r in loaded["included"] if rf.outcome.include_late_recorded or not r["late_recorded"]]
    late_excluded = sum(1 for r in loaded["included"] if r["late_recorded"] and not rf.outcome.include_late_recorded)

    scored_rows = _dedupe_scored_rows(included)
    metrics = _compute_metrics(scored_rows) if scored_rows else _empty_metrics()
    sample_size = len(scored_rows)
    caveat_codes: list[str] = [
        "caller_supplied_market_reference_only",
        "no_external_fetch",
        "not_advice_or_profitability_evidence",
    ]
    if sample_size < min_sample:
        caveat_codes.append("low_n")
    if late_excluded:
        caveat_codes.append("late_recorded_excluded")
    if sample_size == 0:
        caveat_codes.append("baseline_unavailable")

    market = _market_reference_panel(included)
    caveat_codes.extend(c for c in market["caveat_codes"] if c not in caveat_codes)
    decision_coverage = _decision_coverage(conn, rf)
    exclusions = _exclusion_panel(loaded["excluded"], late_excluded)
    record_ids = _record_ids(included)
    source_coverage = _source_reference_coverage(conn, included)
    if source_coverage["missing_source_reference_count"] and "missing_source_reference" not in caveat_codes:
        caveat_codes.append("missing_source_reference")

    sample_warning = None
    if sample_size < min_sample:
        sample_warning = f"only {sample_size} scored binary forecast(s); diagnostics are caveated below {min_sample}"

    summary = {
        "sample_size": sample_size,
        "sample_warning": sample_warning,
        "filter": applied_filter_view(rf, report=REPORT_NAME),
        "metrics": metrics,
        "reference_class": {
            "type": "sample_prevalence_of_local_scored_binary_outcomes",
            "status": "available" if sample_size > 0 else "baseline_unavailable",
            "count": sample_size,
            "prevalence": metrics.get("baseline"),
            "caveat": "local sample only; low-N and selection effects may dominate",
        },
        "market_reference": market,
        "decision_coverage": decision_coverage,
        "source_reference_coverage": source_coverage,
        "exclusions": exclusions,
        "caveat_codes": caveat_codes,
        "caveats": [
            "Market/reference comparisons use only caller-supplied snapshot fields stored locally; no market data is fetched or derived.",
            "recorded_market_reference_gap is agent p_yes minus stored snapshots.implied_probability; it is not a trading signal or profitability proof.",
            "Brier, reliability, and base-rate summaries require enough resolved local binary outcomes; low-N/source/spread/liquidity caveats should be carried forward.",
            "Source reference coverage is local provenance coverage only: records are counted as covered when a stored source edge is attached to the included forecast, thesis, or decision; source content is not fetched or evaluated.",
        ],
    }
    groups = [{
        "key": "all",
        "label": "All supported local binary forecast diagnostics in filter",
        "metrics": metrics,
        "filter": applied_filter_view(rf, report=REPORT_NAME),
        "record_ids": record_ids,
        "market_reference": market,
        "decision_coverage": decision_coverage,
        "source_reference_coverage": source_coverage,
        "sample_size": sample_size,
        "sample_warning": sample_warning,
        "truncated": False,
    }]
    return standard_report_result(summary=summary, groups=groups)


def _resolve_strategy_filter(conn: sqlite3.Connection, value: str | None) -> str | None:
    if value in (None, STRATEGY_NONE_SENTINEL):
        return value
    row = conn.execute("SELECT id FROM strategies WHERE id = ? OR slug = ? ORDER BY id LIMIT 1", (value, value)).fetchone()
    return row[0] if row else value


def _base_where(conn: sqlite3.Connection, rf: ReportFilter) -> tuple[list[str], list[Any]]:
    where = ["1 = 1"]
    params: list[Any] = []
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
    if rf.instrument.instrument_id:
        where.append(f"i.id IN ({_placeholders(len(rf.instrument.instrument_id))})")
        params.extend(rf.instrument.instrument_id)
    if rf.instrument.venue_id:
        where.append(f"i.venue_id IN ({_placeholders(len(rf.instrument.venue_id))})")
        params.extend(rf.instrument.venue_id)
    if rf.decision.decision_type:
        where.append(f"d.type IN ({_placeholders(len(rf.decision.decision_type))})")
        params.extend(rf.decision.decision_type)
    strategy_value = _resolve_strategy_filter(conn, rf.strategy.strategy_id)
    if strategy_value is not None:
        if strategy_value == STRATEGY_NONE_SENTINEL:
            where.append("COALESCE(d.strategy_id, t.strategy_id) IS NULL")
        else:
            where.append("COALESCE(d.strategy_id, t.strategy_id) = ?")
            params.append(strategy_value)
    return where, params


def _load_rows(conn: sqlite3.Connection, rf: ReportFilter) -> dict[str, list[dict[str, Any]]]:
    where, params = _base_where(conn, rf)
    sql = f"""
        SELECT f.id, f.kind, f.scoring_support, f.yes_label, f.thesis_id,
               t.strategy_id, d.id, d.type, d.snapshot_id,
               s.implied_probability, s.spread, s.volume, s.open_interest,
               s.liquidity_depth_json, fs.id, fs.outcome_id, fs.metric,
               fs.score, fs.metadata_json, o.outcome_label
        FROM forecasts f
        JOIN theses t ON t.id = f.thesis_id
        JOIN instruments i ON i.id = t.instrument_id
        LEFT JOIN decisions d ON d.forecast_id = f.id
        LEFT JOIN snapshots s ON s.id = d.snapshot_id
        LEFT JOIN forecast_scores fs ON fs.forecast_id = f.id AND fs.metric = 'brier_binary'
        LEFT JOIN outcomes o ON o.id = fs.outcome_id
        WHERE {' AND '.join(where)}
        ORDER BY f.created_at, f.id, d.created_at, d.id
    """
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in conn.execute(sql, params).fetchall():
        (fid, kind, support, yes_label, thesis_id, strategy_id, did, dtype, sid, implied, spread,
         volume, oi, depth, score_id, outcome_id, metric, score, score_meta, outcome_label) = row
        if kind != "binary":
            excluded.append({"forecast_id": fid, "reason": "unsupported_non_binary", "kind": kind})
            continue
        p_yes = None
        y = None
        if score_id and score is not None and outcome_label is not None:
            p_yes, y = _resolve_p_yes_and_y(conn, forecast_id=fid, yes_label=yes_label, outcome_label=outcome_label)
        if p_yes is None:
            # Still include binary rows for market/reference coverage, but not scored metrics.
            p_yes, _ = _resolve_binary_probability(conn, fid, yes_label)
        if support != "supported" or p_yes is None:
            excluded.append({"forecast_id": fid, "reason": "binary_probability_unusable" if p_yes is None else "scoring_unsupported", "kind": kind})
            continue
        late = '"late_recorded": true' in (score_meta or "") or '"late_recorded":true' in (score_meta or "")
        scored_row = None
        if score_id and score is not None and outcome_id and y is not None:
            from trade_trace.reports.calibration import _ScoredRow
            scored_row = _ScoredRow(fid, score_id, outcome_id, float(p_yes), int(y), late)
        included.append({
            "forecast_id": fid, "thesis_id": thesis_id, "decision_id": did, "decision_type": dtype, "snapshot_id": sid,
            "outcome_id": outcome_id, "score_id": score_id, "strategy_id": strategy_id,
            "p_yes": float(p_yes), "implied_probability": implied, "spread": spread,
            "volume": volume, "open_interest": oi, "liquidity_depth_json": depth,
            "late_recorded": late, "scored_row": scored_row,
        })
    return {"included": included, "excluded": _dedupe_exclusions(excluded)}


def _resolve_binary_probability(conn: sqlite3.Connection, forecast_id: str, yes_label: str | None) -> tuple[float | None, None]:
    rows = conn.execute("SELECT outcome_label, probability FROM forecast_outcomes WHERE forecast_id = ?", (forecast_id,)).fetchall()
    if len(rows) != 2:
        return None, None
    # NULL outcome_label is a schema invariant violation (forecast_outcomes
    # declares the column NOT NULL); guard so corrupt rows surface as an
    # excludable forecast instead of crashing the report (trade-trace-rpb8).
    if any(r[0] is None for r in rows):
        return None, None
    labels = {r[0].strip().lower(): float(r[1]) for r in rows}
    yes_norm = yes_label.strip().lower() if yes_label else ("yes" if "yes" in labels else "true" if "true" in labels else None)
    return (labels.get(yes_norm), None) if yes_norm else (None, None)


def _market_reference_panel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    with_ref = [r for r in rows if r["implied_probability"] is not None]
    gaps = [r["p_yes"] - float(r["implied_probability"]) for r in with_ref]
    caveats = []
    if len(with_ref) < len(rows):
        caveats.append("missing_market_reference")
    if any(r["spread"] is None for r in rows):
        caveats.append("missing_spread")
    if any(r["spread"] is not None and float(r["spread"]) > WIDE_SPREAD_THRESHOLD for r in rows):
        caveats.append("wide_spread")
    if any(r["volume"] is None and r["open_interest"] is None and (not r["liquidity_depth_json"] or r["liquidity_depth_json"] == "{}") for r in rows):
        caveats.append("missing_liquidity_context")
    return {
        "reference_source": "caller_supplied_snapshots_implied_probability",
        "weighting": "snapshot_decision_reference_counted",
        "caveat": "Counts and gaps are over included forecast-decision snapshot references; a forecast with multiple linked decisions/snapshots can contribute multiple market-reference gaps. This is not a performance ranking or trading signal.",
        "count_with_recorded_implied_probability": len(with_ref),
        "count_missing_recorded_implied_probability": len(rows) - len(with_ref),
        "mean_recorded_market_reference_gap": round(sum(gaps) / len(gaps), 6) if gaps else None,
        "max_abs_recorded_market_reference_gap": round(max((abs(g) for g in gaps), default=0.0), 6) if gaps else None,
        "spread_coverage_count": sum(1 for r in rows if r["spread"] is not None),
        "liquidity_context_coverage_count": sum(1 for r in rows if r["volume"] is not None or r["open_interest"] is not None or (r["liquidity_depth_json"] and r["liquidity_depth_json"] != "{}")),
        "caveat_codes": caveats,
        "wide_spread_threshold": WIDE_SPREAD_THRESHOLD,
    }


def _decision_coverage(conn: sqlite3.Connection, rf: ReportFilter) -> dict[str, Any]:
    where, params = _base_where(conn, rf)
    rows = conn.execute(f"""
        SELECT d.type, d.id, d.forecast_id FROM decisions d
        LEFT JOIN forecasts f ON f.id = d.forecast_id
        LEFT JOIN theses t ON t.id = COALESCE(f.thesis_id, d.thesis_id)
        LEFT JOIN instruments i ON i.id = d.instrument_id
        WHERE {' AND '.join(w.replace('f.', 'f.').replace('d.type', 'd.type') for w in where)}
    """, params).fetchall()
    by_type: dict[str, dict[str, Any]] = {}
    without_forecast: list[str] = []
    for dtype, did, fid in rows:
        bucket = by_type.setdefault(dtype, {"decision_count": 0, "with_forecast_count": 0, "decision_ids": []})
        bucket["decision_count"] += 1
        bucket["decision_ids"].append(did)
        if fid:
            bucket["with_forecast_count"] += 1
        else:
            without_forecast.append(did)
    non_action_types = {"watch", "skip", "hold", "review"}
    return {"by_decision_type": by_type, "decisions_without_forecast": without_forecast, "non_action_decision_types_counted": sorted(non_action_types)}


def _dedupe_scored_rows(rows: list[dict[str, Any]]) -> list[Any]:
    scored: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        scored_row = row.get("scored_row")
        if scored_row is None:
            continue
        key = (str(row["forecast_id"]), str(row["score_id"]))
        if key in seen:
            continue
        seen.add(key)
        scored.append(scored_row)
    return scored


def _has_source_reference(conn: sqlite3.Connection, kind: str, record_id: str) -> bool:
    return conn.execute(
        """
        SELECT 1 FROM edges e
        WHERE ((e.source_kind = ? AND e.source_id = ?) OR (e.target_kind = ? AND e.target_id = ?))
          AND (e.source_kind = 'source' OR e.target_kind = 'source')
        LIMIT 1
        """,
        (kind, record_id, kind, record_id),
    ).fetchone() is not None


def _source_reference_coverage(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> dict[str, Any]:
    records: dict[str, set[str]] = {"forecasts": set(), "theses": set(), "decisions": set()}
    for row in rows:
        records["forecasts"].add(str(row["forecast_id"]))
        if row.get("thesis_id"):
            records["theses"].add(str(row["thesis_id"]))
        if row.get("decision_id"):
            records["decisions"].add(str(row["decision_id"]))
    missing: dict[str, list[str]] = {}
    covered_count = 0
    total_count = 0
    for plural, kind in (("forecasts", "forecast"), ("theses", "thesis"), ("decisions", "decision")):
        missing_ids: list[str] = []
        for record_id in sorted(records[plural]):
            total_count += 1
            if _has_source_reference(conn, kind, record_id):
                covered_count += 1
            else:
                missing_ids.append(record_id)
        missing[plural] = missing_ids[:50]
    return {
        "status": "complete" if covered_count == total_count else "missing_source_reference",
        "covered_source_reference_count": covered_count,
        "total_record_count": total_count,
        "missing_source_reference_count": total_count - covered_count,
        "missing_record_ids_by_kind": missing,
        "caveat": "Local source-edge coverage only; source content is not fetched or assessed.",
    }


def _exclusion_panel(excluded: list[dict[str, Any]], late_excluded: int) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in excluded:
        counts[item["reason"]] = counts.get(item["reason"], 0) + 1
    if late_excluded:
        counts["late_recorded_excluded"] = late_excluded
    return {"counts_by_reason": counts, "forecast_ids_by_reason": {reason: [i["forecast_id"] for i in excluded if i["reason"] == reason][:50] for reason in counts}}


def _record_ids(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {k: sorted({str(r[v]) for r in rows if r.get(v)}) for k, v in {"forecasts": "forecast_id", "decisions": "decision_id", "snapshots": "snapshot_id", "outcomes": "outcome_id", "forecast_scores": "score_id", "strategies": "strategy_id"}.items()}


def _dedupe_exclusions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        key = (item["forecast_id"], item["reason"])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out
