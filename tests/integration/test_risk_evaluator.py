"""Deterministic risk-check evaluator (trade-trace-g629).

Covers the §3.1 limit classes, stable reason codes, the missing_data-is-not-a-
soft-pass invariant, determinism, and the read-only ``risk.evaluate`` tool wired
through the registry against stored policy versions + pre-trade intents.
"""

from __future__ import annotations

import sqlite3

from trade_trace.core import dispatch
from trade_trace.storage.paths import db_path
from trade_trace.tools.risk import (
    RC_APPROVAL_REQUIRED,
    RC_CATEGORY_BLOCKED,
    RC_CATEGORY_NOT_ALLOWED,
    RC_CLOSE_ONLY_VIOLATION,
    RC_LIMIT_EXCEEDED,
    RC_MISSING_INPUT,
    RC_PAPER_ONLY_VIOLATION,
    RC_REQUIRED_LINK_MISSING,
    RC_UNKNOWN_LIMIT_CLASS,
    RC_WITHIN_LIMIT,
    evaluate_risk_policy,
)


def _call(tool: str, args: dict, *, actor_id: str = "agent:risk"):
    return dispatch(tool, args, actor_id=actor_id)


# --------------------------------------------------------------------------- #
# Pure evaluator unit coverage
# --------------------------------------------------------------------------- #


def test_notional_within_limit_passes():
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": 100}},
        policy_rules=[{"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000}],
        snapshots={},
    )
    assert v["status"] == "pass"
    assert v["outcome"] == "pass"
    assert v["rule_results"][0]["reason_code"] == RC_WITHIN_LIMIT
    assert v["missing_data"] is False


def test_notional_exceeded_hard_blocks_and_requires_waiver():
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": 5000}},
        policy_rules=[{"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000}],
        snapshots={},
    )
    assert v["status"] == "fail"
    assert v["outcome"] == "hard_block"
    rr = v["rule_results"][0]
    assert rr["reason_code"] == RC_LIMIT_EXCEEDED
    assert rr["severity"] == "hard_block"
    assert rr["waiver_required"] is True
    assert rr["threshold"] == {"max": 1000.0}


def test_warning_rule_yields_warn_not_fail():
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": 5000}},
        policy_rules=[{"rule_id": "n", "limit_class": "notional", "severity": "warning", "threshold": 1000}],
        snapshots={},
    )
    assert v["status"] == "warn"
    assert v["outcome"] == "warning"


def test_missing_input_is_not_a_soft_pass():
    # spread rule but no market snapshot -> cannot evaluate -> missing_data.
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": 1}},
        policy_rules=[{"rule_id": "spread", "limit_class": "spread", "severity": "warning", "threshold": 0.05}],
        snapshots={"market": {}},
    )
    assert v["missing_data"] is True
    assert v["status"] == "missing_data"
    assert v["rule_results"][0]["reason_code"] == RC_MISSING_INPUT


def test_missing_data_cannot_be_overridden_by_a_passing_rule():
    # One passing rule + one missing-data rule must NOT aggregate to pass.
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": 1}},
        policy_rules=[
            {"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000},
            {"rule_id": "ttr", "limit_class": "time_to_resolution", "severity": "warning", "threshold": 24},
        ],
        snapshots={"market": {}},
    )
    statuses = {r["reason_code"] for r in v["rule_results"]}
    assert RC_WITHIN_LIMIT in statuses
    assert RC_MISSING_INPUT in statuses
    assert v["status"] == "missing_data"


def test_hard_block_outranks_missing_data():
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": 9999}},
        policy_rules=[
            {"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000},
            {"rule_id": "spread", "limit_class": "spread", "severity": "warning", "threshold": 0.05},
        ],
        snapshots={"market": {}},
    )
    # notional fails hard; spread is missing_data -> hard_block must win.
    assert v["status"] == "fail"
    assert v["missing_data"] is True


def test_exposure_classes_read_exposure_snapshot():
    rules = [
        {"rule_id": "tot", "limit_class": "total_exposure", "severity": "hard_block", "threshold": 500},
        {"rule_id": "mkt", "limit_class": "market_exposure", "severity": "warning", "threshold": 100},
        {"rule_id": "cat", "limit_class": "category_exposure", "severity": "warning", "threshold": 200},
    ]
    v = evaluate_risk_policy(
        intent={"proposed_shape": {}},
        policy_rules=rules,
        snapshots={"exposure": {"total_exposure": 600, "market_exposure": 50, "category_exposure": 50},
                   "exposure_input_ids": ["pos_1"]},
    )
    by_id = {r["rule_id"]: r for r in v["rule_results"]}
    assert by_id["tot"]["reason_code"] == RC_LIMIT_EXCEEDED
    assert by_id["tot"]["contributing_record_ids"] == ["pos_1"]
    assert by_id["mkt"]["reason_code"] == RC_WITHIN_LIMIT
    assert v["status"] == "fail"


