"""Deterministic replay candidate-output process evaluator.

The v0 evaluator is intentionally syntactic/structural. It consumes only a
caller-supplied replay.case_bundle payload and candidate_output object, performs
no model execution, fetch, simulation, scoring engine, or writes, and returns
machine-readable process criteria.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any, Literal

from trade_trace.tools.decision_matrix import allowed_decision_types

CONTRACT_VERSION = "replay.evaluate_output.v0"
DEFAULT_RUBRIC_VERSION = "replay.rubric.v0"
Status = Literal["pass", "fail", "ambiguous", "not_applicable"]

_BOUNDARY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("profitability_claim", r"\b(profit guarantee|guaranteed profit|risk[- ]free profit|profit proof|will profit)\b"),
    ("alpha_signal", r"\b(alpha|trading signal|market signal)\b"),
    ("trading_advice", r"\b(buy recommendation|sell recommendation|recommend (buy|sell)|should buy|should sell)\b"),
    ("execution_or_fill", r"\b(simulated fill|filled at|executed trade|placed order|broker execution)\b"),
    ("backtest_claim", r"\b(backtest return|backtested return|backtester|backtest shows)\b"),
    ("fetch_or_model_run", r"\b(fetched live|queried the internet|ran external model|called gpt|model runner)\b"),
    ("market_path_reconstruction", r"\b(market path reconstruction|reconstructed market path)\b"),
)


def _stable_hash(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _text(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False).lower()


def _non_empty(value: Any) -> bool:
    return value not in (None, "", [], {})


def _ids_from_refs(refs: Any) -> set[str]:
    ids: set[str] = set()
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, dict) and isinstance(ref.get("id"), str):
                ids.add(ref["id"])
            elif isinstance(ref, str):
                ids.add(ref)
    return ids


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


def _case_items(bundle: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Return dict-shaped cases and the count of malformed case entries."""

    cases = bundle.get("cases")
    if not isinstance(cases, list):
        return [], 1 if cases is not None else 0
    valid = [case for case in cases if isinstance(case, dict)]
    return valid, len(cases) - len(valid)


def _case_context(case: dict[str, Any]) -> dict[str, Any]:
    ctx = case.get("point_in_time_context")
    return ctx if isinstance(ctx, dict) else {}


