"""Internal derived lifecycle states for decisions and material non-actions.

This module is intentionally read-only and not registered as a public report/tool.
It derives deterministic lifecycle cases from existing ledger/memory/playbook rows
so future report surfaces can reuse one interpretation without adding lifecycle
persistence.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, get_args

from trade_trace.contracts.report_filter import STRATEGY_NONE_SENTINEL, ReportFilter
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import process_filter
from trade_trace.reports.watchlist import DEFAULT_STALE_THRESHOLD_DAYS
from trade_trace.timestamps import (
    parse_report_timestamp_strict_utc_naive_as_utc as _parse_ts,
)
from trade_trace.tools._helpers import now_iso

LifecycleState = Literal[
    "open",
    "pending_review",
    "stale",
    "resolved",
    "outcome_recorded",
    "scored",
    "reflection_due",
    "reflected",
    "adherence_due",
    "adherence_recorded",
    "closed",
    "superseded",
]

NON_ACTION_DECISION_TYPES = {
    "watch",
    "skip",
    "hold",
    "invalidate_thesis",
    "update_thesis",
    "review",
}
TERMINAL_DECISION_TYPES = {"skip", "resolved", "invalidate_thesis"}


@dataclass(frozen=True)
class LifecycleCase:
    """JSON-like internal lifecycle record for one derived case."""

    case_id: str
    state: LifecycleState
    reason_codes: list[str]
    source_refs: list[dict[str, str]]
    due_at: str | None = None
    threshold_basis: dict[str, Any] = field(default_factory=dict)
    caveat_codes: list[str] = field(default_factory=list)
    material_non_action: dict[str, Any] | None = None
    timestamps: dict[str, str | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def derive_lifecycle_cases(
    conn: sqlite3.Connection,
    *,
    as_of: str | None = None,
    stale_threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS,
) -> list[dict[str, Any]]:
    """Return deterministic derived decision/non-action lifecycle cases.

    Inputs are local SQLite rows only. No rows are written. When ``as_of`` is
    supplied, all due/stale checks use that instant; otherwise the current tool
    clock is captured once via ``now_iso``.
    """

    resolved_as_of = as_of or now_iso()
    as_of_dt = _parse_ts(resolved_as_of)
    threshold_dt = as_of_dt - timedelta(days=stale_threshold_days)
    cases: list[LifecycleCase] = []

    decisions = conn.execute(
        """
        SELECT id, instrument_id, thesis_id, forecast_id, snapshot_id, type,
               reason, playbook_version_id, review_by, strategy_id, run_id,
               metadata_json, created_at
        FROM decisions
        ORDER BY created_at ASC, id ASC
        """,
    ).fetchall()
    for row in decisions:
        decision = _row_dict(
            row,
            [
                "id",
                "instrument_id",
                "thesis_id",
                "forecast_id",
                "snapshot_id",
                "type",
                "reason",
                "playbook_version_id",
                "review_by",
                "strategy_id",
                "run_id",
                "metadata_json",
                "created_at",
            ],
        )
        marker = _material_marker(decision["metadata_json"])
        if decision["type"] not in NON_ACTION_DECISION_TYPES and marker is None:
            continue
        cases.append(
            _derive_decision_case(
                conn,
                decision=decision,
                marker=marker,
                as_of_dt=as_of_dt,
                threshold_dt=threshold_dt,
                stale_threshold_days=stale_threshold_days,
            ),
        )

    # Forecasts are included where their lifecycle is directly computable and
    # useful to decision/non-action cases; this is an internal substrate, not a
    # public report payload.
    forecasts = conn.execute(
        """
        SELECT f.id, f.thesis_id, f.resolution_at, f.scoring_state,
               f.scoring_support, f.created_at, t.instrument_id
        FROM forecasts f
        JOIN theses t ON t.id = f.thesis_id
        ORDER BY f.created_at ASC, f.id ASC
        """,
    ).fetchall()
    for row in forecasts:
        forecast = _row_dict(
            row,
            [
                "id",
                "thesis_id",
                "resolution_at",
                "scoring_state",
                "scoring_support",
                "created_at",
                "instrument_id",
            ],
        )
        cases.append(_derive_forecast_case(conn, forecast=forecast, as_of_dt=as_of_dt))

    return [case.to_dict() for case in sorted(cases, key=_case_sort_key)]


def report_lifecycle(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    states: list[str] | None = None,
    as_of: str | None = None,
    stale_threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS,
) -> dict[str, Any]:
    """Return public derived lifecycle gaps/cases without persisting state."""

    if not isinstance(stale_threshold_days, int) or stale_threshold_days < 0:
        raise ValueError("stale_threshold_days must be a non-negative integer")
    allowed_states = set(get_args(LifecycleState))
    state_filter = sorted(set(states or []))
    unknown = [state for state in state_filter if state not in allowed_states]
    if unknown:
        raise ValueError(f"unsupported lifecycle state(s): {unknown!r}")
    resolved_as_of = _iso(_parse_ts(as_of or now_iso()))

    rf = ReportFilter.model_validate(raw_filter or {})
    filter_view = process_filter(rf, report="report.lifecycle")
    cases = [
        _public_case(case)
        for case in derive_lifecycle_cases(
            conn,
            as_of=resolved_as_of,
            stale_threshold_days=stale_threshold_days,
        )
    ]
    cases = [case for case in cases if _case_matches_filter(case, rf, state_filter)]

    state_counts = {state: 0 for state in sorted(allowed_states)}
    for case in cases:
        state_counts[case["state"]] += 1
    groups = [
        {
            "key": case["case_id"],
            "label": f"{case['state']} lifecycle case",
            "metrics": {
                "state": case["state"],
                "status": case["status"],
                "due_at": case.get("due_at"),
                "created_at": case["timestamps"].get("created_at"),
                "material_non_action": case.get("material_non_action") is not None,
            },
            "filter": {**filter_view, "states": state_filter},
            "record_ids": case["record_ids"],
            "examples": [{"kind": "lifecycle_case", "id": case["case_id"], "summary": ",".join(case["reason_codes"])}],
            "sample_size": 1,
            "sample_warning": None,
            "truncated": False,
        }
        for case in cases
    ]
    return standard_report_result(
        summary={
            "sample_size": len(cases),
            "sample_warning": None,
            "filter": {**filter_view, "states": state_filter},
            "metrics": {
                "case_count": len(cases),
                "state_counts": state_counts,
                "due_count": sum(1 for case in cases if case.get("due_at") is not None),
                "material_non_action_count": sum(1 for case in cases if case.get("material_non_action") is not None),
                "stale_threshold_days": stale_threshold_days,
            },
            "caveats": [],
        },
        groups=groups,
        extra={"as_of": resolved_as_of, "lifecycle_cases": cases},
    )


def _public_case(case: dict[str, Any]) -> dict[str, Any]:
    record_ids: dict[str, list[str]] = {}
    for ref in case["source_refs"]:
        record_ids.setdefault(f"{ref['kind']}s", []).append(ref["id"])
    return {**case, "status": case["state"], "record_ids": {kind: sorted(set(ids)) for kind, ids in sorted(record_ids.items())}}


def _case_matches_filter(case: dict[str, Any], rf: ReportFilter, states: list[str]) -> bool:
    if states and case["state"] not in states:
        return False
    refs = {(ref["kind"], ref["id"]) for ref in case["source_refs"]}
    if rf.instrument.instrument_id and not any(("instrument", inst) in refs for inst in rf.instrument.instrument_id):
        return False
    strategy_ids = [ref_id for kind, ref_id in refs if kind == "strategy"]
    if rf.strategy_filter_mode() == "is_null" and strategy_ids:
        return False
    if rf.strategy_filter_mode() == "match" and ("strategy", rf.strategy.strategy_id or STRATEGY_NONE_SENTINEL) not in refs:
        return False
    if rf.actors.run_id and not any(("run", run_id) in refs for run_id in rf.actors.run_id):
        return False
    created_at = case.get("timestamps", {}).get("created_at")
    for gte in (rf.time_window.created_at_gte, rf.time_window.decision_at_gte):
        if gte is not None and (created_at is None or _parse_ts(created_at) < _parse_ts(gte)):
            return False
    for lt in (rf.time_window.created_at_lt, rf.time_window.decision_at_lt):
        if lt is not None and (created_at is None or _parse_ts(created_at) >= _parse_ts(lt)):
            return False
    return True


def _derive_decision_case(
    conn: sqlite3.Connection,
    *,
    decision: dict[str, Any],
    marker: dict[str, Any] | None,
    as_of_dt: datetime,
    threshold_dt: datetime,
    stale_threshold_days: int,
) -> LifecycleCase:
    decision_id = decision["id"]
    refs = _base_decision_refs(decision) + _edge_refs(conn, "decision", decision_id)
    reason_codes: list[str] = [f"decision_type:{decision['type']}"]
    caveats: list[str] = []
    due_at = decision["review_by"]
    threshold_basis: dict[str, Any] = {"as_of": _iso(as_of_dt)}

    if marker is not None:
        reason_codes.append("material_non_action_marker_present")
    metadata = _metadata_dict(decision.get("metadata_json"))
    if metadata.get("tracelab_seeded") is True:
        reason_codes.append("tracelab_seeded")
    if not any(ref["kind"] == "source" for ref in refs):
        caveats.append("missing_source_ref")

    superseded = _has_incoming_supersedes(conn, "decision", decision_id)
    reflected = _has_reflection(conn, "decision", decision_id)
    adherence_count = _adherence_count(conn, decision_id)
    outcome_id = _outcome_id_for_decision(conn, decision)
    score_id = _score_id(conn, decision["forecast_id"]) if decision["forecast_id"] else None
    score_outcome_id = _score_outcome_id(conn, score_id) if score_id else None
    has_outcome = outcome_id is not None
    has_score = score_id is not None
    has_resolving_decision = _has_later_resolved_decision(conn, decision)

    if superseded:
        state: LifecycleState = "superseded"
        reason_codes.append("superseded_by_edge")
    elif reflected:
        state = "reflected"
        reason_codes.append("reflection_about_decision")
    elif decision["playbook_version_id"] and adherence_count > 0:
        state = "adherence_recorded"
        reason_codes.append("playbook_adherence_row_present")
    elif decision["playbook_version_id"]:
        state = "adherence_due"
        reason_codes.append("playbook_scoped_decision_missing_adherence")
    elif _reflection_due(decision, has_outcome=has_outcome, has_score=has_score, reflected=reflected):
        state = "reflection_due"
        reason_codes.append("resolved_evidence_missing_reflection")
    elif has_score:
        state = "scored"
        reason_codes.append("linked_forecast_score_present")
        if score_id:
            refs.append({"kind": "forecast_score", "id": score_id})
        if score_outcome_id:
            refs.append({"kind": "outcome", "id": score_outcome_id})
    elif has_outcome:
        state = "outcome_recorded"
        reason_codes.append("instrument_outcome_present")
        if outcome_id:
            refs.append({"kind": "outcome", "id": outcome_id})
    elif has_resolving_decision:
        state = "resolved"
        reason_codes.append("later_resolved_decision")
    elif _review_overdue(decision["review_by"], as_of_dt):
        state = "pending_review"
        reason_codes.append("review_by_due")
    elif _is_stale(decision["created_at"], threshold_dt) and decision["type"] in {"watch", "hold", "review"}:
        state = "stale"
        reason_codes.append("created_before_stale_threshold")
        threshold_basis["stale_threshold_days"] = stale_threshold_days
    elif decision["type"] in TERMINAL_DECISION_TYPES and marker is None:
        state = "closed"
        reason_codes.append("terminal_decision_type")
    else:
        state = "open"
        reason_codes.append("no_terminal_or_due_signal")

    return LifecycleCase(
        case_id=f"derived:decision:{decision_id}:lifecycle",
        state=state,
        reason_codes=reason_codes,
        source_refs=_stable_refs(refs),
        due_at=due_at,
        threshold_basis=threshold_basis,
        caveat_codes=sorted(set(caveats)),
        material_non_action=marker,
        timestamps={"created_at": decision["created_at"], "review_by": decision["review_by"]},
    )


def _derive_forecast_case(
    conn: sqlite3.Connection, *, forecast: dict[str, Any], as_of_dt: datetime) -> LifecycleCase:
    refs = _stable_refs([
        {"kind": "forecast", "id": forecast["id"]},
        {"kind": "thesis", "id": forecast["thesis_id"]},
        {"kind": "instrument", "id": forecast["instrument_id"]},
        *_edge_refs(conn, "forecast", forecast["id"]),
    ])
    reason_codes = [f"forecast_scoring_state:{forecast['scoring_state']}"]
    due_at = forecast["resolution_at"]
    score_id = _score_id(conn, forecast["id"])
    score_outcome_id = _score_outcome_id(conn, score_id) if score_id else None
    outcome_id = _outcome_id_for_forecast(conn, forecast)
    has_outcome = outcome_id is not None
    if _has_incoming_supersedes(conn, "forecast", forecast["id"]) or forecast["scoring_state"] == "superseded":
        state: LifecycleState = "superseded"
        reason_codes.append("forecast_superseded")
    elif score_id:
        state = "scored"
        reason_codes.append("forecast_score_present")
        refs.append({"kind": "forecast_score", "id": score_id})
        if score_outcome_id:
            refs.append({"kind": "outcome", "id": score_outcome_id})
    elif has_outcome:
        state = "outcome_recorded"
        reason_codes.append("instrument_outcome_present")
        if outcome_id:
            refs.append({"kind": "outcome", "id": outcome_id})
    elif _review_overdue(forecast["resolution_at"], as_of_dt):
        state = "pending_review"
        reason_codes.append("resolution_at_due_without_score")
    elif not forecast["resolution_at"]:
        # An open forecast with no resolution_at can never become due by clock,
        # so it would otherwise stay silently "open" and never surface in
        # report.work_queue as a resolve obligation (trade-trace-ptyi). Treat the
        # missing horizon itself as a review obligation so the agent loop is
        # prompted to record an outcome or set a resolution horizon.
        state = "pending_review"
        reason_codes.append("resolution_at_missing")
    else:
        state = "open"
        reason_codes.append("forecast_pending")
    caveats = [] if any(ref["kind"] == "source" for ref in refs) else ["missing_source_ref"]
    return LifecycleCase(
        case_id=f"derived:forecast:{forecast['id']}:lifecycle",
        state=state,
        reason_codes=reason_codes,
        source_refs=_stable_refs(refs),
        due_at=due_at,
        threshold_basis={"as_of": _iso(as_of_dt)},
        caveat_codes=caveats,
        timestamps={"created_at": forecast["created_at"], "resolution_at": forecast["resolution_at"]},
    )


def _row_dict(row: tuple[Any, ...], columns: list[str]) -> dict[str, Any]:
    return dict(zip(columns, row, strict=True))


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _metadata_dict(metadata_json: str | None) -> dict[str, Any]:
    if not metadata_json:
        return {}
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _material_marker(metadata_json: str | None) -> dict[str, Any] | None:
    metadata = _metadata_dict(metadata_json)
    marker = metadata.get("material_non_action")
    return marker if isinstance(marker, dict) else None


def _base_decision_refs(decision: dict[str, Any]) -> list[dict[str, str]]:
    refs = [{"kind": "decision", "id": decision["id"]}, {"kind": "instrument", "id": decision["instrument_id"]}]
    for kind, key in (("thesis", "thesis_id"), ("forecast", "forecast_id"), ("snapshot", "snapshot_id"), ("playbook_version", "playbook_version_id"), ("strategy", "strategy_id")):
        if decision.get(key):
            refs.append({"kind": kind, "id": decision[key]})
    if decision.get("run_id"):
        refs.append({"kind": "run", "id": decision["run_id"]})
    return refs


def _edge_refs(conn: sqlite3.Connection, target_kind: str, target_id: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT source_kind, source_id FROM edges
        WHERE target_kind = ? AND target_id = ?
        ORDER BY source_kind ASC, source_id ASC
        """,
        (target_kind, target_id),
    ).fetchall()
    return [{"kind": kind, "id": ref_id} for kind, ref_id in rows]


