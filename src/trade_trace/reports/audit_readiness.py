"""Read-only audit-readiness report for prediction/event-market provenance.

Deterministic local diagnostics only: no network, no recommendations.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from trade_trace.timestamps import to_utc_iso8601

MAX_SAMPLES = 100
DEFAULT_STALE_SNAPSHOT_THRESHOLD_DAYS = 1
DEFAULT_STALE_SOURCE_THRESHOLD_DAYS = 7

ENTER_TYPES = ("actual_enter", "paper_enter")
PM_CLASSES = ("prediction_market", "event_market")


def report_audit_readiness(
    conn: sqlite3.Connection,
    *,
    stale_snapshot_threshold_days: int = DEFAULT_STALE_SNAPSHOT_THRESHOLD_DAYS,
    stale_source_threshold_days: int = DEFAULT_STALE_SOURCE_THRESHOLD_DAYS,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    checks = [
        _missing_resolution_rule_provenance(conn),
        _missing_snapshot_for_entered_decisions(conn),
        _stale_snapshots(conn, stale_snapshot_threshold_days),
        _missing_microstructure(conn),
        _stale_sources(conn, stale_source_threshold_days),
        _contradictory_sources(conn),
        _weak_decision_provenance(conn),
        _missing_retrieval_metadata(conn),
        _missing_agent_metadata(conn),
    ]
    issues = [c for c in checks if c["count"] > 0]
    counts = {"blocking": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue["severity"]] += issue["count"]
    sample_size = _count(conn, """
        SELECT COUNT(*)
        FROM decisions d
        JOIN instruments i ON i.id = d.instrument_id
        WHERE d.type IN ('actual_enter','paper_enter')
          AND i.asset_class IN ('prediction_market','event_market')
        """)
    sample_warning = "no_data" if sample_size == 0 else None
    return {
        "summary": {
            "sample_size": sample_size,
            "blocking_count": counts["blocking"],
            "warning_count": counts["warning"],
            "info_count": counts["info"],
            "ready": sample_size > 0 and counts["blocking"] == 0,
            "sample_warning": sample_warning,
            "stale_snapshot_threshold_days": stale_snapshot_threshold_days,
            "stale_source_threshold_days": stale_source_threshold_days,
        },
        "issues": issues,
    }


def _count(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def _issue(check: str, severity: str, sample_kind: str, samples: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(samples)
    capped = samples[:MAX_SAMPLES]
    return {
        "check": check,
        "severity": severity,
        "count": total,
        "sample_ids": {sample_kind: [s["id"] for s in capped]},
        "samples": capped,
        "truncated": total > MAX_SAMPLES,
    }


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(to_utc_iso8601(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _missing_resolution_rule_provenance(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT f.id, t.instrument_id, i.resolution_criteria_text, f.resolution_rule_text
        FROM forecasts f
        JOIN theses t ON t.id = f.thesis_id
        JOIN instruments i ON i.id = t.instrument_id
        WHERE i.asset_class IN ('prediction_market','event_market')
          AND (NULLIF(TRIM(COALESCE(i.resolution_criteria_text,'')), '') IS NULL
               OR NULLIF(TRIM(COALESCE(f.resolution_rule_text,'')), '') IS NULL)
        ORDER BY f.created_at, f.id
        """
    ).fetchall()
    samples = [{"id": r[0], "instrument_id": r[1], "has_instrument_criteria": bool(r[2]), "has_forecast_rule": bool(r[3])} for r in rows]
    return _issue("missing_resolution_rule_provenance", "blocking", "forecasts", samples)


def _missing_snapshot_for_entered_decisions(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT d.id, d.instrument_id
        FROM decisions d
        JOIN instruments i ON i.id = d.instrument_id
        WHERE d.type IN ('actual_enter','paper_enter')
          AND i.asset_class IN ('prediction_market','event_market')
          AND d.snapshot_id IS NULL
        ORDER BY d.created_at, d.id
        """
    ).fetchall()
    return _issue("missing_snapshot", "blocking", "decisions", [{"id": r[0], "instrument_id": r[1]} for r in rows])


def _stale_snapshots(conn: sqlite3.Connection, days: int) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT d.id, d.snapshot_id, d.created_at, s.captured_at
        FROM decisions d
        JOIN instruments i ON i.id = d.instrument_id
        JOIN snapshots s ON s.id = d.snapshot_id
        WHERE d.type IN ('actual_enter','paper_enter')
          AND i.asset_class IN ('prediction_market','event_market')
        ORDER BY d.created_at, d.id
        """
    ).fetchall()
    samples = []
    for d_id, s_id, d_at, s_at in rows:
        dd, sd = _parse(d_at), _parse(s_at)
        if dd and sd and dd - sd > timedelta(days=days):
            samples.append({"id": d_id, "snapshot_id": s_id, "decision_at": to_utc_iso8601(d_at), "captured_at": to_utc_iso8601(s_at), "age_days": (dd - sd).days})
    return _issue("stale_snapshot", "warning", "decisions", samples)


