"""risk-unit write surface + report.risk per trade-trace-8z2."""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path
from trade_trace.tools._helpers import new_id


def _env(home: Path, tool: str, args: dict):
    return mcp_call(tool, {"home": str(home), **args}, actor_id="agent:default").model_dump(
        mode="json", exclude_none=True,
    )


def _instrument(home: Path, title: str = "R") -> str:
    """Seed venue + instrument + thesis and return the instrument id.
    A thesis is needed because actual_enter decisions require thesis_id
    per PRD §3.1; the tests below use that decision type so the seed
    creates the thesis up-front rather than per-call."""

    venue = _env(home, "venue.add", {"name": f"PM-{title}", "kind": "prediction_market"})
    inst = _env(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": title,
    })
    instrument_id = inst["data"]["id"]
    _env(home, "thesis.add", {
        "instrument_id": instrument_id,
        "side": "long",
        "body": f"test thesis for {title}",
    })
    return instrument_id


def _closed_position(home: Path, instrument_id: str, realized_pnl: float, status: str = "closed") -> None:
    db = open_database(db_path(home))
    try:
        with db.transaction():
            db.connection.execute(
                "INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, "
                "closed_at, resolved_at, realized_pnl, unrealized_pnl, avg_entry_price, updated_at) "
                "VALUES (?, ?, 'paper', 'long', ?, '2026-05-18T14:00:00Z', "
                "'2026-05-18T16:00:00Z', NULL, ?, NULL, 0.40, '2026-05-18T16:00:00Z')",
                (new_id("pos"), instrument_id, status, realized_pnl),
            )
    finally:
        db.close()


def test_report_risk_registered():
    assert "report.risk" in default_registry().names()


def test_decision_add_persists_all_risk_fields(home):
    inst = _instrument(home)
    env = _env(home, "decision.add", {
        "type": "add", "instrument_id": inst, "side": "long",
        "quantity": 10, "price": 2.0, "declared_risk_amount": "100",
        "declared_risk_unit": "USD", "expected_edge": "1.25",
        "expected_edge_after_costs": "1.0", "cost_basis_estimate": "20.5",
        "risk_reward_estimate": "2.5",
    })
    assert env["ok"], env
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT declared_risk_amount, declared_risk_unit, expected_edge, "
            "expected_edge_after_costs, cost_basis_estimate, risk_reward_estimate "
            "FROM decisions WHERE id = ?",
            (env["data"]["id"],),
        ).fetchone()
    finally:
        db.close()
    assert tuple(row) == (100.0, "USD", 1.25, 1.0, 20.5, 2.5)