def test_loss_classes():
    v = evaluate_risk_policy(
        intent={"proposed_shape": {}},
        policy_rules=[
            {"rule_id": "dl", "limit_class": "daily_loss", "severity": "hard_block", "threshold": 100},
            {"rule_id": "wl", "limit_class": "weekly_loss", "severity": "hard_block", "threshold": 500},
        ],
        snapshots={"exposure": {"daily_loss": 150, "weekly_loss": 100}},
    )
    by_id = {r["rule_id"]: r for r in v["rule_results"]}
    assert by_id["dl"]["reason_code"] == RC_LIMIT_EXCEEDED
    assert by_id["wl"]["reason_code"] == RC_WITHIN_LIMIT


def test_slippage_from_intent_shape():
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": 1, "max_slippage": 0.10}},
        policy_rules=[{"rule_id": "slip", "limit_class": "slippage", "severity": "warning", "threshold": 0.05}],
        snapshots={},
    )
    assert v["rule_results"][0]["reason_code"] == RC_LIMIT_EXCEEDED


def test_time_to_resolution_is_a_minimum():
    # 2h runway against a 24h minimum -> violation.
    v = evaluate_risk_policy(
        intent={"proposed_shape": {}},
        policy_rules=[{"rule_id": "ttr", "limit_class": "time_to_resolution", "severity": "warning", "threshold": 24}],
        snapshots={"market": {"time_to_resolution": 2}},
    )
    assert v["rule_results"][0]["reason_code"] == RC_LIMIT_EXCEEDED
    # ample runway passes.
    v2 = evaluate_risk_policy(
        intent={"proposed_shape": {}},
        policy_rules=[{"rule_id": "ttr", "limit_class": "time_to_resolution", "severity": "warning", "threshold": 24}],
        snapshots={"market": {"time_to_resolution": 48}},
    )
    assert v2["rule_results"][0]["reason_code"] == RC_WITHIN_LIMIT


def test_blocked_and_allowed_categories():
    blocked = evaluate_risk_policy(
        intent={"category": "crypto", "proposed_shape": {}},
        policy_rules=[{"rule_id": "blk", "limit_class": "blocked_categories", "severity": "hard_block",
                       "threshold": ["crypto", "politics"]}],
        snapshots={},
    )
    assert blocked["rule_results"][0]["reason_code"] == RC_CATEGORY_BLOCKED

    not_allowed = evaluate_risk_policy(
        intent={"category": "sports", "proposed_shape": {}},
        policy_rules=[{"rule_id": "alw", "limit_class": "allowed_categories", "severity": "hard_block",
                       "threshold": {"categories": ["crypto", "macro"]}}],
        snapshots={},
    )
    assert not_allowed["rule_results"][0]["reason_code"] == RC_CATEGORY_NOT_ALLOWED


def test_category_missing_is_missing_data():
    v = evaluate_risk_policy(
        intent={"proposed_shape": {}},
        policy_rules=[{"rule_id": "blk", "limit_class": "blocked_categories", "severity": "hard_block",
                       "threshold": ["crypto"]}],
        snapshots={},
    )
    assert v["rule_results"][0]["missing_data"] is True
    assert v["status"] == "missing_data"


def test_required_links_missing_is_a_violation_not_missing_data():
    v = evaluate_risk_policy(
        intent={"proposed_shape": {}, "forecast_id": "f_1", "thesis_id": None},
        policy_rules=[{"rule_id": "links", "limit_class": "required_links", "severity": "hard_block",
                       "threshold": ["forecast_id", "thesis_id", "decision_id"]}],
        snapshots={},
    )
    rr = v["rule_results"][0]
    assert rr["reason_code"] == RC_REQUIRED_LINK_MISSING
    assert rr["missing_data"] is False  # the intent definitively lacks the links
    assert set(rr["observed_value"]["missing_links"]) == {"thesis_id", "decision_id"}
    assert v["status"] == "fail"