def _visible_ref_ids(bundle: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for case in _case_items(bundle)[0]:
        ids.add(case.get("case_id", ""))
        ids |= _ids_from_refs(case.get("source_refs")) | _ids_from_refs(case.get("evidence_refs"))
        ctx = _case_context(case)
        for node in _walk(ctx):
            for key in ("source_refs", "evidence_refs"):
                ids |= _ids_from_refs(node.get(key))
            for key in ("source_id", "forecast_id", "thesis_id", "snapshot_id", "instrument_id", "recall_id"):
                if isinstance(node.get(key), str):
                    ids.add(node[key])
    return {i for i in ids if i}


def _future_ref_ids(bundle: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in bundle.get("excluded_artifacts") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            reason = str(item.get("reason") or "").lower()
            if "future" in reason or "post_as_of" in reason or "evaluator" in reason:
                ids.add(item["id"])
    labels = (bundle.get("evaluation_labels") or {}).get("labels") or []
    for node in _walk(labels):
        for key, value in node.items():
            if key.endswith("_id") and key != "case_id" and isinstance(value, str):
                ids.add(value)
    return ids


def _candidate_case_ids(candidate_output: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("case_id", "case_ids"):
        value = candidate_output.get(key)
        if isinstance(value, str):
            ids.add(value)
        elif isinstance(value, list):
            ids |= {v for v in value if isinstance(v, str)}
    per_case = candidate_output.get("cases") or candidate_output.get("case_outputs") or candidate_output.get("per_case_outputs")
    if isinstance(per_case, list):
        for item in per_case:
            if isinstance(item, dict) and isinstance(item.get("case_id"), str):
                ids.add(item["case_id"])
    return ids


def _has_forecast(candidate_output: dict[str, Any], case_ids: set[str]) -> bool:
    if _non_empty(candidate_output.get("forecast")):
        return True
    for key in ("cases", "case_outputs", "per_case_outputs"):
        value = candidate_output.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("case_id") in case_ids and _non_empty(item.get("forecast")):
                    return True
    return False


def _candidate_citation_ids(candidate_output: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    nodes = [candidate_output]
    for key in ("cases", "case_outputs", "per_case_outputs"):
        value = candidate_output.get(key)
        if isinstance(value, list):
            nodes.extend(item for item in value if isinstance(item, dict))
    for node in nodes:
        for key in ("citations", "source_refs", "evidence_refs", "memory_use"):
            value = node.get(key)
            ids |= _ids_from_refs(value)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        for subkey in ("id", "source_id", "memory_id", "evidence_id"):
                            if isinstance(item.get(subkey), str):
                                ids.add(item[subkey])
                        ids |= _ids_from_refs(item.get("source_refs")) | _ids_from_refs(item.get("evidence_refs"))
    return ids


def _case_caveat_codes(bundle: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    for case in _case_items(bundle)[0]:
        codes |= {c for c in case.get("caveat_codes") or [] if isinstance(c, str)}
        for node in _walk(_case_context(case)):
            codes |= {c for c in node.get("caveat_codes") or [] if isinstance(c, str)}
    return codes


def _result(criterion: str, status: Status, severity: str, message: str, *, source_refs: list[Any] | None = None, caveat_codes: list[str] | None = None, evidence_refs: list[Any] | None = None) -> dict[str, Any]:
    return {"criterion": criterion, "status": status, "severity": severity, "message": message, "source_refs": source_refs or [], "caveat_codes": caveat_codes or [], "evidence_refs": evidence_refs or []}


def evaluate_output(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("kind") not in (None, "replay.evaluate_output"):
        raise ValueError("kind must be replay.evaluate_output when supplied")
    if args.get("contract_version") not in (None, CONTRACT_VERSION):
        raise ValueError(f"contract_version must be {CONTRACT_VERSION}")
    bundle = args.get("case_bundle")
    candidate = args.get("candidate_output")
    if not isinstance(bundle, dict):
        raise ValueError("case_bundle must be an object")
    if not isinstance(candidate, dict):
        raise ValueError("candidate_output must be an object")
    rubric = args.get("rubric_version", DEFAULT_RUBRIC_VERSION)

    cases, malformed_case_count = _case_items(bundle)
    raw_candidate_task = bundle.get("candidate_task")
    candidate_task: dict[str, Any] = raw_candidate_task if isinstance(raw_candidate_task, dict) else {}
    case_ids: set[str] = {c["case_id"] for c in cases if isinstance(c.get("case_id"), str)}
    results: list[dict[str, Any]] = []

    valid_bundle = bundle.get("kind") == "replay.case_bundle" and bundle.get("contract_version") == "replay.case_bundle.v0" and bool(case_ids) and malformed_case_count == 0
    bundle_msg = "Bundle kind/version is valid and case IDs are present."
    bundle_contract_caveats: list[str] = []
    if not valid_bundle:
        bundle_msg = "Expected replay.case_bundle.v0 with at least one case_id and dict-shaped cases."
        if malformed_case_count:
            bundle_msg += f" Ignored {malformed_case_count} malformed case entr{'y' if malformed_case_count == 1 else 'ies'}."
            bundle_contract_caveats.append("malformed_case_entries")
    results.append(_result("bundle_contract", "pass" if valid_bundle else "fail", "blocking", bundle_msg, source_refs=list(bundle.get("case_index") or []), caveat_codes=bundle_contract_caveats))

    required = candidate_task.get("candidate_metadata_required") or []
    # Accept `candidate_metadata` as an alias for `metadata`: the bundle field is
    # named `candidate_metadata_required`, there is no published
    # replay.candidate_output.v0 schema to consult, and this module is already
    # alias-tolerant for case ids / citations, so a caller reasonably reaches for
    # `candidate_metadata`. Without this, a fully-supplied-but-misplaced metadata
    # block reports every field "missing", indistinguishable from absent. AX-053.
    raw_metadata = candidate.get("metadata")
    if not isinstance(raw_metadata, dict):
        raw_metadata = candidate.get("candidate_metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    missing = [field for field in required if not _non_empty(metadata.get(field))]
    results.append(_result("candidate_metadata", "pass" if not missing else "fail", "blocking", "All required candidate metadata fields are present." if not missing else "Missing required candidate metadata fields: " + ", ".join(missing), caveat_codes=["missing_candidate_metadata"] if missing else []))

    cited_cases = _candidate_case_ids(candidate)
    if len(case_ids) <= 1:
        coverage_ok = bool(cited_cases & case_ids)
    else:
        coverage_ok = case_ids <= cited_cases
    results.append(_result("case_coverage", "pass" if coverage_ok else "fail", "blocking", "Candidate output covers required replay case IDs." if coverage_ok else "Candidate output must reference the single case_id or cover all case_ids for multi-case bundles.", evidence_refs=sorted(cited_cases)))

    cand_text = _text(candidate)
    future_ids = _future_ref_ids(bundle)
    leaked_ids = sorted(i for i in future_ids if i and i.lower() in cand_text)
    forbidden_sections = [s for s in ("evaluation_labels", "future_labels", "forecast_scores", "post_as_of") if s in cand_text]
    leak = leaked_ids or forbidden_sections
    results.append(_result("future_leakage", "fail" if leak else "pass", "blocking", "Candidate output does not mention evaluator-only/future artifact IDs or sections." if not leak else "Candidate output mentions evaluator-only/future artifacts or sections.", source_refs=leaked_ids, caveat_codes=forbidden_sections))

    mode = candidate_task.get("mode")
    needs_forecast = mode == "forecast_only" or any(_non_empty(_case_context(c).get("forecasts")) for c in cases)
    has_context = any(_non_empty(_case_context(c).get("forecasts")) or c.get("case_type") == "forecast" for c in cases)
    if needs_forecast and not has_context:
        forecast_status: Status = "ambiguous"
        forecast_msg = "Forecast appears required, but bundle has no forecast context to anchor the check."
    elif needs_forecast:
        forecast_status = "pass" if _has_forecast(candidate, case_ids) else "fail"
        forecast_msg = "Required forecast section is present." if forecast_status == "pass" else "Forecast is required for this replay task/case context but is missing."
    else:
        forecast_status = "not_applicable"
        forecast_msg = "Forecast is not required by task mode or visible case context."
    results.append(_result("forecast_required", forecast_status, "blocking" if forecast_status == "fail" else "advisory", forecast_msg))

    decision = candidate.get("decision") if isinstance(candidate.get("decision"), dict) else candidate
    decision_type = (decision.get("type") or decision.get("decision_type")) if isinstance(decision, dict) else None
    if isinstance(decision_type, str):
        ok = decision_type in allowed_decision_types()
        results.append(_result("decision_type", "pass" if ok else "fail", "blocking", f"decision type {decision_type!r} is allowed." if ok else f"decision type {decision_type!r} is not allowed.", caveat_codes=[] if ok else ["invalid_decision_type"]))
    else:
        status: Status = "ambiguous" if mode != "forecast_only" else "not_applicable"
        results.append(_result("decision_type", status, "advisory", "No decision type present to validate."))

    citation_ids = _candidate_citation_ids(candidate)
    visible = _visible_ref_ids(bundle)
    invalid_cites = sorted(citation_ids - visible)
    insufficient = bool(candidate.get("insufficient_context"))
    if citation_ids:
        status = "fail" if invalid_cites else "pass"
        msg = "All candidate citations resolve to candidate-visible context." if not invalid_cites else "Candidate cites IDs not present in candidate-visible context."
    else:
        status = "ambiguous" if insufficient else "fail"
        msg = "No citations supplied; candidate claims insufficient context." if insufficient else "Candidate supplied no source/memory citations."
    results.append(_result("citation_coverage", status, "blocking" if status == "fail" else "advisory", msg, source_refs=sorted(citation_ids), caveat_codes=["unresolved_citations"] if invalid_cites else []))

    playbook_exists = any(isinstance(_case_context(c).get("playbook_state"), dict) and _non_empty(_case_context(c).get("playbook_state")) and _case_context(c).get("playbook_state", {}).get("status") != "not_included_v0" for c in cases)
    pb = candidate.get("playbook_adherence")
    if not playbook_exists:
        pb_status: Status = "not_applicable"
        pb_msg = "No playbook context exists in the bundle."
    elif isinstance(pb, dict) and (_non_empty(pb.get("source_refs")) or _non_empty(pb.get("caveats")) or _non_empty(pb.get("caveat_codes"))):
        pb_status = "pass"
        pb_msg = "playbook_adherence section includes refs or caveats."
    else:
        pb_status = "ambiguous"
        pb_msg = "Playbook context exists but playbook_adherence refs/caveats are missing."
    results.append(_result("playbook_adherence", pb_status, "advisory", pb_msg))

    bundle_caveats = _case_caveat_codes(bundle)
    cand_caveats = set()
    caveat_obj = candidate.get("caveats") or candidate.get("caveat_codes") or []
    if isinstance(caveat_obj, list):
        cand_caveats = {c if isinstance(c, str) else c.get("code") for c in caveat_obj if isinstance(c, (str, dict))}
    elif isinstance(caveat_obj, dict):
        cand_caveats = {c for c in caveat_obj.get("caveat_codes", []) if isinstance(c, str)}
    if not bundle_caveats:
        cav_status: Status = "not_applicable"
        cav_msg = "Bundle has no source/context caveat codes."
    elif insufficient or (bundle_caveats & cand_caveats):
        cav_status = "pass"
        cav_msg = "Candidate acknowledges at least one bundle caveat or marks insufficient_context."
    else:
        cav_status = "ambiguous"
        cav_msg = "Bundle has caveats, but candidate did not acknowledge caveat codes."
    results.append(_result("source_caveat_handling", cav_status, "advisory", cav_msg, caveat_codes=sorted(bundle_caveats)))

    hits = [code for code, pattern in _BOUNDARY_PATTERNS if re.search(pattern, cand_text)]
    results.append(_result("boundary_language", "fail" if hits else "pass", "blocking", "Candidate output avoids forbidden advice/profit/simulation/fetch/model-run claims." if not hits else "Candidate output contains forbidden boundary language.", caveat_codes=hits))

    label_text = _text((bundle.get("evaluation_labels") or {}).get("labels") or [])
    has_scores = "forecast_score_id" in label_text or "forecast_scores" in label_text
    results.append(_result("later_scoring", "not_applicable", "advisory", "Forecast scores exist, but v0 does not perform scoring/backtest/profit comparisons." if has_scores else "No evaluator forecast_scores are present for later scoring."))

    counts = Counter(r["status"] for r in results)
    blocking_failures = sum(1 for r in results if r["status"] == "fail" and r["severity"] == "blocking")
    overall = "fail" if blocking_failures else "ambiguous" if counts.get("ambiguous") else "pass"
    request_equivalent = {"contract_version": CONTRACT_VERSION, "rubric_version": rubric, "case_bundle": bundle, "candidate_output": candidate}
    return {
        "kind": "replay.evaluate_output",
        "contract_version": CONTRACT_VERSION,
        "evaluation_id": _stable_hash(request_equivalent),
        "metadata": {"deterministic": True, "read_only": True, "rubric_version": rubric},
        "bundle_ref": {"bundle_id": bundle.get("bundle_id"), "case_ids": sorted(case_ids), "as_of": ((bundle.get("as_of_boundary") or {}).get("as_of"))},
        "criteria_results": results,
        "summary": {"counts_by_status": {k: counts.get(k, 0) for k in ("pass", "fail", "ambiguous", "not_applicable")}, "blocking_failure_count": blocking_failures, "overall_status": overall},
        "hard_constraints": {"local": True, "read_only": True, "no_fetch": True, "no_model_runner": True, "no_market_simulator": True, "no_backtester": True, "no_profit_proof": True, "no_trading_advice": True},
        "caveats": ["v0 is a deterministic syntactic/process checker, not semantic NLP judgment.", "No causal, profit, backtest, market-simulation, or trading-advice scoring is performed.", "No model execution or external data fetch is performed."],
    }