def _missing_microstructure(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT d.id, d.snapshot_id, s.bid, s.ask, s.spread, s.liquidity_depth_json
        FROM decisions d
        JOIN instruments i ON i.id = d.instrument_id
        JOIN snapshots s ON s.id = d.snapshot_id
        WHERE d.type IN ('actual_enter','paper_enter')
          AND i.asset_class IN ('prediction_market','event_market')
        ORDER BY d.created_at, d.id
        """
    ).fetchall()
    samples = []
    for d_id, s_id, bid, ask, spread, depth in rows:
        missing = []
        if bid is None:
            missing.append("bid")
        if ask is None:
            missing.append("ask")
        if spread is None:
            missing.append("spread")
        try:
            empty_depth = not bool(json.loads(depth or "{}"))
        except Exception:
            empty_depth = True
        if empty_depth:
            missing.append("liquidity_depth_json")
        if missing:
            samples.append({"id": d_id, "snapshot_id": s_id, "missing_fields": missing})
    return _issue("missing_market_microstructure", "warning", "decisions", samples)


def _stale_sources(conn: sqlite3.Connection, days: int) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT s.id, d.id, s.freshness_at, d.created_at
        FROM edges e
        JOIN sources s ON s.id = e.source_id
        JOIN decisions d ON d.thesis_id = e.target_id
        JOIN instruments i ON i.id = d.instrument_id
        WHERE e.source_kind='source'
          AND e.target_kind='thesis'
          AND d.type IN ('actual_enter','paper_enter')
          AND i.asset_class IN ('prediction_market','event_market')
          AND s.freshness_at IS NOT NULL
        UNION
        SELECT s.id, d.id, s.freshness_at, d.created_at
        FROM edges e
        JOIN sources s ON s.id = e.source_id
        JOIN decisions d ON d.id = e.target_id
        JOIN instruments i ON i.id = d.instrument_id
        WHERE e.source_kind='source'
          AND e.target_kind='decision'
          AND d.type IN ('actual_enter','paper_enter')
          AND i.asset_class IN ('prediction_market','event_market')
          AND s.freshness_at IS NOT NULL
        """
    ).fetchall()
    samples = []
    seen = set()
    for s_id, d_id, fresh, d_at in rows:
        if (s_id, d_id) in seen:
            continue
        seen.add((s_id, d_id))
        fd, dd = _parse(fresh), _parse(d_at)
        if fd and dd and dd - fd > timedelta(days=days):
            samples.append({"id": s_id, "decision_id": d_id, "freshness_at": to_utc_iso8601(fresh), "decision_at": to_utc_iso8601(d_at), "staleness_days": (dd - fd).days})
    return _issue("stale_source", "warning", "sources", samples)


def _contradictory_sources(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT e1.target_id, s1.kind, s1.id, s2.id
        FROM edges e1
        JOIN theses t ON t.id = e1.target_id
        JOIN instruments i ON i.id = t.instrument_id
        JOIN sources s1 ON s1.id=e1.source_id
        JOIN edges e2 ON e2.target_kind=e1.target_kind AND e2.target_id=e1.target_id
        JOIN sources s2 ON s2.id=e2.source_id AND s2.kind=s1.kind
        WHERE e1.source_kind='source' AND e2.source_kind='source'
          AND e1.target_kind='thesis' AND e1.edge_type='supports' AND e2.edge_type='contradicts'
          AND i.asset_class IN ('prediction_market','event_market')
        ORDER BY e1.target_id, s1.id, s2.id
        """
    ).fetchall()
    return _issue("contradictory_sources", "blocking", "theses", [{"id": r[0], "source_kind": r[1], "supports_source_id": r[2], "contradicts_source_id": r[3]} for r in rows])


def _weak_decision_provenance(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT d.id
        FROM decisions d
        JOIN instruments i ON i.id = d.instrument_id
        WHERE d.type IN ('actual_enter','paper_enter')
          AND i.asset_class IN ('prediction_market','event_market')
          AND NULLIF(TRIM(COALESCE(d.reason,'')), '') IS NULL
          AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.source_kind='source' AND e.target_kind='decision' AND e.target_id=d.id)
        ORDER BY d.created_at, d.id
        """
    ).fetchall()
    return _issue("weak_decision_provenance", "blocking", "decisions", [{"id": r[0]} for r in rows])


def _missing_retrieval_metadata(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT id FROM (
            SELECT DISTINCT s.id AS id
            FROM edges e
            JOIN sources s ON s.id = e.source_id
            JOIN decisions d ON d.thesis_id = e.target_id
            JOIN instruments i ON i.id = d.instrument_id
            WHERE e.source_kind='source'
              AND e.target_kind='thesis'
              AND d.type IN ('actual_enter','paper_enter')
              AND i.asset_class IN ('prediction_market','event_market')
              AND s.retrieved_at IS NULL
              AND s.captured_at IS NULL
            UNION
            SELECT DISTINCT s.id AS id
            FROM edges e
            JOIN sources s ON s.id = e.source_id
            JOIN decisions d ON d.id = e.target_id
            JOIN instruments i ON i.id = d.instrument_id
            WHERE e.source_kind='source'
              AND e.target_kind='decision'
              AND d.type IN ('actual_enter','paper_enter')
              AND i.asset_class IN ('prediction_market','event_market')
              AND s.retrieved_at IS NULL
              AND s.captured_at IS NULL
        )
        ORDER BY id
        """
    ).fetchall()
    return _issue("missing_retrieval_metadata", "info", "sources", [{"id": r[0]} for r in rows])


def _missing_agent_metadata(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT d.id
        FROM decisions d
        JOIN instruments i ON i.id = d.instrument_id
        WHERE d.type IN ('actual_enter','paper_enter')
          AND i.asset_class IN ('prediction_market','event_market')
          AND d.agent_id IS NULL AND d.model_id IS NULL AND d.run_id IS NULL
        ORDER BY d.created_at, d.id
        """
    ).fetchall()
    return _issue("missing_agent_metadata", "info", "decisions", [{"id": r[0]} for r in rows])
