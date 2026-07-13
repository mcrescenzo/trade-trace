"""Audit-only risk policy version and risk-check receipt tools."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    canonical_json as _canonical_json,
)
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    db_for_args,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    reject_credential_metadata,
    reject_if_contains_secrets,
    require,
    store_metadata_json,
)
from trade_trace.tools.errors import ToolError

_POLICY_EVENT = "risk_policy_version.created"
_RECEIPT_EVENT = "risk_check_receipt.recorded"
STATUSES = {"pass", "warn", "fail", "missing_data"}
OUTCOMES = {"pass", "warning", "hard_block", "missing_data", "stale_data", "waived_warning"}
SEVERITIES = {"info", "warning", "hard_block", "missing_data"}
RECEIPT_ANCHOR_FIELDS = (
    "intended_action", "proposed_intent_hash", "decision_id", "market_id",
    "instrument_id", "strategy_id", "snapshot_id",
)


def _hash_payload(prefix: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(f"{prefix}:{_canonical_json(payload)}".encode()).hexdigest()


def _json_arg(args: dict[str, Any], field: str, default: Any) -> Any:
    value = args.get(field, default)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be valid JSON", details={"field": field}) from exc
    return value


def _list_arg(args: dict[str, Any], field: str) -> list[Any]:
    value = _json_arg(args, field, [])
    if not isinstance(value, list):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an array", details={"field": field})
    return value


def _dict_arg(args: dict[str, Any], field: str) -> dict[str, Any]:
    value = _json_arg(args, field, {})
    if not isinstance(value, dict):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"{field} must be an object", details={"field": field})
    return value


# ---------------------------------------------------------------------------
# Deterministic risk-check evaluator (trade-trace-g629)
#
# autonomous-trader-substrate.md §3.1 + §8 step 2: a deterministic evaluator
# that takes a proposed intent + a risk_policy_version + input snapshots and
# RETURNS per-rule results + an aggregate status. This is the "evaluate" half
# of the Phase-2 loop. It is pure (no DB writes, no execution), credential-blind,
# and emits no directional advice — only policy status. ``missing_data`` is NEVER
# a soft pass (§3.1): a rule that cannot be evaluated for lack of an input
# degrades the aggregate, it does not silently pass.
#
# A rule entry in ``rules_json`` is data, not prose:
#   {"rule_id": "...", "limit_class": "<class>", "severity": "warning"|"hard_block",
#    "threshold": <value-or-object>, "waiver": "none"|"warning"|"approval", ...}
# The ``limit_class`` selects the deterministic comparator below. Unknown limit
# classes are surfaced as ``missing_data`` (the evaluator refuses to guess) so a
# policy can never silently pass a rule the evaluator does not understand.
# ---------------------------------------------------------------------------

# Aggregate severity ranking: higher wins when folding per-rule severities into
# the aggregate status. Stable and total.
_SEVERITY_RANK: dict[str, int] = {
    "info": 0,
    "warning": 1,
    "missing_data": 2,
    "hard_block": 3,
}
# Map the worst per-rule severity to the aggregate status vocabulary.
_AGGREGATE_STATUS_FOR_SEVERITY: dict[str, str] = {
    "info": "pass",
    "warning": "warn",
    "missing_data": "missing_data",
    "hard_block": "fail",
}
# Map aggregate status to the receipt outcome vocabulary (OUTCOMES).
_AGGREGATE_OUTCOME_FOR_STATUS: dict[str, str] = {
    "pass": "pass",
    "warn": "warning",
    "missing_data": "missing_data",
    "fail": "hard_block",
}

# Stable reason codes. These are part of the evaluator's public contract; do not
# rename existing codes — only add new ones.
RC_WITHIN_LIMIT = "within_limit"
RC_LIMIT_EXCEEDED = "limit_exceeded"
RC_CATEGORY_BLOCKED = "category_blocked"
RC_CATEGORY_NOT_ALLOWED = "category_not_allowed"
RC_REQUIRED_LINK_MISSING = "required_link_missing"
RC_APPROVAL_REQUIRED = "approval_threshold_exceeded"
RC_PAPER_ONLY_VIOLATION = "paper_only_violation"
RC_CLOSE_ONLY_VIOLATION = "close_only_violation"
RC_MISSING_INPUT = "missing_input_data"
RC_STALE_INPUT = "stale_input_data"
RC_UNKNOWN_LIMIT_CLASS = "unknown_limit_class"
RC_MALFORMED_RULE = "malformed_rule"

# The §3.1 limit classes this evaluator understands.
LIMIT_CLASSES: frozenset[str] = frozenset({
    "notional",
    "market_exposure",
    "category_exposure",
    "total_exposure",
    "daily_loss",
    "weekly_loss",
    "spread",
    "slippage",
    "time_to_resolution",
    "allowed_categories",
    "blocked_categories",
    "required_links",
    "approval_threshold",
    "paper_only",
    "close_only",
})


def _coerce_number(value: Any) -> float | None:
    """Best-effort numeric coercion that refuses non-numeric junk.

    Strings are accepted (callers serialize proposed prices/sizes as strings),
    but only when they parse cleanly. Booleans are rejected because Python's
    ``bool`` is an ``int`` subtype and silently passing ``True`` as ``1`` would
    be a soft-pass foot-gun for a risk evaluator.

    Non-finite results (``NaN``, ``+/-Inf``) are also rejected and returned as
    ``None`` so the value is treated as ``missing_data`` rather than slipping
    through a comparator. ``nan > threshold`` evaluates to ``False`` in Python,
    so a NaN observed magnitude would otherwise silently return
    ``RC_WITHIN_LIMIT`` — a soft-pass of a hard-block limit, violating the
    evaluator's §3.1 invariant ("missing_data must NOT soft-pass"). NaN/Inf can
    arrive as inline strings (``'nan'``, ``'NaN'``, ``'inf'``, ``'1e9999'``) or
    as literal floats (``json.loads`` accepts a bare ``NaN`` by default), so the
    guard sits at this single coercion chokepoint shared by every numeric
    comparator (``_eval_numeric_max``, ``_eval_min``, ``_eval_approval_threshold``).
    """

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value.strip())
        except (ValueError, AttributeError):
            return None
    else:
        return None
    if not math.isfinite(result):
        return None
    return result


def _rule_result(
    *,
    rule_id: str,
    reason_code: str,
    severity: str,
    observed_value: Any = None,
    threshold: Any = None,
    contributing_record_ids: list[Any] | None = None,
    waiver_required: bool = False,
    caveat: str | None = None,
    missing_data: bool = False,
    stale_data: bool = False,
) -> dict[str, Any]:
    """Build one normalized per-rule result entry.

    Shape matches what ``risk.check_record`` accepts for ``rule_results`` so an
    evaluation can be recorded verbatim as a receipt without translation.
    """

    return {
        "rule_id": rule_id,
        "reason_code": reason_code,
        "severity": severity,
        "observed_value": observed_value,
        "threshold": threshold,
        "contributing_record_ids": list(contributing_record_ids or []),
        "waiver_required": waiver_required,
        "caveat": caveat,
        "missing_data": missing_data,
        "stale_data": stale_data,
    }


def _waiver_required(rule: dict[str, Any], severity: str) -> bool:
    """Deterministic waiver requirement for a *violating* rule.

    Policy ``waiver`` field: ``none`` (non-waivable hard block), ``warning``
    (warning-waivable), or ``approval`` (requires explicit operator approval).
    Defaults: hard_block rules are non-waivable unless the policy says otherwise;
    warnings are waivable.
    """

    waiver = rule.get("waiver")
    if waiver == "none":
        return True  # non-waivable: a waiver record is *required* to proceed
    if waiver == "approval":
        return True
    if waiver == "warning":
        return True
    # Default by severity when the policy is silent.
    return severity == "hard_block"


def _eval_numeric_max(
    rule: dict[str, Any],
    *,
    observed: Any,
    severity: str,
    source_label: str,
    contributing: list[Any],
) -> dict[str, Any]:
    """Compare an observed magnitude against a max threshold.

    Missing observed input => ``missing_data`` (never a soft pass). Used for
    notional, every exposure class, loss classes, spread, and slippage.
    """

    rule_id = str(rule.get("rule_id") or rule.get("limit_class"))
    threshold = _coerce_number(rule.get("threshold"))
    if threshold is None:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_MALFORMED_RULE, severity="missing_data",
            threshold=rule.get("threshold"), missing_data=True,
            caveat=f"rule {rule_id} has no numeric threshold",
        )
    value = _coerce_number(observed)
    if value is None:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_MISSING_INPUT, severity="missing_data",
            threshold={"max": threshold}, missing_data=True, contributing_record_ids=contributing,
            caveat=f"{source_label} unavailable for rule {rule_id}; cannot evaluate (missing_data is not a pass)",
        )
    if value > threshold:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_LIMIT_EXCEEDED, severity=severity,
            observed_value={source_label: value}, threshold={"max": threshold},
            contributing_record_ids=contributing, waiver_required=_waiver_required(rule, severity),
        )
    return _rule_result(
        rule_id=rule_id, reason_code=RC_WITHIN_LIMIT, severity="info",
        observed_value={source_label: value}, threshold={"max": threshold},
        contributing_record_ids=contributing,
    )


def _eval_min(
    rule: dict[str, Any], *, observed: Any, severity: str, source_label: str,
) -> dict[str, Any]:
    """Compare an observed magnitude against a *minimum* threshold.

    Used for time_to_resolution (intent must have at least N units of runway).
    """

    rule_id = str(rule.get("rule_id") or rule.get("limit_class"))
    threshold = _coerce_number(rule.get("threshold"))
    if threshold is None:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_MALFORMED_RULE, severity="missing_data",
            threshold=rule.get("threshold"), missing_data=True,
            caveat=f"rule {rule_id} has no numeric threshold",
        )
    value = _coerce_number(observed)
    if value is None:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_MISSING_INPUT, severity="missing_data",
            threshold={"min": threshold}, missing_data=True,
            caveat=f"{source_label} unavailable for rule {rule_id}; cannot evaluate (missing_data is not a pass)",
        )
    if value < threshold:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_LIMIT_EXCEEDED, severity=severity,
            observed_value={source_label: value}, threshold={"min": threshold},
            waiver_required=_waiver_required(rule, severity),
        )
    return _rule_result(
        rule_id=rule_id, reason_code=RC_WITHIN_LIMIT, severity="info",
        observed_value={source_label: value}, threshold={"min": threshold},
    )


def _eval_category(
    rule: dict[str, Any], *, category: Any, mode: str, severity: str,
) -> dict[str, Any]:
    """Allowed/blocked category gate.

    ``mode="blocked"``: violation if category is in the blocked set.
    ``mode="allowed"``: violation if category is NOT in the allowed set.
    Missing category on the intent => ``missing_data`` (cannot prove compliance).
    """

    rule_id = str(rule.get("rule_id") or rule.get("limit_class"))
    raw_set = rule.get("threshold")
    if isinstance(raw_set, dict):
        raw_set = raw_set.get("categories")
    if not isinstance(raw_set, list):
        return _rule_result(
            rule_id=rule_id, reason_code=RC_MALFORMED_RULE, severity="missing_data",
            threshold=rule.get("threshold"), missing_data=True,
            caveat=f"rule {rule_id} has no category list",
        )
    category_set = {str(c) for c in raw_set}
    if category is None or str(category).strip() == "":
        return _rule_result(
            rule_id=rule_id, reason_code=RC_MISSING_INPUT, severity="missing_data",
            threshold={mode: sorted(category_set)}, missing_data=True,
            caveat=f"intent category unavailable for rule {rule_id}; cannot evaluate (missing_data is not a pass)",
        )
    cat = str(category)
    if mode == "blocked":
        if cat in category_set:
            return _rule_result(
                rule_id=rule_id, reason_code=RC_CATEGORY_BLOCKED, severity=severity,
                observed_value={"category": cat}, threshold={"blocked": sorted(category_set)},
                waiver_required=_waiver_required(rule, severity),
            )
        return _rule_result(
            rule_id=rule_id, reason_code=RC_WITHIN_LIMIT, severity="info",
            observed_value={"category": cat}, threshold={"blocked": sorted(category_set)},
        )
    # allowed
    if cat not in category_set:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_CATEGORY_NOT_ALLOWED, severity=severity,
            observed_value={"category": cat}, threshold={"allowed": sorted(category_set)},
            waiver_required=_waiver_required(rule, severity),
        )
    return _rule_result(
        rule_id=rule_id, reason_code=RC_WITHIN_LIMIT, severity="info",
        observed_value={"category": cat}, threshold={"allowed": sorted(category_set)},
    )


def _eval_required_links(
    rule: dict[str, Any], *, intent: dict[str, Any], severity: str,
) -> dict[str, Any]:
    """Required forecast/thesis/decision (and other) link presence.

    ``threshold`` is a list of intent fields that must be non-empty, e.g.
    ``["forecast_id", "thesis_id", "decision_id"]``. A missing required link is a
    hard policy violation, NOT missing_data: the intent definitively lacks it.
    """

    rule_id = str(rule.get("rule_id") or rule.get("limit_class"))
    required = rule.get("threshold")
    if isinstance(required, dict):
        required = required.get("links")
    if not isinstance(required, list) or not required:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_MALFORMED_RULE, severity="missing_data",
            threshold=rule.get("threshold"), missing_data=True,
            caveat=f"rule {rule_id} has no required-link list",
        )
    required_fields = [str(f) for f in required]
    absent = [f for f in required_fields if not intent.get(f)]
    if absent:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_REQUIRED_LINK_MISSING, severity=severity,
            observed_value={"missing_links": absent}, threshold={"required": required_fields},
            waiver_required=_waiver_required(rule, severity),
        )
    return _rule_result(
        rule_id=rule_id, reason_code=RC_WITHIN_LIMIT, severity="info",
        observed_value={"present_links": required_fields}, threshold={"required": required_fields},
    )


def _eval_approval_threshold(
    rule: dict[str, Any], *, notional: Any, approval_state: Any,
) -> dict[str, Any]:
    """Approval threshold: notional at/above ``threshold`` requires approval.

    Severity is fixed at ``warning`` with ``waiver_required=True`` (requires
    explicit operator approval) when the intent is not already approved/waived
    elsewhere. Missing notional => ``missing_data``.
    """

    rule_id = str(rule.get("rule_id") or rule.get("limit_class"))
    threshold = _coerce_number(rule.get("threshold"))
    if threshold is None:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_MALFORMED_RULE, severity="missing_data",
            threshold=rule.get("threshold"), missing_data=True,
            caveat=f"rule {rule_id} has no numeric threshold",
        )
    value = _coerce_number(notional)
    if value is None:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_MISSING_INPUT, severity="missing_data",
            threshold={"approval_at_or_above": threshold}, missing_data=True,
            caveat=f"notional unavailable for rule {rule_id}; cannot evaluate (missing_data is not a pass)",
        )
    already_cleared = str(approval_state or "") in {"approved_elsewhere", "waived_elsewhere"}
    if value >= threshold and not already_cleared:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_APPROVAL_REQUIRED, severity="warning",
            observed_value={"notional": value, "approval_state": approval_state},
            threshold={"approval_at_or_above": threshold}, waiver_required=True,
        )
    return _rule_result(
        rule_id=rule_id, reason_code=RC_WITHIN_LIMIT, severity="info",
        observed_value={"notional": value, "approval_state": approval_state},
        threshold={"approval_at_or_above": threshold},
    )


def _eval_mode_flag(
    rule: dict[str, Any], *, observed_flag: Any, mode: str, severity: str,
) -> dict[str, Any]:
    """paper-only / close-only mode gates.

    ``paper_only``: violation when the intent environment is not a paper env.
    ``close_only``: violation when the intent is not a closing/reducing action.
    Missing the relevant intent signal => ``missing_data``.
    """

    rule_id = str(rule.get("rule_id") or rule.get("limit_class"))
    if observed_flag is None:
        return _rule_result(
            rule_id=rule_id, reason_code=RC_MISSING_INPUT, severity="missing_data",
            threshold={mode: True}, missing_data=True,
            caveat=f"intent {mode} signal unavailable; cannot evaluate (missing_data is not a pass)",
        )
    compliant = bool(observed_flag)
    if not compliant:
        reason = RC_PAPER_ONLY_VIOLATION if mode == "paper_only" else RC_CLOSE_ONLY_VIOLATION
        return _rule_result(
            rule_id=rule_id, reason_code=reason, severity=severity,
            observed_value={mode: compliant}, threshold={mode: True},
            waiver_required=_waiver_required(rule, severity),
        )
    return _rule_result(
        rule_id=rule_id, reason_code=RC_WITHIN_LIMIT, severity="info",
        observed_value={mode: compliant}, threshold={mode: True},
    )


def _evaluate_one_rule(
    rule: dict[str, Any], intent: dict[str, Any], snapshots: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch a single policy rule to its deterministic comparator."""

    if not isinstance(rule, dict):
        return _rule_result(
            rule_id="malformed", reason_code=RC_MALFORMED_RULE, severity="missing_data",
            missing_data=True, caveat="rule entry is not an object",
        )
    limit_class = str(rule.get("limit_class") or "")
    rule_id = str(rule.get("rule_id") or limit_class or "malformed")
    policy_severity = str(rule.get("severity") or "hard_block")
    if policy_severity not in {"warning", "hard_block"}:
        policy_severity = "hard_block"

    shape = intent.get("proposed_shape") or {}
    exposure = snapshots.get("exposure") or {}
    market = snapshots.get("market") or {}

    if limit_class == "notional":
        return _eval_numeric_max(
            rule, observed=shape.get("notional", shape.get("quantity")),
            severity=policy_severity, source_label="notional",
            contributing=list(snapshots.get("exposure_input_ids") or []),
        )
    if limit_class == "market_exposure":
        return _eval_numeric_max(
            rule, observed=exposure.get("market_exposure"), severity=policy_severity,
            source_label="market_exposure", contributing=list(snapshots.get("exposure_input_ids") or []),
        )
    if limit_class == "category_exposure":
        return _eval_numeric_max(
            rule, observed=exposure.get("category_exposure"), severity=policy_severity,
            source_label="category_exposure", contributing=list(snapshots.get("exposure_input_ids") or []),
        )
    if limit_class == "total_exposure":
        return _eval_numeric_max(
            rule, observed=exposure.get("total_exposure"), severity=policy_severity,
            source_label="total_exposure", contributing=list(snapshots.get("exposure_input_ids") or []),
        )
    if limit_class == "daily_loss":
        return _eval_numeric_max(
            rule, observed=exposure.get("daily_loss"), severity=policy_severity,
            source_label="daily_loss", contributing=list(snapshots.get("exposure_input_ids") or []),
        )
    if limit_class == "weekly_loss":
        return _eval_numeric_max(
            rule, observed=exposure.get("weekly_loss"), severity=policy_severity,
            source_label="weekly_loss", contributing=list(snapshots.get("exposure_input_ids") or []),
        )
    if limit_class == "spread":
        return _eval_numeric_max(
            rule, observed=market.get("spread"), severity=policy_severity,
            source_label="spread", contributing=list(snapshots.get("market_input_ids") or []),
        )
    if limit_class == "slippage":
        return _eval_numeric_max(
            rule, observed=shape.get("max_slippage", market.get("slippage")),
            severity=policy_severity, source_label="slippage",
            contributing=list(snapshots.get("market_input_ids") or []),
        )
    if limit_class == "time_to_resolution":
        return _eval_min(
            rule, observed=market.get("time_to_resolution"),
            severity=policy_severity, source_label="time_to_resolution",
        )
    if limit_class == "blocked_categories":
        return _eval_category(
            rule, category=intent.get("category", shape.get("category")),
            mode="blocked", severity=policy_severity,
        )
    if limit_class == "allowed_categories":
        return _eval_category(
            rule, category=intent.get("category", shape.get("category")),
            mode="allowed", severity=policy_severity,
        )
    if limit_class == "required_links":
        return _eval_required_links(rule, intent=intent, severity=policy_severity)
    if limit_class == "approval_threshold":
        return _eval_approval_threshold(
            rule, notional=shape.get("notional", shape.get("quantity")),
            approval_state=intent.get("approval_state"),
        )
    if limit_class == "paper_only":
        return _eval_mode_flag(
            rule, observed_flag=intent.get("is_paper"), mode="paper_only", severity=policy_severity,
        )
    if limit_class == "close_only":
        return _eval_mode_flag(
            rule, observed_flag=intent.get("is_closing"), mode="close_only", severity=policy_severity,
        )
    # Unknown limit class: refuse to guess. Surface as missing_data so the
    # aggregate can never silently pass a rule the evaluator does not understand.
    return _rule_result(
        rule_id=rule_id, reason_code=RC_UNKNOWN_LIMIT_CLASS, severity="missing_data",
        observed_value={"limit_class": limit_class}, missing_data=True,
        caveat=f"unknown limit_class {limit_class!r}; evaluator cannot apply rule {rule_id}",
    )