def test_required_links_present_passes():
    v = evaluate_risk_policy(
        intent={"proposed_shape": {}, "forecast_id": "f_1", "thesis_id": "t_1"},
        policy_rules=[{"rule_id": "links", "limit_class": "required_links", "severity": "hard_block",
                       "threshold": ["forecast_id", "thesis_id"]}],
        snapshots={},
    )
    assert v["rule_results"][0]["reason_code"] == RC_WITHIN_LIMIT


def test_approval_threshold():
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": 5000}, "approval_state": "not_requested"},
        policy_rules=[{"rule_id": "appr", "limit_class": "approval_threshold", "threshold": 1000}],
        snapshots={},
    )
    rr = v["rule_results"][0]
    assert rr["reason_code"] == RC_APPROVAL_REQUIRED
    assert rr["waiver_required"] is True
    assert v["status"] == "warn"

    cleared = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": 5000}, "approval_state": "approved_elsewhere"},
        policy_rules=[{"rule_id": "appr", "limit_class": "approval_threshold", "threshold": 1000}],
        snapshots={},
    )
    assert cleared["rule_results"][0]["reason_code"] == RC_WITHIN_LIMIT


def test_paper_only_and_close_only():
    paper = evaluate_risk_policy(
        intent={"proposed_shape": {}, "is_paper": False},
        policy_rules=[{"rule_id": "po", "limit_class": "paper_only", "severity": "hard_block"}],
        snapshots={},
    )
    assert paper["rule_results"][0]["reason_code"] == RC_PAPER_ONLY_VIOLATION

    close = evaluate_risk_policy(
        intent={"proposed_shape": {}, "is_closing": False},
        policy_rules=[{"rule_id": "co", "limit_class": "close_only", "severity": "hard_block"}],
        snapshots={},
    )
    assert close["rule_results"][0]["reason_code"] == RC_CLOSE_ONLY_VIOLATION

    ok = evaluate_risk_policy(
        intent={"proposed_shape": {}, "is_paper": True, "is_closing": True},
        policy_rules=[
            {"rule_id": "po", "limit_class": "paper_only", "severity": "hard_block"},
            {"rule_id": "co", "limit_class": "close_only", "severity": "hard_block"},
        ],
        snapshots={},
    )
    assert ok["status"] == "pass"


def test_unknown_limit_class_is_missing_data_never_a_pass():
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": 1}},
        policy_rules=[{"rule_id": "weird", "limit_class": "made_up_class", "severity": "hard_block", "threshold": 1}],
        snapshots={},
    )
    assert v["rule_results"][0]["reason_code"] == RC_UNKNOWN_LIMIT_CLASS
    assert v["status"] == "missing_data"