@pytest.mark.parametrize("bad_args,field", [
    ({"declared_risk_amount": -1}, "declared_risk_amount"),
    ({"declared_risk_amount": "abc"}, "declared_risk_amount"),
    ({"expected_edge": 0.5, "expected_edge_after_costs": 0.6}, "expected_edge_after_costs"),
])
def test_invalid_risk_fields_return_validation_error(home, bad_args, field):
    inst = _instrument(home, field)
    env = _env(home, "decision.add", {
        "type": "add", "instrument_id": inst, "side": "long",
        "quantity": 1, "price": 1.0, **bad_args,
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == field
    assert "sqlite_error" not in env["error"].get("details", {})


def test_report_risk_aggregates_r_and_missing_caveats_and_pnl_still_works(home):
    inst_win = _instrument(home, "win")
    inst_loss = _instrument(home, "loss")
    inst_missing = _instrument(home, "missing")
    inst_pending = _instrument(home, "pending")

    _env(home, "decision.add", {"type": "add", "instrument_id": inst_win, "side": "long", "quantity": 1, "price": 1, "declared_risk_amount": 100})
    _env(home, "decision.add", {"type": "add", "instrument_id": inst_loss, "side": "long", "quantity": 1, "price": 1, "declared_risk_amount": 50})
    _env(home, "decision.add", {"type": "add", "instrument_id": inst_missing, "side": "long", "quantity": 1, "price": 1})
    _env(home, "decision.add", {"type": "add", "instrument_id": inst_pending, "side": "long", "quantity": 1, "price": 1, "declared_risk_amount": 25})
    _closed_position(home, inst_win, 250.0)
    _closed_position(home, inst_loss, -25.0)
    _closed_position(home, inst_missing, 10.0)

    risk = _env(home, "report.risk", {})
    assert risk["ok"], risk
    metrics = risk["data"]["summary"]["metrics"]
    assert metrics["n_closed_with_risk"] == 2
    assert metrics["n_closed_total"] == 3
    assert metrics["mean_r"] == pytest.approx(1.0)
    assert metrics["median_r"] == pytest.approx(1.0)
    assert metrics["expectancy_r"] == pytest.approx(1.0)
    assert metrics["win_rate_r"] == pytest.approx(0.5)
    assert metrics["payoff_ratio_r"] == pytest.approx(5.0)
    assert risk["data"]["summary"]["missing_risk_count"] == 1
    assert risk["data"]["summary"]["pending_risk_count"] == 1
    assert any("missing declared_risk_amount" in c for c in risk["data"]["summary"]["caveats"])

    pnl = _env(home, "report.pnl", {})
    assert pnl["ok"], pnl
    assert pnl["data"]["summary"]["metrics"]["realized_pnl"] == pytest.approx(235.0)


def test_report_risk_rejects_unsupported_filters_cleanly(home):
    env = _env(home, "report.risk", {"filter": {"decision": {"decision_type": ["actual_enter"]}}})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert "unsupported_filter_paths" in env["error"]["details"]


def test_risk_policy_versions_and_receipts_are_deterministic_and_reported(home):
    inst = _instrument(home, "risk-receipt")
    policy = _env(home, "risk.policy_version_add", {
        "policy_key": "profile/default",
        "version": "2026-05-28",
        "limits_json": {"max_position_usd": 100},
        "rules_json": [{"rule_id": "position_limit", "severity": "hard_block"}],
        "source": "profile_fixture",
        "provenance_json": {"author": "test"},
        "effective_from": "2026-05-28T00:00:00Z",
        "idempotency_key": "risk-policy-v1",
    })
    assert policy["ok"], policy
    replay = _env(home, "risk.policy_version_add", {
        "policy_key": "profile/default",
        "version": "2026-05-28",
        "limits_json": {"max_position_usd": 100},
        "rules_json": [{"rule_id": "position_limit", "severity": "hard_block"}],
        "source": "profile_fixture",
        "provenance_json": {"author": "test"},
        "effective_from": "2026-05-28T00:00:00Z",
        "idempotency_key": "risk-policy-v1",
    })
    assert replay["ok"], replay
    assert replay["data"]["id"] == policy["data"]["id"]
    conflict = _env(home, "risk.policy_version_add", {
        "policy_key": "profile/default",
        "version": "2026-05-28",
        "limits_json": {"max_position_usd": 200},
        "rules_json": [{"rule_id": "position_limit", "severity": "hard_block"}],
        "source": "profile_fixture",
        "effective_from": "2026-05-28T00:00:00Z",
        "idempotency_key": "risk-policy-v1",
    })
    assert conflict["ok"] is False
    assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    receipt = _env(home, "risk.check_record", {
        "policy_version_id": policy["data"]["id"],
        "status": "fail",
        "outcome": "hard_block",
        "intended_action": "journal_pretrade_packet",
        "proposed_intent_hash": "sha256:intent",
        "instrument_id": inst,
        "exposure_input_ids_json": ["pos_1"],
        "evidence_input_ids_json": ["src_1"],
        "input_provenance_json": {"exposure_as_of": "2026-05-28T12:00:00Z"},
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [{
            "rule_id": "position_limit",
            "reason_code": "POSITION_LIMIT_EXCEEDED",
            "severity": "hard_block",
            "observed_value": {"usd": 150},
            "threshold": {"max_usd": 100},
            "contributing_record_ids": ["pos_1"],
            "waiver_required": False,
        }],
        "idempotency_key": "risk-receipt-1",
    })
    assert receipt["ok"], receipt
    assert receipt["data"]["status"] == "fail"
    assert receipt["data"]["rule_results"][0]["reason_code"] == "POSITION_LIMIT_EXCEEDED"

    report = _env(home, "report.risk", {})
    assert report["ok"], report
    summary = report["data"]["summary"]
    assert summary["risk_policy_versions"]["available"] is True
    assert summary["risk_policy_versions"]["recent_policy_versions"][0]["policy_hash"] == policy["data"]["policy_hash"]
    assert summary["risk_check_receipts"]["recent_blocked_or_waived_checks"][0]["id"] == receipt["data"]["id"]
    assert "no trading advice" in summary["audit_only_note"]


def test_risk_missing_data_never_silent_pass(home):
    policy = _env(home, "risk.policy_version_add", {
        "policy_key": "profile/default",
        "version": "missing-data",
        "limits_json": {},
        "rules_json": [{"rule_id": "fresh_exposure", "severity": "missing_data"}],
        "source": "profile_fixture",
        "effective_from": "2026-05-28T00:00:00Z",
    })
    assert policy["ok"], policy
    bad = _env(home, "risk.check_record", {
        "policy_version_id": policy["data"]["id"],
        "status": "missing_data",
        "outcome": "missing_data",
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [{"rule_id": "fresh_exposure", "reason_code": "EXPOSURE_INPUT_MISSING", "severity": "missing_data"}],
    })
    assert bad["ok"] is False
    assert bad["error"]["code"] == "VALIDATION_ERROR"

    ok = _env(home, "risk.check_record", {
        "policy_version_id": policy["data"]["id"],
        "status": "missing_data",
        "outcome": "missing_data",
        "as_of": "2026-05-28T12:00:00Z",
        "evidence_input_ids_json": ["src_missing_exposure"],
        "rule_results": [{
            "rule_id": "fresh_exposure",
            "reason_code": "EXPOSURE_INPUT_MISSING",
            "severity": "missing_data",
            "missing_data": True,
            "waiver_required": True,
            "contributing_record_ids": [],
            "caveat": "exposure snapshot absent",
        }],
    })
    assert ok["ok"], ok
    assert ok["data"]["status"] == "missing_data"


def _risk_policy(home: Path, version: str = "qa-risk") -> str:
    policy = _env(home, "risk.policy_version_add", {
        "policy_key": "profile/default",
        "version": version,
        "limits_json": {},
        "rules_json": [{"rule_id": "limit", "severity": "info"}],
        "source": "profile_fixture",
        "effective_from": "2026-05-28T00:00:00Z",
    })
    assert policy["ok"], policy
    return policy["data"]["id"]


def _valid_rule(**overrides):
    rule = {
        "rule_id": "limit",
        "reason_code": "WITHIN_LIMIT",
        "severity": "info",
        "observed_value": {"usd": 10},
        "threshold": {"max_usd": 100},
        "contributing_record_ids": ["pos_1"],
        "waiver_required": False,
    }
    rule.update(overrides)
    return rule


def test_risk_check_record_rejects_unanchored_receipt(home):
    policy_id = _risk_policy(home, "unanchored")
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "pass",
        "outcome": "pass",
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [_valid_rule()],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "receipt_anchor"


@pytest.mark.parametrize("anchor", [
    {"intended_action": "pretrade_audit"},
    {"exposure_input_ids_json": ["pos_anchor"]},
    {"evidence_input_ids_json": ["src_anchor"]},
])
def test_risk_check_record_accepts_representative_anchors(home, anchor):
    policy_id = _risk_policy(home, "anchor-" + next(iter(anchor)))
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "pass",
        "outcome": "pass",
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [_valid_rule()],
        **anchor,
    })
    assert env["ok"], env