def evaluate_risk_policy(
    *,
    intent: dict[str, Any],
    policy_rules: list[Any],
    snapshots: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure deterministic evaluator: intent + policy rules + snapshots -> verdict.

    Returns ``{"status", "outcome", "rule_results", "missing_data", "stale_data"}``
    where ``status`` is one of ``pass|warn|fail|missing_data`` and ``outcome`` is
    drawn from :data:`OUTCOMES`. No DB, no events, no side effects, no advice.

    Determinism: rule results are returned in policy order; the aggregate is a
    pure fold over per-rule severities. ``missing_data`` is never a soft pass —
    any rule the evaluator cannot apply (missing input, malformed rule, unknown
    limit class) raises the aggregate to at least ``missing_data``.
    """

    snaps = snapshots or {}
    results: list[dict[str, Any]] = []
    worst_rank = _SEVERITY_RANK["info"]
    any_missing = False
    any_stale = bool(snaps.get("stale")) or bool((snaps.get("market") or {}).get("stale"))
    for rule in policy_rules:
        result = _evaluate_one_rule(rule if isinstance(rule, dict) else {}, intent, snaps)
        if any_stale and not result.get("missing_data"):
            result["stale_data"] = True
            if not result.get("caveat"):
                result["caveat"] = "evaluated against caller-flagged stale input snapshot"
        results.append(result)
        if result.get("missing_data"):
            any_missing = True
        worst_rank = max(worst_rank, _SEVERITY_RANK.get(result["severity"], 0))
        if result.get("stale_data"):
            worst_rank = max(worst_rank, _SEVERITY_RANK["warning"])

    worst_severity = next(
        (name for name, rank in sorted(_SEVERITY_RANK.items(), key=lambda kv: -kv[1]) if rank == worst_rank),
        "info",
    )
    status = _AGGREGATE_STATUS_FOR_SEVERITY[worst_severity]
    # missing_data must never soft-pass: if any rule is missing_data the aggregate
    # cannot be 'pass' or a plain 'warn'; it is at least missing_data (§3.1).
    if any_missing and status in {"pass", "warn"}:
        status = "missing_data"
    outcome = _AGGREGATE_OUTCOME_FOR_STATUS[status]
    if status == "warn" and any_stale:
        outcome = "stale_data"
    return {
        "status": status,
        "outcome": outcome,
        "rule_results": results,
        "missing_data": any_missing,
        "stale_data": any_stale,
    }


def _policy_response(conn: Any, policy_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, policy_key, version, policy_hash, effective_from, effective_to, created_at FROM risk_policy_versions WHERE id = ?",
        (policy_id,),
    ).fetchone()
    return {
        "id": row[0], "policy_key": row[1], "version": row[2], "policy_hash": row[3],
        "effective_from": row[4], "effective_to": row[5], "created_at": row[6],
    }


def _risk_policy_version_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    policy_key = require(args, "policy_key")
    version = require(args, "version")
    limits = _dict_arg(args, "limits_json")
    rules = _list_arg(args, "rules_json")
    source = require(args, "source")
    reject_credential_metadata(limits, field="limits_json")
    reject_credential_metadata(rules, field="rules_json")
    reject_if_contains_secrets(source, field="source")
    effective_from = normalize_timestamp(args, "effective_from", required=True)
    effective_to = normalize_timestamp(args, "effective_to")
    provenance_json = store_metadata_json(args, "provenance_json")
    idempotency_key = args.get("idempotency_key")
    computed_policy_hash = _hash_payload("risk_policy", {
        "policy_key": policy_key, "version": version, "limits": limits, "rules": rules,
        "source": source, "effective_from": effective_from, "effective_to": effective_to,
        "provenance": json.loads(provenance_json),
    })
    policy_hash = args.get("policy_hash") or computed_policy_hash
    if policy_hash != computed_policy_hash:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "policy_hash does not match canonical policy payload", details={"field": "policy_hash"})

    def payload(pid: str) -> dict[str, Any]:
        return {
            "id": pid, "policy_key": policy_key, "version": version, "policy_hash": policy_hash,
            "limits_json": limits, "rules_json": rules, "source": source,
            "provenance_json": json.loads(provenance_json), "effective_from": effective_from,
            "effective_to": effective_to,
        }

    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(uow, event_type=_POLICY_EVENT, actor_id=ctx.actor_id, idempotency_key=idempotency_key)
            if replay is not None:
                emit_event(uow, event_type=_POLICY_EVENT, subject_kind="risk_policy_version", subject_id=replay["id"], payload=payload(replay["id"]), actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
                return _policy_response(uow.conn, replay["id"])
            # risk_policy_versions.policy_hash is UNIQUE (m016): identical
            # policy content submitted under a NEW idempotency key would
            # otherwise fall through to the INSERT below and surface a raw
            # sqlite3.IntegrityError ("UNIQUE constraint failed:
            # risk_policy_versions.policy_hash") instead of a typed, actionable
            # envelope (trade-trace-0c7cn). Detect the duplicate up front and
            # name the existing version so the caller can replay with the
            # original idempotency_key or bump the version. Same-key replay is
            # handled above and unaffected.
            duplicate = uow.conn.execute(
                "SELECT id FROM risk_policy_versions WHERE policy_hash = ?",
                (policy_hash,),
            ).fetchone()
            if duplicate is not None:
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    f"identical policy content already recorded as {duplicate[0]}; "
                    "replay with the original idempotency key or bump the version",
                    details={
                        "field": "policy_hash",
                        "existing_policy_version_id": duplicate[0],
                        "policy_hash": policy_hash,
                        "reason": "duplicate_policy_content",
                    },
                )
            policy_id = args.get("id") or new_id("rpv")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO risk_policy_versions(id, policy_key, version, policy_hash, limits_json, rules_json, source, provenance_json, effective_from, effective_to, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (policy_id, policy_key, version, policy_hash, _canonical_json(limits), _canonical_json(rules), source, provenance_json, effective_from, effective_to, created_at, ctx.actor_id),
            )
            emit_event(uow, event_type=_POLICY_EVENT, subject_kind="risk_policy_version", subject_id=policy_id, payload=payload(policy_id), actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
            return _policy_response(uow.conn, policy_id)


def _receipt_response(conn: Any, receipt_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, receipt_hash, policy_version_id, status, outcome, intended_action, proposed_intent_hash, decision_id, market_id, instrument_id, strategy_id, snapshot_id, as_of, created_at FROM risk_check_receipts WHERE id = ?",
        (receipt_id,),
    ).fetchone()
    rules = conn.execute(
        "SELECT rule_id, reason_code, severity, observed_value_json, threshold_json, contributing_record_ids_json, waiver_required, caveat, missing_data, stale_data FROM risk_check_rule_results WHERE receipt_id = ? ORDER BY rule_id",
        (receipt_id,),
    ).fetchall()
    return {
        "id": row[0], "receipt_hash": row[1], "policy_version_id": row[2], "status": row[3],
        "outcome": row[4], "intended_action": row[5], "proposed_intent_hash": row[6],
        "decision_id": row[7], "market_id": row[8], "instrument_id": row[9],
        "strategy_id": row[10], "snapshot_id": row[11], "as_of": row[12], "created_at": row[13],
        "rule_results": [{
            "rule_id": r[0], "reason_code": r[1], "severity": r[2],
            "observed_value": json.loads(r[3]) if r[3] else None,
            "threshold": json.loads(r[4]) if r[4] else None,
            "contributing_record_ids": json.loads(r[5]), "waiver_required": bool(r[6]),
            "caveat": r[7], "missing_data": bool(r[8]), "stale_data": bool(r[9]),
        } for r in rules],
    }


def _risk_check_record(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    policy_version_id = require(args, "policy_version_id")
    status = require(args, "status")
    outcome = require(args, "outcome")
    if status not in STATUSES or outcome not in OUTCOMES:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown risk receipt status/outcome", details={"status": status, "outcome": outcome})
    if status == "pass" and outcome != "pass":
        raise ToolError(ErrorCode.VALIDATION_ERROR, "pass status requires pass outcome", details={"field": "outcome"})
    rule_results = _list_arg(args, "rule_results")
    reject_credential_metadata(rule_results, field="rule_results")
    if status == "missing_data" and not any(r.get("missing_data") for r in rule_results if isinstance(r, dict)):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "missing_data status requires a missing-data rule caveat", details={"field": "rule_results"})
    as_of = normalize_timestamp(args, "as_of", required=True)
    exposure_ids = _list_arg(args, "exposure_input_ids_json")
    evidence_ids = _list_arg(args, "evidence_input_ids_json")
    provenance = _dict_arg(args, "input_provenance_json")
    reject_credential_metadata(exposure_ids, field="exposure_input_ids_json")
    reject_credential_metadata(evidence_ids, field="evidence_input_ids_json")
    reject_credential_metadata(provenance, field="input_provenance_json")
    for field in (
        "intended_action", "proposed_intent_hash", "decision_id", "market_id",
        "instrument_id", "strategy_id", "snapshot_id", "waived_by", "waiver_reason",
    ):
        reject_if_contains_secrets(args.get(field), field=field)
    if not any(args.get(field) for field in RECEIPT_ANCHOR_FIELDS) and not exposure_ids and not evidence_ids:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "risk receipt must include at least one audit anchor", details={"field": "receipt_anchor"})
    validated_rule_results: list[dict[str, Any]] = []
    for rr in rule_results:
        if not isinstance(rr, dict):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "rule_results entries must be objects", details={"field": "rule_results"})
        for field in ("rule_id", "reason_code", "severity"):
            if not rr.get(field):
                raise ToolError(ErrorCode.VALIDATION_ERROR, f"rule result requires {field}", details={"field": field})
        severity = rr["severity"]
        if severity not in SEVERITIES:
            raise ToolError(ErrorCode.VALIDATION_ERROR, "unknown rule severity", details={"field": "severity"})
        if "waiver_required" not in rr or not isinstance(rr.get("waiver_required"), bool):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "rule result requires explicit boolean waiver_required", details={"field": "waiver_required"})
        if "contributing_record_ids" not in rr or not isinstance(rr.get("contributing_record_ids"), list):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "rule result requires contributing_record_ids array", details={"field": "contributing_record_ids"})
        missing_or_stale = bool(rr.get("missing_data")) or bool(rr.get("stale_data"))
        if missing_or_stale and not rr.get("caveat"):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "missing_data or stale_data rule requires caveat", details={"field": "caveat"})
        if not missing_or_stale and ("observed_value" not in rr or "threshold" not in rr):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "non-missing rule requires observed_value and threshold", details={"field": "observed_value"})
        validated_rule_results.append(rr)
    has_missing_data = any(bool(rr.get("missing_data")) for rr in validated_rule_results)
    has_stale_data = any(bool(rr.get("stale_data")) for rr in validated_rule_results)
    if has_missing_data and status != "missing_data":
        raise ToolError(ErrorCode.VALIDATION_ERROR, "missing_data rule requires aggregate missing_data status", details={"field": "status"})
    if has_stale_data and status == "pass":
        raise ToolError(ErrorCode.VALIDATION_ERROR, "stale_data rule cannot have aggregate pass status", details={"field": "status"})
    receipt_material = {
        "policy_version_id": policy_version_id, "status": status, "outcome": outcome,
        "intended_action": args.get("intended_action"), "proposed_intent_hash": args.get("proposed_intent_hash"),
        "decision_id": args.get("decision_id"), "market_id": args.get("market_id"),
        "instrument_id": args.get("instrument_id"), "strategy_id": args.get("strategy_id"),
        "snapshot_id": args.get("snapshot_id"), "exposure_input_ids_json": exposure_ids,
        "evidence_input_ids_json": evidence_ids, "input_provenance_json": provenance, "as_of": as_of,
        "waived_by": args.get("waived_by"), "waiver_reason": args.get("waiver_reason"),
        "rule_results": validated_rule_results,
    }
    computed_receipt_hash = _hash_payload("risk_receipt", receipt_material)
    receipt_hash = args.get("receipt_hash") or computed_receipt_hash
    if receipt_hash != computed_receipt_hash:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "receipt_hash does not match canonical receipt payload", details={"field": "receipt_hash"})
    idempotency_key = args.get("idempotency_key")

    with db_for_args(args) as db:
        _guard_recorded_verdict_matches_evaluator(
            db.connection, args,
            policy_version_id=policy_version_id, status=status, outcome=outcome,
            rule_results=validated_rule_results,
        )
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(uow, event_type=_RECEIPT_EVENT, actor_id=ctx.actor_id, idempotency_key=idempotency_key)
            if replay is not None:
                emit_event(uow, event_type=_RECEIPT_EVENT, subject_kind="risk_check_receipt", subject_id=replay["id"], payload={"id": replay["id"], **receipt_material, "receipt_hash": receipt_hash}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
                return _receipt_response(uow.conn, replay["id"])
            receipt_id = args.get("id") or new_id("rcr")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO risk_check_receipts(id, receipt_hash, policy_version_id, status, outcome, intended_action, proposed_intent_hash, decision_id, market_id, instrument_id, strategy_id, snapshot_id, exposure_input_ids_json, evidence_input_ids_json, input_provenance_json, as_of, waived_by, waiver_reason, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (receipt_id, receipt_hash, policy_version_id, status, outcome, args.get("intended_action"), args.get("proposed_intent_hash"), args.get("decision_id"), args.get("market_id"), args.get("instrument_id"), args.get("strategy_id"), args.get("snapshot_id"), _canonical_json(exposure_ids), _canonical_json(evidence_ids), _canonical_json(provenance), as_of, args.get("waived_by"), args.get("waiver_reason"), created_at, ctx.actor_id),
            )
            for rr in validated_rule_results:
                severity = rr["severity"]
                uow.execute(
                    "INSERT INTO risk_check_rule_results(id, receipt_id, rule_id, reason_code, severity, observed_value_json, threshold_json, contributing_record_ids_json, waiver_required, caveat, missing_data, stale_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id("rrr"), receipt_id, rr["rule_id"], rr["reason_code"], severity, _canonical_json(rr.get("observed_value")) if "observed_value" in rr else None, _canonical_json(rr.get("threshold")) if "threshold" in rr else None, _canonical_json(rr["contributing_record_ids"]), 1 if rr["waiver_required"] else 0, rr.get("caveat"), 1 if rr.get("missing_data") else 0, 1 if rr.get("stale_data") else 0),
                )
            emit_event(uow, event_type=_RECEIPT_EVENT, subject_kind="risk_check_receipt", subject_id=receipt_id, payload={"id": receipt_id, **receipt_material, "receipt_hash": receipt_hash}, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
            return _receipt_response(uow.conn, receipt_id)


def _load_policy_rules(conn: Any, policy_version_id: str) -> list[Any]:
    row = conn.execute(
        "SELECT rules_json FROM risk_policy_versions WHERE id = ?",
        (policy_version_id,),
    ).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "risk policy version not found", details={"policy_version_id": policy_version_id})
    try:
        rules = json.loads(row[0]) if row[0] else []
    except json.JSONDecodeError as exc:  # pragma: no cover - stored rows are canonical
        raise ToolError(ErrorCode.STORAGE_ERROR, "stored policy rules_json is not valid JSON", details={"policy_version_id": policy_version_id}) from exc
    if not isinstance(rules, list):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "policy rules_json must be a JSON array", details={"policy_version_id": policy_version_id})
    return rules


def _load_intent(conn: Any, intent_id: str) -> dict[str, Any]:
    # Every column selected here must cover a field the deterministic
    # evaluator can read off `intent` (see _evaluate_one_rule / _eval_
    # required_links, which does a generic `intent.get(<policy-configured
    # field name>)` for required_links, plus the named market_id/
    # instrument_id/forecast_id/thesis_id/decision_id/strategy_id/
    # snapshot_id/approval_state reads). Omitting a column here makes a
    # persisted-intent re-evaluation (proposed_intent_id path) silently
    # disagree with the same intent evaluated inline, e.g. spuriously
    # failing a required_links check (trade-trace-r0oee).
    row = conn.execute(
        "SELECT id, proposed_shape_json, approval_state, market_id, instrument_id, snapshot_id, forecast_id, thesis_id, decision_id, strategy_id FROM pretrade_intents WHERE id = ?",
        (intent_id,),
    ).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "pre-trade intent not found", details={"proposed_intent_id": intent_id})
    return {
        "id": row[0],
        "proposed_shape": json.loads(row[1]) if row[1] else {},
        "approval_state": row[2],
        "market_id": row[3], "instrument_id": row[4], "snapshot_id": row[5],
        "forecast_id": row[6], "thesis_id": row[7], "decision_id": row[8], "strategy_id": row[9],
    }


def _verdict_signature(rule_results: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Order-independent identity of a verdict's per-rule outcomes.

    Two verdicts are consistent when they agree on the aggregate status/outcome
    AND on the multiset of ``(rule_id, reason_code, severity)`` per-rule
    decisions. We deliberately compare these load-bearing fields rather than the
    full dict so a caller may carry extra provenance (e.g. ``contributing_record_ids``
    the evaluator left empty) without tripping the guard.
    """

    return sorted(
        (
            str(rr.get("rule_id")),
            str(rr.get("reason_code")),
            str(rr.get("severity")),
        )
        for rr in rule_results
        if isinstance(rr, dict)
    )


def _guard_recorded_verdict_matches_evaluator(
    conn: Any,
    args: dict[str, Any],
    *,
    policy_version_id: str,
    status: str,
    outcome: str,
    rule_results: list[dict[str, Any]],
) -> None:
    """Consistency guard for the public ``risk.evaluate`` -> ``risk.check_record`` flow.

    ``risk.check_record`` still accepts a caller-asserted verdict (the receipt is
    recorded by an external/profile risk layer that may not run our evaluator).
    But when the caller ALSO supplies the deterministic evaluator's inputs
    (``proposed_intent`` and/or ``proposed_intent_id``, optionally ``snapshots``),
    we re-run :func:`evaluate_risk_policy` against the same immutable policy
    version and refuse the write if the recorded verdict disagrees. This makes
    the supported public flow — ``risk.evaluate`` produces the verdict, the
    caller passes it verbatim into ``risk.check_record`` — verifiable instead of
    trust-me: a hand-edited status/outcome/rule_results can no longer be recorded
    alongside the inputs that contradict it (bead trade-trace-ur8w).

    No-op when no evaluator inputs are present (the legacy caller-asserted path).
    """

    inline_intent = args.get("proposed_intent")
    intent_id = args.get("proposed_intent_id")
    if inline_intent is None and not intent_id:
        return
    if inline_intent is not None and not isinstance(inline_intent, dict):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "proposed_intent must be an object", details={"field": "proposed_intent"})
    snapshots = _dict_arg(args, "snapshots")
    reject_credential_metadata(snapshots, field="snapshots")
    policy_rules = _load_policy_rules(conn, policy_version_id)
    if intent_id:
        intent = _load_intent(conn, str(intent_id))
        if isinstance(inline_intent, dict):
            merged = dict(intent)
            merged.update({k: v for k, v in inline_intent.items() if k not in intent or intent.get(k) is None})
            intent = merged
    else:
        intent = dict(inline_intent or {})
    verdict = evaluate_risk_policy(intent=intent, policy_rules=policy_rules, snapshots=snapshots)
    if (verdict["status"], verdict["outcome"]) != (status, outcome) or _verdict_signature(
        verdict["rule_results"]
    ) != _verdict_signature(rule_results):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "recorded verdict does not match the deterministic evaluator for the supplied intent + policy version",
            details={
                "field": "status",
                "recorded": {"status": status, "outcome": outcome},
                "evaluated": {"status": verdict["status"], "outcome": verdict["outcome"]},
            },
        )