def test_boolean_notional_is_rejected_not_coerced():
    # bool is an int subtype; a risk evaluator must not read True as 1.
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": True}},
        policy_rules=[{"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000}],
        snapshots={},
    )
    assert v["rule_results"][0]["missing_data"] is True


# --------------------------------------------------------------------------- #
# Non-finite (NaN / +/-Inf) inputs must NOT soft-pass a numeric limit.
#
# Regression for trade-trace-65nm: ``nan > threshold`` is ``False`` in Python,
# so a NaN observed magnitude would silently return RC_WITHIN_LIMIT — a
# soft-pass of a hard-block limit, violating §3.1 ("missing_data must NOT
# soft-pass"). _coerce_number now rejects non-finite results, routing NaN/Inf
# to missing_data. Covered for float AND inline-string forms across every
# numeric limit class (notional, exposure, loss, spread, slippage).
# --------------------------------------------------------------------------- #


# Inline-string forms of non-finite numbers (callers serialize sizes as strings;
# json.loads also accepts a bare literal NaN by default).
_NONFINITE_STRINGS = ["nan", "NaN", "inf", "-inf", "Infinity", "1e9999", "-1e9999"]
# Literal float forms.
_NONFINITE_FLOATS = [float("nan"), float("inf"), float("-inf")]


def _max_rule(limit_class):
    return [{"rule_id": "r", "limit_class": limit_class, "severity": "hard_block", "threshold": 1000}]


def _assert_not_within_limit(v):
    """A non-finite numeric input must route to missing_data, never a pass."""
    rr = v["rule_results"][0]
    assert rr["reason_code"] != RC_WITHIN_LIMIT, rr
    assert rr["reason_code"] == RC_MISSING_INPUT, rr
    assert rr["missing_data"] is True, rr
    assert v["status"] == "missing_data", v
    assert v["status"] != "pass", v


def test_nonfinite_notional_does_not_soft_pass():
    for bad in _NONFINITE_FLOATS + _NONFINITE_STRINGS:
        v = evaluate_risk_policy(
            intent={"proposed_shape": {"notional": bad}},
            policy_rules=_max_rule("notional"),
            snapshots={},
        )
        _assert_not_within_limit(v)


def test_nonfinite_exposure_does_not_soft_pass():
    for bad in _NONFINITE_FLOATS + _NONFINITE_STRINGS:
        v = evaluate_risk_policy(
            intent={"proposed_shape": {}},
            policy_rules=_max_rule("total_exposure"),
            snapshots={"exposure": {"total_exposure": bad}},
        )
        _assert_not_within_limit(v)


def test_nonfinite_loss_does_not_soft_pass():
    for bad in _NONFINITE_FLOATS + _NONFINITE_STRINGS:
        v = evaluate_risk_policy(
            intent={"proposed_shape": {}},
            policy_rules=_max_rule("daily_loss"),
            snapshots={"exposure": {"daily_loss": bad}},
        )
        _assert_not_within_limit(v)


def test_nonfinite_spread_does_not_soft_pass():
    for bad in _NONFINITE_FLOATS + _NONFINITE_STRINGS:
        v = evaluate_risk_policy(
            intent={"proposed_shape": {"notional": 1}},
            policy_rules=_max_rule("spread"),
            snapshots={"market": {"spread": bad}},
        )
        _assert_not_within_limit(v)


def test_nonfinite_slippage_does_not_soft_pass():
    for bad in _NONFINITE_FLOATS + _NONFINITE_STRINGS:
        v = evaluate_risk_policy(
            intent={"proposed_shape": {"notional": 1, "max_slippage": bad}},
            policy_rules=_max_rule("slippage"),
            snapshots={},
        )
        _assert_not_within_limit(v)


def test_nan_notional_aggregate_is_not_a_pass():
    # The original soft-pass: a single NaN notional rule must NOT aggregate to pass.
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": float("nan")}},
        policy_rules=_max_rule("notional"),
        snapshots={},
    )
    assert v["status"] == "missing_data"
    assert v["status"] != "pass"


def test_nan_does_not_override_a_real_hard_block():
    # A NaN (missing_data) rule alongside a genuine hard-block violation must
    # still fail — NaN must never mask or soft-pass a real block.
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": 9999}},
        policy_rules=[
            {"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000},
            {"rule_id": "spread", "limit_class": "spread", "severity": "hard_block", "threshold": 0.05},
        ],
        snapshots={"market": {"spread": float("nan")}},
    )
    by_id = {r["rule_id"]: r for r in v["rule_results"]}
    assert by_id["n"]["reason_code"] == RC_LIMIT_EXCEEDED
    assert by_id["spread"]["reason_code"] == RC_MISSING_INPUT
    assert by_id["spread"]["missing_data"] is True
    assert v["status"] == "fail"