def _stable_refs(refs: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for ref in sorted(refs, key=lambda r: (r["kind"], r["id"])):
        key = (ref["kind"], ref["id"])
        if key not in seen:
            seen.add(key)
            out.append(ref)
    return out


def _has_incoming_supersedes(conn: sqlite3.Connection, target_kind: str, target_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM edges WHERE target_kind = ? AND target_id = ? AND edge_type = 'supersedes' LIMIT 1",
        (target_kind, target_id),
    ).fetchone() is not None


def _has_reflection(conn: sqlite3.Connection, target_kind: str, target_id: str) -> bool:
    return conn.execute(
        """
        SELECT 1 FROM edges e
        JOIN memory_nodes m ON m.id = e.source_id
        WHERE e.source_kind = 'memory_node' AND m.node_type = 'reflection'
          AND e.target_kind = ? AND e.target_id = ? AND e.edge_type = 'about'
        LIMIT 1
        """,
        (target_kind, target_id),
    ).fetchone() is not None


def _adherence_count(conn: sqlite3.Connection, decision_id: str) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM decision_playbook_rules WHERE decision_id = ?", (decision_id,)).fetchone()[0])


def _score_id(conn: sqlite3.Connection, forecast_id: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM forecast_scores WHERE forecast_id = ? ORDER BY scored_at ASC, id ASC LIMIT 1",
        (forecast_id,),
    ).fetchone()
    return row[0] if row else None


def _score_outcome_id(conn: sqlite3.Connection, score_id: str) -> str | None:
    row = conn.execute("SELECT outcome_id FROM forecast_scores WHERE id = ?", (score_id,)).fetchone()
    return row[0] if row and row[0] else None


def _outcome_id_for_decision(conn: sqlite3.Connection, decision: dict[str, Any]) -> str | None:
    row = conn.execute(
        "SELECT id FROM outcomes WHERE instrument_id = ? ORDER BY resolved_at ASC, id ASC LIMIT 1",
        (decision["instrument_id"],),
    ).fetchone()
    return row[0] if row else None


def _outcome_id_for_forecast(conn: sqlite3.Connection, forecast: dict[str, Any]) -> str | None:
    row = conn.execute(
        "SELECT id FROM outcomes WHERE instrument_id = ? ORDER BY resolved_at ASC, id ASC LIMIT 1",
        (forecast["instrument_id"],),
    ).fetchone()
    return row[0] if row else None


def _has_later_resolved_decision(conn: sqlite3.Connection, decision: dict[str, Any]) -> bool:
    return conn.execute(
        """
        SELECT 1 FROM decisions d
        WHERE d.type = 'resolved' AND d.id != ? AND d.created_at >= ?
          AND (d.instrument_id = ? OR (d.thesis_id IS NOT NULL AND d.thesis_id = ?) OR (d.forecast_id IS NOT NULL AND d.forecast_id = ?))
        ORDER BY d.created_at ASC, d.id ASC LIMIT 1
        """,
        (decision["id"], decision["created_at"], decision["instrument_id"], decision["thesis_id"], decision["forecast_id"]),
    ).fetchone() is not None


def _review_overdue(value: str | None, as_of_dt: datetime) -> bool:
    if not value:
        return False
    return _parse_ts(value) <= as_of_dt


def _is_stale(created_at: str, threshold_dt: datetime) -> bool:
    return _parse_ts(created_at) < threshold_dt


def _reflection_due(decision: dict[str, Any], *, has_outcome: bool, has_score: bool, reflected: bool) -> bool:
    return (
        not reflected
        and (has_outcome or has_score)
        and decision["type"] == "review"
    )


def _case_sort_key(case: LifecycleCase) -> tuple[str, str, str]:
    created_at = case.timestamps.get("created_at") or ""
    return (created_at, case.case_id, case.state)


__all__ = ["LifecycleCase", "LifecycleState", "derive_lifecycle_cases", "report_lifecycle"]