def _risk_evaluate(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Deterministically evaluate a proposed intent against a risk policy version.

    Read-only (trade-trace-g629): loads the immutable policy rules + the proposed
    intent (by ``proposed_intent_id`` or inline ``proposed_intent``), runs the
    pure :func:`evaluate_risk_policy` over caller-supplied input ``snapshots``, and
    RETURNS per-rule results + an aggregate ``status``/``outcome`` the caller (or a
    later ``risk.check_record``) can trust instead of hand-crafting a verdict. No
    rows are written and no execution is performed.
    """

    del ctx
    policy_version_id = require(args, "policy_version_id")
    snapshots = _dict_arg(args, "snapshots")
    reject_credential_metadata(snapshots, field="snapshots")
    inline_intent = args.get("proposed_intent")
    intent_id = args.get("proposed_intent_id")
    if inline_intent is not None and not isinstance(inline_intent, dict):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "proposed_intent must be an object", details={"field": "proposed_intent"})
    if inline_intent is not None:
        reject_credential_metadata(inline_intent, field="proposed_intent")
    if not intent_id and inline_intent is None:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "provide proposed_intent_id or proposed_intent", details={"field": "proposed_intent_id"})

    with db_for_args(args) as db:
        conn = db.connection
        policy_rules = _load_policy_rules(conn, policy_version_id)
        if intent_id:
            intent = _load_intent(conn, str(intent_id))
            if isinstance(inline_intent, dict):
                # Inline fields (e.g. exposure projections the caller computed)
                # augment but never silently override the stored intent.
                merged = dict(intent)
                merged.update({k: v for k, v in inline_intent.items() if k not in intent or intent.get(k) is None})
                intent = merged
        else:
            intent = dict(inline_intent or {})
        policy = _policy_response(conn, policy_version_id)

    verdict = evaluate_risk_policy(intent=intent, policy_rules=policy_rules, snapshots=snapshots)
    return {
        "policy_version_id": policy_version_id,
        "policy_key": policy["policy_key"],
        "policy_version": policy["version"],
        "policy_hash": policy["policy_hash"],
        "proposed_intent_id": intent.get("id"),
        "evaluated_rule_count": len(verdict["rule_results"]),
        "status": verdict["status"],
        "outcome": verdict["outcome"],
        "missing_data": verdict["missing_data"],
        "stale_data": verdict["stale_data"],
        "rule_results": verdict["rule_results"],
        "deterministic": True,
        "non_executing": True,
        "record_kind": "deterministic_risk_evaluation",
    }


def register_risk_tools(registry: ToolRegistry) -> None:
    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    registry.register(
        "risk.policy_version_add", _risk_policy_version_add, is_write=True,
        description="Record an immutable audit-only risk policy version; no order blocking or execution is performed.",
        json_schema={"type": "object", "properties": {"policy_key": {"type": "string"}, "version": {"type": "string"}, "limits_json": {"type": "object"}, "rules_json": {"type": "array"}, "source": {"type": "string"}, "provenance_json": {"type": "object"}, "effective_from": {"type": "string"}, "effective_to": {"type": "string"}, "policy_hash": {"type": "string"}, "idempotency_key": {"type": "string"}, "home": {"type": "string"}}, "required": ["policy_key", "version", "limits_json", "rules_json", "source", "effective_from"]},
        **_examples_for("risk.policy_version_add"),
    )
    registry.register(
        "risk.check_record", _risk_check_record, is_write=True,
        description="Record an audit-only pre-trade risk-check receipt from an external/profile risk layer; no order blocking or execution is performed.",
        json_schema={"type": "object", "properties": {"policy_version_id": {"type": "string"}, "status": {"type": "string", "enum": sorted(STATUSES)}, "outcome": {"type": "string", "enum": sorted(OUTCOMES)}, "intended_action": {"type": "string"}, "proposed_intent_hash": {"type": "string"}, "decision_id": {"type": "string"}, "market_id": {"type": "string"}, "instrument_id": {"type": "string"}, "strategy_id": {"type": "string"}, "snapshot_id": {"type": "string"}, "exposure_input_ids_json": {"type": "array"}, "evidence_input_ids_json": {"type": "array"}, "input_provenance_json": {"type": "object"}, "as_of": {"type": "string"}, "rule_results": {"type": "array"}, "proposed_intent_id": {"type": "string", "description": "Optional: stored intent id. When supplied (with optional inline proposed_intent / snapshots) the recorded status/outcome/rule_results are re-checked against the deterministic evaluator and the write is refused on mismatch."}, "proposed_intent": {"type": "object", "description": "Optional inline non-executing proposed intent shape. Triggers the same evaluator consistency guard as proposed_intent_id."}, "snapshots": {"type": "object", "description": "Optional caller-supplied input snapshots for the consistency guard; read-only, never live-fetched."}, "waived_by": {"type": "string"}, "waiver_reason": {"type": "string"}, "receipt_hash": {"type": "string"}, "idempotency_key": {"type": "string"}, "home": {"type": "string"}}, "required": ["policy_version_id", "status", "outcome", "as_of", "rule_results"]},
        **_examples_for("risk.check_record"),
    )
    registry.register(
        "risk.evaluate", _risk_evaluate,
        description="Deterministically evaluate a proposed non-executing pre-trade intent against an immutable risk policy version and return per-rule results plus an aggregate pass/warn/fail/missing_data verdict; no rows are written, no order is blocked, signed, placed, or routed.",
        json_schema={"type": "object", "properties": {"policy_version_id": {"type": "string"}, "proposed_intent_id": {"type": "string"}, "proposed_intent": {"type": "object", "description": "Inline non-executing proposed intent shape used when no stored intent id is supplied."}, "snapshots": {"type": "object", "description": "Caller-supplied input snapshots (exposure projection, market/quote/book, imported account state) the deterministic evaluator reads; read-only, never live-fetched."}, "home": {"type": "string"}}, "required": ["policy_version_id"]},
    )


__all__ = ["register_risk_tools", "evaluate_risk_policy", "LIMIT_CLASSES"]