def test_stale_snapshot_degrades_passing_rule_to_warn():
    v = evaluate_risk_policy(
        intent={"proposed_shape": {"notional": 1}},
        policy_rules=[{"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000}],
        snapshots={"stale": True},
    )
    assert v["stale_data"] is True
    assert v["rule_results"][0]["stale_data"] is True
    assert v["status"] == "warn"
    assert v["outcome"] == "stale_data"


def test_evaluator_is_deterministic_and_order_preserving():
    rules = [
        {"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000},
        {"rule_id": "spread", "limit_class": "spread", "severity": "warning", "threshold": 0.05},
        {"rule_id": "links", "limit_class": "required_links", "severity": "hard_block", "threshold": ["forecast_id"]},
    ]
    intent = {"proposed_shape": {"notional": 100}, "forecast_id": "f_1"}
    snaps = {"market": {"spread": 0.01}}
    first = evaluate_risk_policy(intent=intent, policy_rules=rules, snapshots=snaps)
    second = evaluate_risk_policy(intent=intent, policy_rules=rules, snapshots=snaps)
    assert first == second
    assert [r["rule_id"] for r in first["rule_results"]] == ["n", "spread", "links"]


# --------------------------------------------------------------------------- #
# risk.evaluate tool wired through the registry
# --------------------------------------------------------------------------- #


def _seed_policy(home, rules):
    _call("journal.init", {"home": str(home)}, actor_id="agent:init")
    res = _call("risk.policy_version_add", {
        "home": str(home),
        "policy_key": "default-pretrade-risk",
        "version": "2026-06-13.1",
        "limits_json": {"max_position_notional": 1000},
        "rules_json": rules,
        "source": "external-profile-risk-layer",
        "effective_from": "2026-06-13T00:00:00Z",
        "idempotency_key": "policy-key-1",
    })
    assert res.ok, res
    return res.data["id"]


def test_risk_evaluate_registered():
    from trade_trace.core import default_registry
    assert "risk.evaluate" in default_registry().names()


def test_risk_evaluate_is_read_only(tmp_path):
    from trade_trace.core import default_registry
    reg = default_registry().get("risk.evaluate")
    assert reg.is_write is False


def test_risk_evaluate_inline_intent_pass(tmp_path):
    home = tmp_path / "home"
    policy_id = _seed_policy(home, [
        {"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000},
    ])
    res = _call("risk.evaluate", {
        "home": str(home),
        "policy_version_id": policy_id,
        "proposed_intent": {"proposed_shape": {"notional": 100}},
        "snapshots": {},
    })
    assert res.ok, res
    data = res.data
    assert data["status"] == "pass"
    assert data["outcome"] == "pass"
    assert data["deterministic"] is True
    assert data["non_executing"] is True
    assert data["policy_key"] == "default-pretrade-risk"
    assert data["evaluated_rule_count"] == 1


def test_risk_evaluate_inline_intent_block(tmp_path):
    home = tmp_path / "home"
    policy_id = _seed_policy(home, [
        {"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000},
    ])
    res = _call("risk.evaluate", {
        "home": str(home),
        "policy_version_id": policy_id,
        "proposed_intent": {"proposed_shape": {"notional": 9999}},
    })
    assert res.ok, res
    assert res.data["status"] == "fail"
    assert res.data["outcome"] == "hard_block"
    assert res.data["rule_results"][0]["reason_code"] == RC_LIMIT_EXCEEDED


def test_risk_evaluate_missing_market_snapshot_does_not_soft_pass(tmp_path):
    home = tmp_path / "home"
    policy_id = _seed_policy(home, [
        {"rule_id": "spread", "limit_class": "spread", "severity": "warning", "threshold": 0.05},
    ])
    res = _call("risk.evaluate", {
        "home": str(home),
        "policy_version_id": policy_id,
        "proposed_intent": {"proposed_shape": {"notional": 1}},
        "snapshots": {"market": {}},
    })
    assert res.ok, res
    assert res.data["status"] == "missing_data"
    assert res.data["missing_data"] is True


def test_risk_evaluate_loads_stored_intent(tmp_path):
    home = tmp_path / "home"
    policy_id = _seed_policy(home, [
        {"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000},
        {"rule_id": "links", "limit_class": "required_links", "severity": "hard_block", "threshold": ["forecast_id"]},
    ])
    # Seed a market + an intent so risk.evaluate can load it by id.
    conn = sqlite3.connect(db_path(home))
    try:
        conn.execute(
            "INSERT INTO markets(id, source, external_id, title, question, state, mechanism, bound_via, venue_metadata_json, metadata_json, created_at, actor_id) "
            "VALUES ('m_1', 'polymarket', 'abc', 'ABC?', 'ABC?', 'open', 'clob', 'manual', '{}', '{}', '2026-06-13T00:00:00.000Z', 'agent:test')"
        )
        conn.commit()
    finally:
        conn.close()
    intent = _call("pretrade_intent.record", {
        "home": str(home),
        "semantic_key": "pm:market:abc:yes:2026-06-13T00:00Z",
        "market_id": "m_1",
        "proposed_shape": {"notional": 250, "side": "yes"},
        "as_of": "2026-06-13T00:00:00.000Z",
        "idempotency_key": "intent-1",
    })
    assert intent.ok, intent
    intent_id = intent.data["id"]

    res = _call("risk.evaluate", {
        "home": str(home),
        "policy_version_id": policy_id,
        "proposed_intent_id": intent_id,
    })
    assert res.ok, res
    # notional 250 < 1000 passes; required forecast_id link is absent -> fail.
    assert res.data["proposed_intent_id"] == intent_id
    by_id = {r["rule_id"]: r for r in res.data["rule_results"]}
    assert by_id["n"]["reason_code"] == RC_WITHIN_LIMIT
    assert by_id["links"]["reason_code"] == RC_REQUIRED_LINK_MISSING
    assert res.data["status"] == "fail"


def test_risk_evaluate_requires_an_intent(tmp_path):
    home = tmp_path / "home"
    policy_id = _seed_policy(home, [])
    res = _call("risk.evaluate", {"home": str(home), "policy_version_id": policy_id})
    assert not res.ok
    assert res.error.code.value == "VALIDATION_ERROR"


def test_risk_evaluate_unknown_policy_is_not_found(tmp_path):
    home = tmp_path / "home"
    _call("journal.init", {"home": str(home)}, actor_id="agent:init")
    res = _call("risk.evaluate", {
        "home": str(home),
        "policy_version_id": "rpv_does_not_exist",
        "proposed_intent": {"proposed_shape": {"notional": 1}},
    })
    assert not res.ok
    assert res.error.code.value == "NOT_FOUND"


def test_risk_evaluate_verdict_is_recordable_as_a_receipt(tmp_path):
    """The evaluator output must drop straight into risk.check_record unchanged.

    This is the spine: risk.evaluate produces the verdict; risk.check_record then
    persists it as an immutable receipt instead of trusting a hand-crafted one.
    """

    home = tmp_path / "home"
    policy_id = _seed_policy(home, [
        {"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000},
    ])
    verdict = _call("risk.evaluate", {
        "home": str(home),
        "policy_version_id": policy_id,
        "proposed_intent": {"proposed_shape": {"notional": 9999}},
    })
    assert verdict.ok, verdict
    recorded = _call("risk.check_record", {
        "home": str(home),
        "policy_version_id": policy_id,
        "status": verdict.data["status"],
        "outcome": verdict.data["outcome"],
        "as_of": "2026-06-13T00:00:00.000Z",
        "proposed_intent_hash": "deadbeef",
        "rule_results": verdict.data["rule_results"],
        "idempotency_key": "receipt-from-eval-1",
    })
    assert recorded.ok, recorded
    assert recorded.data["status"] == "fail"
    assert recorded.data["outcome"] == "hard_block"


def test_risk_check_record_rejects_verdict_contradicting_evaluator(tmp_path):
    """Verdict provenance guard (trade-trace-ur8w).

    When the caller passes the evaluator inputs into risk.check_record, the
    recorded status/outcome/rule_results are re-derived with evaluate_risk_policy
    and the write is refused if they disagree. A hand-asserted ``pass`` cannot be
    recorded alongside an intent the evaluator hard-blocks.
    """

    home = tmp_path / "home"
    policy_id = _seed_policy(home, [
        {"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000},
    ])
    res = _call("risk.check_record", {
        "home": str(home),
        "policy_version_id": policy_id,
        "status": "pass",
        "outcome": "pass",
        "as_of": "2026-06-13T00:00:00.000Z",
        "proposed_intent_hash": "deadbeef",
        "rule_results": [{
            "rule_id": "n", "reason_code": RC_WITHIN_LIMIT, "severity": "info",
            "observed_value": {"notional": 1}, "threshold": {"max": 1000},
            "contributing_record_ids": [], "waiver_required": False,
        }],
        # Inputs that the evaluator turns into fail/hard_block.
        "proposed_intent": {"proposed_shape": {"notional": 9999}},
        "idempotency_key": "contradiction-1",
    })
    assert res.ok is False
    assert res.error.code.value == "VALIDATION_ERROR"
    assert res.error.details["evaluated"]["status"] == "fail"


def test_risk_check_record_without_evaluator_inputs_is_caller_asserted(tmp_path):
    """The legacy path: no evaluator inputs => no guard, the receipt is recorded
    exactly as the external risk layer asserts it (trade-trace-ur8w)."""

    home = tmp_path / "home"
    policy_id = _seed_policy(home, [
        {"rule_id": "n", "limit_class": "notional", "severity": "hard_block", "threshold": 1000},
    ])
    res = _call("risk.check_record", {
        "home": str(home),
        "policy_version_id": policy_id,
        "status": "pass",
        "outcome": "pass",
        "as_of": "2026-06-13T00:00:00.000Z",
        "intended_action": "pretrade_audit",
        "rule_results": [{
            "rule_id": "n", "reason_code": RC_WITHIN_LIMIT, "severity": "info",
            "observed_value": {"notional": 1}, "threshold": {"max": 1000},
            "contributing_record_ids": [], "waiver_required": False,
        }],
        "idempotency_key": "caller-asserted-1",
    })
    assert res.ok, res
    assert res.data["status"] == "pass"
