"""Deterministic local replay case bundle export.

This module implements the v0 ``replay.case_bundle`` read surface. It only
packages caller-supplied local journal rows; it does not fetch, simulate,
evaluate, run a model, or write replay receipts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from trade_trace.timestamps import to_utc_iso8601

CONTRACT_VERSION = "replay.case_bundle.v0"
DEFAULT_BUDGETS = {
    "max_chars_total": 24000,
    "default_max_items_per_section": 10,
    "default_max_chars_per_section": 4000,
    "include_source_bodies": False,
    "include_memory_bodies": False,
    "include_sensitive_sources": False,
    "redaction_policy": "metadata_and_snippets_only",
}
# Budget keys a caller may NOT flip on: they would weaken the bundle's
# fixed redaction posture (bead trade-trace-jm14). _validate_request strips
# these from caller-supplied budgets so DEFAULT_BUDGETS always wins.
_SECURITY_GATE_BUDGET_KEYS = frozenset(
    {"include_sensitive_sources", "include_source_bodies", "include_memory_bodies"}
)
ALLOWED_TASK_MODES = ["blind_decision", "forecast_only", "review_original"]
_ALLOWED_FILTERS = {
    "time_window": {"created_at_gte", "created_at_lt"},
    "actors": {"agent_id", "model_id", "environment", "run_id"},
    "strategy": {"strategy_id"},
    "instrument": {"instrument_id", "symbol"},
    "decision": {"decision_type", "has_forecast"},
}


def _utc(value: str | None) -> str:
    if value is None:
        raise ValueError("as_of is required for replay.case_bundle")
    return to_utc_iso8601(value, field="as_of")


def _hash(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _case_id(kind: str, source_id: str, as_of: str, mode: str) -> str:
    suffix = hashlib.sha256(f"{kind}|{source_id}|{as_of}|{mode}|{CONTRACT_VERSION}".encode()).hexdigest()[:16]
    return f"derived:{kind}:{source_id}:replay:v0:{suffix}"


def _clip(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    return text if len(text) <= limit else text[: max(0, limit - 20)] + "…[truncated]"


def _validate_request(args: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    if args.get("kind") not in (None, "replay.case_bundle"):
        raise ValueError("kind must be replay.case_bundle when supplied")
    if args.get("contract_version") not in (None, CONTRACT_VERSION):
        raise ValueError(f"contract_version must be {CONTRACT_VERSION}")
    as_of = _utc(args.get("as_of"))
    selection = args.get("case_selection") or {}
    if not isinstance(selection, dict):
        raise ValueError("case_selection must be an object")
    task = args.get("task") or {}
    if not isinstance(task, dict):
        raise ValueError("task must be an object")
    mode = task.get("mode", "blind_decision")
    if mode not in ALLOWED_TASK_MODES:
        raise ValueError(f"task.mode must be one of {ALLOWED_TASK_MODES}")
    task = {**task, "mode": mode, "include_evaluation_labels": bool(task.get("include_evaluation_labels", False))}
    # Security-gate budget keys are NOT caller-overridable: the replay/review
    # bundle must unconditionally exclude sensitive sources and long-form
    # bodies regardless of what a caller passes (security.md §6.5/§8, bead
    # trade-trace-jm14). Strip them from caller input before merging so the
    # hardened DEFAULT_BUDGETS values always win.
    caller_budgets = {
        k: v
        for k, v in (args.get("budgets") or {}).items()
        if k not in _SECURITY_GATE_BUDGET_KEYS
    }
    budgets = {**DEFAULT_BUDGETS, **caller_budgets}
    if not isinstance(budgets["default_max_items_per_section"], int) or budgets["default_max_items_per_section"] < 0:
        raise ValueError("budgets.default_max_items_per_section must be a non-negative integer")
    if not isinstance(budgets["default_max_chars_per_section"], int) or budgets["default_max_chars_per_section"] < 1:
        raise ValueError("budgets.default_max_chars_per_section must be a positive integer")
    return as_of, selection, task, budgets


def _reject_unsupported_filter(raw: Any) -> None:
    if raw in (None, {}):
        return
    if not isinstance(raw, dict):
        raise ValueError("case_selection.filter must be an object")
    bad: list[str] = []
    for section, value in raw.items():
        if value in (None, {}, []):
            continue
        if section not in _ALLOWED_FILTERS or not isinstance(value, dict):
            bad.append(section)
            continue
        for key, leaf in value.items():
            if leaf in (None, [], {}):
                continue
            if key not in _ALLOWED_FILTERS[section]:
                bad.append(f"{section}.{key}")
    if bad:
        raise ValueError("unsupported replay.case_bundle filter fields: " + ", ".join(sorted(bad)))


def _source_ref(kind: str, id_: str) -> dict[str, str]:
    return {"kind": kind, "id": id_}


def _replay_artifact_refs(conn: sqlite3.Connection, strategy_id: str | None, as_of: str) -> list[dict[str, Any]]:
    """Return evaluator-only replay/evaluation artifact refs available by as_of."""

    if not strategy_id:
        return []
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='replay_evaluation_artifacts'").fetchone() is None:
        return []
    rows = conn.execute(
        """
        SELECT id, artifact_type, evidence_mode, dataset_hash, strategy_version, sample_size, as_of, imported_at
        FROM replay_evaluation_artifacts
        WHERE strategy_id = ? AND as_of <= ? AND imported_at <= ?
        ORDER BY as_of DESC, imported_at DESC, id
        LIMIT 10
        """,
        (strategy_id, as_of, as_of),
    ).fetchall()
    return [
        {
            "kind": "replay_evaluation_artifact",
            "id": row[0],
            "artifact_type": row[1],
            "evidence_mode": row[2],
            "dataset_hash": row[3],
            "strategy_version": row[4],
            "sample_size": row[5],
            "as_of": row[6],
            "imported_at": row[7],
            "candidate_visible": False,
            "caveat_codes": ["evaluator_only_artifact_ref", "externally_supplied_no_trade_trace_backtest"],
        }
        for row in rows
    ]


def _add_value_filter(clauses: list[str], params: list[Any], column: str, value: Any) -> None:
    if isinstance(value, list) and value:
        clauses.append(f"{column} IN ({','.join('?' for _ in value)})")
        params.extend(value)
    elif isinstance(value, str):
        clauses.append(f"{column} = ?")
        params.append(value)


def _validity_clause(alias: str) -> str:
    return f"{alias}.created_at <= ? AND ({alias}.valid_from IS NULL OR {alias}.valid_from <= ?) AND ({alias}.valid_to IS NULL OR ? < {alias}.valid_to) AND ({alias}.invalidated_at IS NULL OR {alias}.invalidated_at > ?)"


def _validity_params(as_of: str) -> tuple[str, str, str, str]:
    return (as_of, as_of, as_of, as_of)


def _valid_at_as_of(row: sqlite3.Row, as_of: str) -> bool:
    return (
        row["created_at"] <= as_of
        and (row["valid_from"] is None or row["valid_from"] <= as_of)
        and (row["valid_to"] is None or as_of < row["valid_to"])
        and (row["invalidated_at"] is None or row["invalidated_at"] > as_of)
    )


def _selection_refs_from_case_ids(selection: dict[str, Any], as_of: str, mode: str) -> list[dict[str, str]]:
    case_ids = selection.get("case_ids") or []
    if not case_ids:
        return []
    if not isinstance(case_ids, list) or not all(isinstance(cid, str) for cid in case_ids):
        raise ValueError("case_selection.case_ids must be a list of replay.case_bundle v0 case ID strings")
    refs: list[dict[str, str]] = []
    for cid in case_ids:
        parts = cid.split(":")
        if len(parts) != 6 or parts[0] != "derived" or parts[3:5] != ["replay", "v0"]:
            raise ValueError("case_selection.case_ids only supports replay.case_bundle v0 derived case IDs")
        kind, source_id = parts[1], parts[2]
        if kind not in {"decision", "forecast", "recall_event"} or cid != _case_id(kind, source_id, as_of, mode):
            raise ValueError("case_selection.case_ids must match this as_of and task.mode")
        refs.append({"kind": kind, "id": source_id})
    return refs


def _rows_for_selection(conn: sqlite3.Connection, selection: dict[str, Any], as_of: str, mode: str) -> list[dict[str, Any]]:
    _reject_unsupported_filter(selection.get("filter"))
    max_cases = selection.get("max_cases", 25)
    if not isinstance(max_cases, int) or max_cases < 1:
        raise ValueError("case_selection.max_cases must be a positive integer")
    refs = selection.get("source_refs") or _selection_refs_from_case_ids(selection, as_of, mode)
    if refs and selection.get("source_refs") and selection.get("case_ids"):
        raise ValueError("case_selection.case_ids and source_refs are mutually exclusive")
    if refs and (not isinstance(refs, list) or not all(isinstance(r, dict) for r in refs)):
        raise ValueError("case_selection.source_refs must be a list of objects")
    selected: list[dict[str, Any]] = []
    for ref in refs:
        kind, rid = ref.get("kind"), ref.get("id")
        if kind not in {"decision", "forecast", "recall_event"} or not isinstance(rid, str):
            raise ValueError("source_refs support decision, forecast, and recall_event ids")
        if kind == "recall_event":
            row = conn.execute("SELECT recall_id, created_at FROM memory_recall_events WHERE recall_id = ?", (rid,)).fetchone()
            if row is None:
                raise ValueError(f"recall_event source_ref is not locally verifiable at as_of: {rid}")
            if row["created_at"] > as_of:
                raise ValueError(f"recall_event source_ref was created after as_of: {rid}")
            selected.append({"source_kind": kind, "source_id": rid, "created_at": row["created_at"], "row": None})
            continue
        table = "decisions" if kind == "decision" else "forecasts"
        if kind == "forecast":
            row = conn.execute(
                f"SELECT f.* FROM forecasts f JOIN theses t ON t.id = f.thesis_id WHERE f.id = ? AND {_validity_clause('f')} AND {_validity_clause('t')}",
                (rid, *_validity_params(as_of), *_validity_params(as_of)),
            ).fetchone()
        else:
            row = conn.execute(f"SELECT * FROM {table} WHERE id = ? AND created_at <= ?", (rid, as_of)).fetchone()
        if row is not None:
            selected.append({"source_kind": kind, "source_id": rid, "created_at": row["created_at"], "row": row})
    if not refs:
        raw_filter = selection.get("filter") or {}
        clauses = ["d.created_at <= ?"]
        params: list[Any] = [as_of]
        tw = raw_filter.get("time_window") or {}
        if tw.get("created_at_gte"):
            clauses.append("d.created_at >= ?")
            params.append(to_utc_iso8601(tw["created_at_gte"], field="case_selection.filter.time_window.created_at_gte"))
        if tw.get("created_at_lt"):
            clauses.append("d.created_at < ?")
            params.append(to_utc_iso8601(tw["created_at_lt"], field="case_selection.filter.time_window.created_at_lt"))
        for section, colmap in {"actors": {"agent_id": "d.agent_id", "model_id": "d.model_id", "environment": "d.environment", "run_id": "d.run_id"}, "instrument": {"instrument_id": "d.instrument_id", "symbol": "i.symbol"}, "strategy": {"strategy_id": "d.strategy_id"}}.items():
            vals = raw_filter.get(section) or {}
            for key, col in colmap.items():
                _add_value_filter(clauses, params, col, vals.get(key))
        dec = raw_filter.get("decision") or {}
        if dec.get("decision_type"):
            v = dec["decision_type"]
            clauses.append(f"d.type IN ({','.join('?' for _ in v)})")
            params.extend(v)
        if dec.get("has_forecast") is True:
            clauses.append("d.forecast_id IS NOT NULL")
        elif dec.get("has_forecast") is False:
            clauses.append("d.forecast_id IS NULL")
        selected_decision_forecast_ids: list[str] = []
        for row in conn.execute(f"SELECT d.* FROM decisions d LEFT JOIN instruments i ON i.id = d.instrument_id WHERE {' AND '.join(clauses)} ORDER BY d.created_at, 'decision', d.id LIMIT ?", (*params, max_cases)).fetchall():
            selected.append({"source_kind": "decision", "source_id": row["id"], "created_at": row["created_at"], "row": row})
            if row["forecast_id"]:
                selected_decision_forecast_ids.append(row["forecast_id"])
        if len(selected) < max_cases:
            f_clauses = [_validity_clause("f"), _validity_clause("t")]
            f_params: list[Any] = [*_validity_params(as_of), *_validity_params(as_of)]
            if tw.get("created_at_gte"):
                f_clauses.append("f.created_at >= ?")
                f_params.append(to_utc_iso8601(tw["created_at_gte"], field="case_selection.filter.time_window.created_at_gte"))
            if tw.get("created_at_lt"):
                f_clauses.append("f.created_at < ?")
                f_params.append(to_utc_iso8601(tw["created_at_lt"], field="case_selection.filter.time_window.created_at_lt"))
            for section, colmap in {"actors": {"agent_id": "f.agent_id", "model_id": "f.model_id", "environment": "f.environment", "run_id": "f.run_id"}, "instrument": {"instrument_id": "t.instrument_id", "symbol": "i.symbol"}, "strategy": {"strategy_id": "t.strategy_id"}}.items():
                vals = raw_filter.get(section) or {}
                for key, col in colmap.items():
                    _add_value_filter(f_clauses, f_params, col, vals.get(key))
            if dec and selected_decision_forecast_ids:
                f_clauses.append(f"f.id IN ({','.join('?' for _ in selected_decision_forecast_ids)})")
                f_params.extend(selected_decision_forecast_ids)
            elif dec:
                f_clauses.append("0")
            for row in conn.execute(f"SELECT f.* FROM forecasts f JOIN theses t ON t.id = f.thesis_id JOIN instruments i ON i.id = t.instrument_id WHERE {' AND '.join(f_clauses)} ORDER BY f.created_at, f.id LIMIT ?", (*f_params, max_cases-len(selected))).fetchall():
                selected.append({"source_kind": "forecast", "source_id": row["id"], "created_at": row["created_at"], "row": row})
    return sorted(selected, key=lambda r: (r["created_at"], r["source_kind"], r["source_id"]))[:max_cases]


def _instrument(conn: sqlite3.Connection, instrument_id: str | None, as_of: str) -> dict[str, Any] | None:
    if not instrument_id:
        return None
    row = conn.execute("SELECT i.id, i.title, i.symbol, i.asset_class, i.venue_id, i.created_at FROM instruments i WHERE i.id = ? AND i.created_at <= ?", (instrument_id, as_of)).fetchone()
    if row is None:
        return None
    return {"instrument_id": row[0], "title": row[1], "symbol": row[2], "asset_class": row[3], "venue_id": row[4], "created_at": row[5], "source_refs": [_source_ref("instrument", row[0])]}


def _case(conn: sqlite3.Connection, item: dict[str, Any], as_of: str, task: dict[str, Any], budgets: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    kind, sid, row = item["source_kind"], item["source_id"], item["row"]
    cid = _case_id(kind, sid, as_of, task["mode"])
    refs = [_source_ref(kind, sid)]
    caveats: list[str] = []
    labels: dict[str, Any] = {"case_id": cid, "outcomes": [], "forecast_scores": [], "replay_evaluation_artifact_refs": [], "post_as_of_reflections": [], "post_as_of_source_updates": [], "post_as_of_playbook_changes": [], "original_artifact_for_blind_tasks": None, "source_refs": refs, "caveat_codes": ["evaluator_only_not_candidate_context"]}
    excluded: list[dict[str, Any]] = []
    ctx: dict[str, Any]
    if row is None:
        caveats.append("recall_event_context_summary_unavailable_v0")
        ctx = {"instrument": None, "snapshots": [], "theses": [], "forecasts": [], "sources": [], "strategy_state": {}, "playbook_state": {}, "memory_context": {}, "recall_receipts": [], "lifecycle_context": [], "work_queue_context": [], "prior_reports": []}
    else:
        r = dict(row)
        instrument_id = r.get("instrument_id")
        thesis_id = r.get("thesis_id")
        forecast_id = r.get("forecast_id") if kind == "decision" else r.get("id")
        strategy_id = r.get("strategy_id")
        if thesis_id:
            t = conn.execute("SELECT instrument_id, strategy_id FROM theses WHERE id = ?", (thesis_id,)).fetchone()
            if t and kind == "forecast":
                instrument_id = t[0]
            if t and not strategy_id:
                strategy_id = t[1]
        snapshots = []
        if kind == "decision" and r.get("snapshot_id"):
            s = conn.execute("SELECT id,instrument_id,captured_at,price,bid,ask,mid,spread,volume,open_interest,implied_probability,created_at FROM snapshots WHERE id = ? AND created_at <= ?", (r["snapshot_id"], as_of)).fetchone()
            if s:
                snapshots.append({"snapshot_id": s[0], "instrument_id": s[1], "captured_at": s[2], "price": s[3], "bid": s[4], "ask": s[5], "mid": s[6], "spread": s[7], "volume": s[8], "open_interest": s[9], "implied_probability": s[10], "created_at": s[11], "source_refs": [_source_ref("snapshot", s[0])]})
        theses = []
        if thesis_id:
            t = conn.execute("SELECT id,instrument_id,version,side,confidence_label,body,falsification_criteria,risk_notes,strategy_id,valid_from,valid_to,invalidated_at,created_at FROM theses WHERE id = ? AND created_at <= ?", (thesis_id, as_of)).fetchone()
            if t and _valid_at_as_of(t, as_of):
                theses.append({"thesis_id": t[0], "instrument_id": t[1], "version": t[2], "side": t[3], "confidence_label": t[4], "body_snippet": _clip(t[5], budgets["default_max_chars_per_section"]), "falsification_criteria": _clip(t[6], 500), "risk_notes": _clip(t[7], 500), "strategy_id": t[8], "valid_from": t[9], "valid_to": t[10], "invalidated_at": t[11], "created_at": t[12], "source_refs": [_source_ref("thesis", t[0])]})
            elif t:
                caveats.append("thesis_not_valid_at_as_of_excluded")
                excluded.append({"kind": "thesis", "id": t[0], "reason": "not_valid_at_as_of"})
        forecasts = []
        if forecast_id:
            f = conn.execute("SELECT id,thesis_id,kind,resolution_at,yes_label,resolution_rule_text,scoring_support,scoring_state,valid_from,valid_to,invalidated_at,created_at FROM forecasts WHERE id = ? AND created_at <= ?", (forecast_id, as_of)).fetchone()
            linked_thesis = conn.execute("SELECT id,instrument_id,version,side,confidence_label,body,falsification_criteria,risk_notes,strategy_id,valid_from,valid_to,invalidated_at,created_at FROM theses WHERE id = ? AND created_at <= ?", (f[1], as_of)).fetchone() if f and f[1] else None
            linked_thesis_valid = linked_thesis is None or _valid_at_as_of(linked_thesis, as_of)
            if f and _valid_at_as_of(f, as_of) and linked_thesis_valid:
                outcomes = conn.execute("SELECT outcome_label, probability, lower_bound, upper_bound FROM forecast_outcomes WHERE forecast_id = ? ORDER BY outcome_label", (f[0],)).fetchall()
                forecasts.append({"forecast_id": f[0], "thesis_id": f[1], "kind": f[2], "resolution_at": f[3], "yes_label": f[4], "resolution_rule_text": _clip(f[5], 500), "scoring_support": f[6], "scoring_state_as_of_caveat": "not_reconstructed_v0", "valid_from": f[8], "valid_to": f[9], "invalidated_at": f[10], "created_at": f[11], "outcomes": [{"outcome_label": o[0], "probability": o[1], "lower_bound": o[2], "upper_bound": o[3]} for o in outcomes], "source_refs": [_source_ref("forecast", f[0])]})
            elif f and _valid_at_as_of(f, as_of) and not linked_thesis_valid:
                caveats.append("forecast_linked_thesis_not_valid_at_as_of_excluded")
                excluded.append({"kind": "forecast", "id": f[0], "reason": "linked_thesis_not_valid_at_as_of"})
            elif f:
                caveats.append("forecast_not_valid_at_as_of_excluded")
                excluded.append({"kind": "forecast", "id": f[0], "reason": "not_valid_at_as_of"})
        sources = []
        for sk, si in [(kind, sid), ("forecast", forecast_id), ("thesis", thesis_id)]:
            if not si:
                continue
            rows = conn.execute("""SELECT DISTINCT s.id,s.kind,s.title,s.stance,s.freshness_at,s.captured_at,s.redaction_status,s.created_at,s.excerpt,s.summary FROM sources s JOIN edges e ON ((e.source_kind='source' AND e.source_id=s.id AND e.target_kind=? AND e.target_id=?) OR (e.target_kind='source' AND e.target_id=s.id AND e.source_kind=? AND e.source_id=?)) WHERE s.created_at <= ? AND e.created_at <= ? ORDER BY s.created_at,s.id LIMIT ?""", (sk, si, sk, si, as_of, as_of, budgets["default_max_items_per_section"])).fetchall()
            for s in rows:
                if s[6] == "sensitive" and not budgets["include_sensitive_sources"]:
                    continue
                sources.append({"source_id": s[0], "kind": s[1], "title": s[2], "stance": s[3], "freshness_at": s[4], "captured_at": s[5], "redaction_status": s[6], "created_at": s[7], "snippet": _clip(s[8] or s[9], 500), "source_refs": [_source_ref("source", s[0])]})
        ctx = {"instrument": _instrument(conn, instrument_id, as_of), "snapshots": snapshots, "theses": theses, "forecasts": [] if (kind == "forecast" and task["mode"] == "forecast_only") else forecasts, "sources": sources, "strategy_state": {"status": "summary_only", "caveat_codes": ["mutable_strategy_reconstruction"]}, "playbook_state": {"status": "summary_only"}, "memory_context": {"status": "not_included_v0"}, "recall_receipts": [], "lifecycle_context": [], "work_queue_context": [], "prior_reports": []}
        for o in conn.execute("SELECT id,resolved_at,outcome_label,status,created_at FROM outcomes WHERE instrument_id = ? AND created_at > ? ORDER BY created_at,id", (instrument_id, as_of)).fetchall():
            labels["outcomes"].append({"outcome_id": o[0], "resolved_at": o[1], "outcome_label": o[2], "status": o[3], "created_at": o[4], "source_refs": [_source_ref("outcome", o[0])]})
            excluded.append({"kind": "outcome", "id": o[0], "reason": "post_as_of_future_label"})
        if forecast_id:
            for fs in conn.execute("SELECT id,outcome_id,metric,score,scored_at FROM forecast_scores WHERE forecast_id = ? AND scored_at > ? ORDER BY scored_at,id", (forecast_id, as_of)).fetchall():
                labels["forecast_scores"].append({"forecast_score_id": fs[0], "outcome_id": fs[1], "metric": fs[2], "score": fs[3], "scored_at": fs[4], "source_refs": [_source_ref("forecast_score", fs[0])]})
                excluded.append({"kind": "forecast_score", "id": fs[0], "reason": "post_as_of_future_label"})
        if task["mode"] != "review_original":
            labels["original_artifact_for_blind_tasks"] = {"kind": kind, "id": sid}
            excluded.append({"kind": kind, "id": sid, "reason": "original_artifact_answer_withheld_for_blind_task"})
        if task["include_evaluation_labels"]:
            labels["replay_evaluation_artifact_refs"] = _replay_artifact_refs(conn, strategy_id, as_of)
            for artifact_ref in labels["replay_evaluation_artifact_refs"]:
                excluded.append({"kind": "replay_evaluation_artifact", "id": artifact_ref["id"], "reason": "evaluator_only_artifact_ref_not_candidate_context"})
        else:
            labels["replay_evaluation_artifact_refs"] = []
    original = {"status": "included" if task["mode"] == "review_original" else "withheld", "source_refs": refs}
    return {"case_id": cid, "case_key": {"source_kind": kind, "source_id": sid, "as_of": as_of, "task_mode": task["mode"]}, "case_type": kind, "eligibility_status": "needs_caveat" if caveats else "runnable", "original_artifact": original, "point_in_time_context": ctx, "candidate_instructions": {"mode": task["mode"], "produce_candidate_output_contract_version": task.get("candidate_output_contract_version", "replay.candidate_output.v0")}, "source_refs": refs, "evidence_refs": refs, "caveat_codes": caveats, "omitted_counts": {}, "truncation": {"is_partial": False}}, labels, excluded


def export_case_bundle(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    as_of, selection, task, budgets = _validate_request(args)
    items = _rows_for_selection(conn, selection, as_of, task["mode"])
    cases, label_rows, excluded = [], [], []
    for item in items:
        case, labels, exc = _case(conn, item, as_of, task, budgets)
        cases.append(case)
        label_rows.append(labels)
        excluded.extend(exc)
    data: dict[str, Any] = {
        "kind": "replay.case_bundle", "contract_version": CONTRACT_VERSION, "bundle_id": None,
        "metadata": {"case_count": len(cases), "deterministic": True, "read_only": True},
        "request": {"kind": "replay.case_bundle", "contract_version": CONTRACT_VERSION, "as_of": as_of, "case_selection": selection, "task": task},
        "as_of_boundary": {"as_of": as_of, "timezone": "UTC", "ordering": ["created_at", "source_kind", "id"], "inclusion_rule": "created_at <= as_of and, for versioned artifacts, valid_from <= as_of < valid_to with invalidated_at absent or > as_of", "no_wall_clock_dependence": True, "late_recording_policy": "records created after as_of are excluded even if they describe earlier world-time facts", "tie_break_policy": "source_kind_then_id", "caveat_codes": []},
        "case_index": [{"case_id": c["case_id"], **c["case_key"], "eligibility_status": c["eligibility_status"]} for c in cases],
        "cases": cases,
        "candidate_task": {"mode": task["mode"], "allowed_modes": ALLOWED_TASK_MODES, "candidate_metadata_required": ["agent_id", "model_id", "prompt_id_or_hash", "environment", "candidate_run_id", "tool_policy_id", "recall_policy_id", "playbook_version_id"], "accepted_output_sections": ["decision", "forecast", "citations", "memory_use", "playbook_adherence", "process_next_actions", "caveats", "insufficient_context"], "output_contract_version": task.get("candidate_output_contract_version", "replay.candidate_output.v0"), "rubric_version": task.get("rubric_version", "replay.rubric.v0"), "forbidden_output_claims": ["trade_recommendation", "profitability_claim", "simulated_fill", "market_path_reconstruction"]},
        "evaluation_labels": {"status": "included_for_evaluator_only", "labels": label_rows} if task["include_evaluation_labels"] else {"status": "withheld", "reason": "candidate_context_must_not_contain_future_labels"},
        "excluded_artifacts": excluded,
        "leakage_protections": {"candidate_context_excludes_future_labels": True, "evaluation_labels_separated": True, "as_of_required": True, "utc_only": True, "created_at_cutoff_enforced": True, "validity_window_enforced": True, "late_recording_caveated": True, "current_policy_excluded": True, "no_fetch_performed": True, "no_model_run_performed": True, "no_hidden_writes": True},
        "budgets": budgets,
        "truncation": {"is_partial": False, "omitted_counts": {}},
        "caveats": ["v0 supports decision/forecast cases and minimal recall_event source-ref selection; lifecycle/work_queue/recall details are summary-only when not directly reconstructable from local rows."],
        "hard_constraints": {"local_first": True, "caller_supplied_data_only": True, "read_only": True, "no_market_fetching": True, "no_model_runner": True, "no_market_simulator": True, "no_backtester": True, "no_profit_proof": True, "no_trading_advice": True},
    }
    data["bundle_id"] = _hash({k: v for k, v in data.items() if k != "bundle_id"})
    return data