@pytest.mark.parametrize("drop_field", ["rule_id", "reason_code", "severity", "waiver_required", "contributing_record_ids"])
def test_risk_rule_results_require_acceptance_fields(home, drop_field):
    policy_id = _risk_policy(home, "missing-" + drop_field)
    rule = _valid_rule()
    rule.pop(drop_field)
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "pass",
        "outcome": "pass",
        "instrument_id": "ins_anchor",
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [rule],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == drop_field


def test_risk_rule_results_require_observed_threshold_unless_missing_or_stale(home):
    policy_id = _risk_policy(home, "observed-threshold")
    rule = _valid_rule()
    rule.pop("observed_value")
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id, "status": "pass", "outcome": "pass",
        "instrument_id": "ins_anchor", "as_of": "2026-05-28T12:00:00Z", "rule_results": [rule],
    })
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "observed_value"


def test_risk_rule_results_require_caveat_for_missing_or_stale(home):
    policy_id = _risk_policy(home, "stale-caveat")
    rule = _valid_rule(stale_data=True)
    rule.pop("observed_value")
    rule.pop("threshold")
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id, "status": "warn", "outcome": "stale_data",
        "instrument_id": "ins_anchor", "as_of": "2026-05-28T12:00:00Z", "rule_results": [rule],
    })
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "caveat"


def test_risk_check_record_rejects_pass_with_missing_data_rule(home):
    policy_id = _risk_policy(home, "pass-missing-data")
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "pass",
        "outcome": "pass",
        "instrument_id": "ins_anchor",
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [_valid_rule(
            missing_data=True,
            caveat="exposure snapshot absent",
            reason_code="EXPOSURE_INPUT_MISSING",
            severity="missing_data",
        )],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "status"



def test_risk_check_record_rejects_pass_with_stale_data_rule(home):
    policy_id = _risk_policy(home, "pass-stale-data")
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "pass",
        "outcome": "pass",
        "instrument_id": "ins_anchor",
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [_valid_rule(
            stale_data=True,
            caveat="exposure snapshot stale",
            reason_code="EXPOSURE_INPUT_STALE",
            severity="warning",
        )],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "status"



def test_risk_check_record_accepts_missing_data_status_with_missing_data_rule(home):
    policy_id = _risk_policy(home, "accepted-missing-data")
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "missing_data",
        "outcome": "missing_data",
        "evidence_input_ids_json": ["src_missing_exposure"],
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [_valid_rule(
            missing_data=True,
            caveat="exposure snapshot absent",
            reason_code="EXPOSURE_INPUT_MISSING",
            severity="missing_data",
        )],
    })
    assert env["ok"], env
    assert env["data"]["status"] == "missing_data"


def test_risk_check_record_accepts_warn_with_stale_data_rule(home):
    policy_id = _risk_policy(home, "accepted-stale-data")
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "warn",
        "outcome": "stale_data",
        "evidence_input_ids_json": ["src_stale_exposure"],
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [_valid_rule(
            stale_data=True,
            caveat="exposure snapshot stale",
            reason_code="EXPOSURE_INPUT_STALE",
            severity="warning",
        )],
    })
    assert env["ok"], env
    assert env["data"]["status"] == "warn"


def test_risk_hash_mismatch_is_rejected(home):
    policy = _env(home, "risk.policy_version_add", {
        "policy_key": "profile/default", "version": "bad-hash", "limits_json": {}, "rules_json": [],
        "source": "profile_fixture", "effective_from": "2026-05-28T00:00:00Z", "policy_hash": "not-canonical",
    })
    assert policy["ok"] is False
    assert policy["error"]["details"]["field"] == "policy_hash"
    policy_id = _risk_policy(home, "bad-receipt-hash")
    receipt = _env(home, "risk.check_record", {
        "policy_version_id": policy_id, "status": "pass", "outcome": "pass", "instrument_id": "ins_anchor",
        "as_of": "2026-05-28T12:00:00Z", "rule_results": [_valid_rule()], "receipt_hash": "not-canonical",
    })
    assert receipt["ok"] is False
    assert receipt["error"]["details"]["field"] == "receipt_hash"
