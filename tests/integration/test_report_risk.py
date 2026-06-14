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


def _closed_position(
    home: Path,
    instrument_id: str,
    realized_pnl: float,
    status: str = "closed",
    *,
    decision_id: str | None = None,
    position_id: str | None = None,
) -> str:
    """Seed a position and (when `decision_id` is supplied) the
    `position_events` open row that links the decision to it, mirroring the
    production path where decisions reach positions through position_events
    rather than the shared instrument_id (trade-trace-rtxy). Returns the
    position id."""

    position_id = position_id or new_id("pos")
    db = open_database(db_path(home))
    try:
        with db.transaction():
            db.connection.execute(
                "INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, "
                "closed_at, resolved_at, realized_pnl, unrealized_pnl, avg_entry_price, updated_at) "
                "VALUES (?, ?, 'paper', 'long', ?, '2026-05-18T14:00:00Z', "
                "'2026-05-18T16:00:00Z', NULL, ?, NULL, 0.40, '2026-05-18T16:00:00Z')",
                (position_id, instrument_id, status, realized_pnl),
            )
            if decision_id is not None:
                db.connection.execute(
                    "INSERT INTO position_events(id, position_id, instrument_id, "
                    "decision_id, event_type, quantity_delta, price, fees, slippage, "
                    "created_at, actor_id) "
                    "VALUES (?, ?, ?, ?, 'open', 1, 0.40, 0, 0, "
                    "'2026-05-18T14:00:00Z', 'agent:test')",
                    (new_id("pev"), position_id, instrument_id, decision_id),
                )
    finally:
        db.close()
    return position_id


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
    # _optional_float ValueError path for the remaining numeric fields
    # (decision.py:84-89). Each non-numeric value must surface a clean
    # VALIDATION_ERROR naming the field, not a raw float() ValueError or a
    # downstream SQLite CHECK string (trade-trace-nyix).
    ({"cost_basis_estimate": "not-a-number"}, "cost_basis_estimate"),
    ({"risk_reward_estimate": "not-a-number"}, "risk_reward_estimate"),
    ({"expected_edge": "not-a-number"}, "expected_edge"),
    ({"expected_edge_after_costs": "not-a-number"}, "expected_edge_after_costs"),
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


def test_expected_edge_after_costs_float_tolerance_boundary(home):
    """Pin the 1e-9 float tolerance in decision.py's tool-layer guard
    (`expected_edge_after_costs > expected_edge + 1e-9`) through the dispatch
    surface, not the SQLite CHECK (trade-trace-il3f).

    expected_edge_after_costs = expected_edge + 1e-10 is within tolerance and
    must succeed; expected_edge_after_costs = expected_edge + 2e-9 exceeds it
    and must raise VALIDATION_ERROR with details.field pinned to the offending
    field — proving the Python guard, not just the DB CHECK trigger, fires."""

    expected_edge = 0.5

    # Within tolerance (delta < 1e-9): the guard must NOT fire.
    inst_ok = _instrument(home, "tol-ok")
    env_ok = _env(home, "decision.add", {
        "type": "add", "instrument_id": inst_ok, "side": "long",
        "quantity": 1, "price": 1.0,
        "expected_edge": expected_edge,
        "expected_edge_after_costs": expected_edge + 1e-10,
    })
    assert env_ok["ok"] is True, env_ok

    # Beyond tolerance (delta > 1e-9): the guard must fire at the tool layer.
    inst_bad = _instrument(home, "tol-bad")
    env_bad = _env(home, "decision.add", {
        "type": "add", "instrument_id": inst_bad, "side": "long",
        "quantity": 1, "price": 1.0,
        "expected_edge": expected_edge,
        "expected_edge_after_costs": expected_edge + 2e-9,
    })
    assert env_bad["ok"] is False
    assert env_bad["error"]["code"] == "VALIDATION_ERROR"
    assert env_bad["error"]["details"]["field"] == "expected_edge_after_costs"
    assert "sqlite_error" not in env_bad["error"].get("details", {})


def test_report_risk_aggregates_r_and_missing_caveats_and_pnl_still_works(home):
    inst_win = _instrument(home, "win")
    inst_loss = _instrument(home, "loss")
    inst_missing = _instrument(home, "missing")
    inst_pending = _instrument(home, "pending")

    dec_win = _env(home, "decision.add", {"type": "add", "instrument_id": inst_win, "side": "long", "quantity": 1, "price": 1, "declared_risk_amount": 100})["data"]["id"]
    dec_loss = _env(home, "decision.add", {"type": "add", "instrument_id": inst_loss, "side": "long", "quantity": 1, "price": 1, "declared_risk_amount": 50})["data"]["id"]
    dec_missing = _env(home, "decision.add", {"type": "add", "instrument_id": inst_missing, "side": "long", "quantity": 1, "price": 1})["data"]["id"]
    _env(home, "decision.add", {"type": "add", "instrument_id": inst_pending, "side": "long", "quantity": 1, "price": 1, "declared_risk_amount": 25})
    _closed_position(home, inst_win, 250.0, decision_id=dec_win)
    _closed_position(home, inst_loss, -25.0, decision_id=dec_loss)
    _closed_position(home, inst_missing, 10.0, decision_id=dec_missing)

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


def _open_position(home: Path, instrument_id: str, decision_id: str | None = None) -> str:
    """Seed an OPEN position (no realized P&L) and optionally link it to a
    decision via a position_events open row."""

    position_id = new_id("pos")
    db = open_database(db_path(home))
    try:
        with db.transaction():
            db.connection.execute(
                "INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, "
                "closed_at, resolved_at, realized_pnl, unrealized_pnl, avg_entry_price, updated_at) "
                "VALUES (?, ?, 'paper', 'long', 'open', '2026-05-18T14:00:00Z', "
                "NULL, NULL, NULL, NULL, 0.40, '2026-05-18T16:00:00Z')",
                (position_id, instrument_id),
            )
            if decision_id is not None:
                db.connection.execute(
                    "INSERT INTO position_events(id, position_id, instrument_id, "
                    "decision_id, event_type, quantity_delta, price, fees, slippage, "
                    "created_at, actor_id) "
                    "VALUES (?, ?, ?, ?, 'open', 1, 0.40, 0, 0, "
                    "'2026-05-18T14:00:00Z', 'agent:test')",
                    (new_id("pev"), position_id, instrument_id, decision_id),
                )
    finally:
        db.close()
    return position_id


def test_report_risk_does_not_inflate_on_instrument_with_multiple_positions(home):
    """Regression for trade-trace-rtxy: an instrument that carries several
    position rows (the old `positions.instrument_id = decisions.instrument_id`
    join fanned each decision out to one row per position) must contribute its
    decision exactly once. Here a SINGLE decision opens one closed position,
    but the instrument also has an unrelated open position and an unrelated
    extra closed position. Under the buggy join the decision's R-multiple was
    counted three times (and the decision could land in both the histogram and
    the pending caveat); under the fix it is counted once."""

    inst = _instrument(home, "fanout")
    # The decision under test: links (via position_events) to ONE closed
    # position with realized_pnl 200 against declared risk 100 -> R = 2.0.
    dec = _env(home, "decision.add", {
        "type": "add", "instrument_id": inst, "side": "long",
        "quantity": 1, "price": 1, "declared_risk_amount": 100,
    })["data"]["id"]
    _closed_position(home, inst, 200.0, decision_id=dec)
    # Unrelated extra position rows on the SAME instrument with no decision
    # link. The old instrument_id join would have multiplied `dec` across all
    # of these; the new position_events join ignores them for `dec`.
    _closed_position(home, inst, 999.0)  # extra closed, not linked to dec
    _open_position(home, inst)  # open, not linked to dec

    risk = _env(home, "report.risk", {})
    assert risk["ok"], risk
    metrics = risk["data"]["summary"]["metrics"]
    summary = risk["data"]["summary"]
    # Exactly one closed-with-risk decision; not 3, not inflated.
    assert metrics["n_closed_with_risk"] == 1
    assert summary["sample_size"] == 1
    assert metrics["mean_r"] == pytest.approx(2.0)
    assert metrics["best_r"] == pytest.approx(2.0)
    assert metrics["worst_r"] == pytest.approx(2.0)
    assert metrics["win_count"] == 1
    assert metrics["win_rate_r"] == pytest.approx(1.0)
    # Coverage is computed over closed decisions, not closed positions: the
    # extra unlinked closed position does not appear as a decision row, so it
    # must not inflate the denominator either.
    assert metrics["coverage"] == pytest.approx(1.0)
    # The R distribution histogram carries a single observation.
    assert sum(b["count"] for b in metrics["r_distribution"]) == 1
    # The decision is NOT simultaneously in the pending caveat.
    assert summary["pending_risk_count"] == 0


def test_report_risk_one_decision_with_multiple_closed_positions_counts_once(home):
    """Second fan-out shape from trade-trace-rtxy: one instrument with N closed
    positions. Only the decision-linked position contributes; the decision's
    R-multiple is counted once, not N times."""

    inst = _instrument(home, "multiclosed")
    dec = _env(home, "decision.add", {
        "type": "add", "instrument_id": inst, "side": "long",
        "quantity": 1, "price": 1, "declared_risk_amount": 100,
    })["data"]["id"]
    # Link the decision to one closed position (R = 1.0); seed two more closed
    # positions on the same instrument that are NOT linked to the decision.
    _closed_position(home, inst, 100.0, decision_id=dec)
    _closed_position(home, inst, 500.0)
    _closed_position(home, inst, -300.0)

    risk = _env(home, "report.risk", {})
    assert risk["ok"], risk
    metrics = risk["data"]["summary"]["metrics"]
    assert metrics["n_closed_with_risk"] == 1
    assert metrics["mean_r"] == pytest.approx(1.0)
    assert metrics["best_r"] == pytest.approx(1.0)
    assert metrics["worst_r"] == pytest.approx(1.0)
    assert risk["data"]["summary"]["sample_size"] == 1


def test_report_risk_surfaces_prominent_coverage_block(home):
    """trade-trace-62fj: report.risk must surface the denominator caveat
    prominently — a top-level `coverage` block stating how many resolved markets
    actually carry declared risk (the fraction expectancy_r is computed over),
    plus a pointer to the longitudinal compare base report."""

    inst_with = _instrument(home, "cov-with")
    inst_missing = _instrument(home, "cov-missing")
    dec_with = _env(home, "decision.add", {
        "type": "add", "instrument_id": inst_with, "side": "long",
        "quantity": 1, "price": 1, "declared_risk_amount": 100,
    })["data"]["id"]
    dec_missing = _env(home, "decision.add", {
        "type": "add", "instrument_id": inst_missing, "side": "long",
        "quantity": 1, "price": 1,
    })["data"]["id"]
    _closed_position(home, inst_with, 150.0, decision_id=dec_with)
    _closed_position(home, inst_missing, 40.0, decision_id=dec_missing)

    risk = _env(home, "report.risk", {})
    assert risk["ok"], risk
    summary = risk["data"]["summary"]
    coverage = summary["coverage"]
    # one of two closed decisions carries declared risk -> 50% coverage
    assert coverage["eligible_count"] == 2
    assert coverage["included_count"] == 1
    assert coverage["missing_count"] == 1
    assert coverage["coverage_pct"] == 50.0
    assert coverage["denominator_kind"] == "closed_decisions"
    assert "declared a positive risk amount" in coverage["note"]
    # prominent pointer to the over-time / per-strategy expectancy series
    assert "report.compare" in summary["longitudinal_expectancy_report"]
    assert "period" in summary["longitudinal_expectancy_report"]
    # exactly-0.5 coverage does NOT trip the below-0.5 caveat (boundary is
    # exclusive); the missing-risk caveat still fires.
    assert not any("coverage is below 0.5" in c for c in summary["caveats"])
    assert any("missing declared_risk_amount" in c for c in summary["caveats"])


def test_report_risk_coverage_block_full_when_all_declared(home):
    inst = _instrument(home, "cov-full")
    dec = _env(home, "decision.add", {
        "type": "add", "instrument_id": inst, "side": "long",
        "quantity": 1, "price": 1, "declared_risk_amount": 100,
    })["data"]["id"]
    _closed_position(home, inst, 100.0, decision_id=dec)
    risk = _env(home, "report.risk", {})
    assert risk["ok"], risk
    coverage = risk["data"]["summary"]["coverage"]
    assert coverage["eligible_count"] == 1
    assert coverage["included_count"] == 1
    assert coverage["coverage_pct"] == 100.0


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


def _risk_receipt(home: Path, version: str = "append-only") -> str:
    policy_id = _risk_policy(home, version)
    receipt = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "pass",
        "outcome": "pass",
        "exposure_input_ids_json": ["pos_anchor"],
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [_valid_rule()],
        "idempotency_key": f"receipt-{version}",
    })
    assert receipt["ok"], receipt
    replay = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "pass",
        "outcome": "pass",
        "exposure_input_ids_json": ["pos_anchor"],
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [_valid_rule()],
        "idempotency_key": f"receipt-{version}",
    })
    assert replay["ok"], replay
    assert replay["data"]["id"] == receipt["data"]["id"]
    return receipt["data"]["id"]


@pytest.mark.parametrize("table,statement", [
    ("risk_check_receipts", "UPDATE risk_check_receipts SET status = 'warn' WHERE id = ?"),
    ("risk_check_receipts", "DELETE FROM risk_check_receipts WHERE id = ?"),
    ("risk_check_rule_results", "UPDATE risk_check_rule_results SET severity = 'warning' WHERE receipt_id = ?"),
    ("risk_check_rule_results", "DELETE FROM risk_check_rule_results WHERE receipt_id = ?"),
])
def test_risk_receipt_tables_are_db_append_only(home, table, statement):
    receipt_id = _risk_receipt(home, f"append-only-{table}-{statement.split()[0].lower()}")
    db = open_database(db_path(home), create_parent=False)
    try:
        with pytest.raises(Exception, match="append-only invariant"):
            db.connection.execute(statement, (receipt_id,))
    finally:
        db.close()


_BAD_SECRET = "s" + "k" + "-" + ("FAKEKEY" * 4)[:24]


@pytest.mark.parametrize("field,bad_value", [
    ("limits_json", {"api_key": "not persisted"}),
    ("rules_json", [{"rule_id": "limit", "private_key": "not persisted"}]),
    ("source", "contains " + _BAD_SECRET),
])
def test_risk_policy_version_add_rejects_credentials_and_secrets(home, field, bad_value):
    args = {
        "policy_key": "profile/default",
        "version": "secret-guard-" + field,
        "limits_json": {},
        "rules_json": [{"rule_id": "limit", "severity": "info"}],
        "source": "profile_fixture",
        "effective_from": "2026-05-28T00:00:00Z",
        field: bad_value,
    }
    env = _env(home, "risk.policy_version_add", args)
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == field


@pytest.mark.parametrize("field,bad_value", [
    ("exposure_input_ids_json", [{"session_token": "not persisted"}]),
    ("evidence_input_ids_json", ["contains " + _BAD_SECRET]),
    ("input_provenance_json", {"broker_token": "not persisted"}),
    ("intended_action", "contains " + _BAD_SECRET),
    ("waived_by", "contains " + _BAD_SECRET),
    ("waiver_reason", "contains " + _BAD_SECRET),
    ("rule_results", [_valid_rule(observed_value={"signing_key": "not persisted"})]),
    ("rule_results", [_valid_rule(caveat="contains " + _BAD_SECRET)]),
])
def test_risk_check_record_rejects_credentials_and_secrets(home, field, bad_value):
    policy_id = _risk_policy(home, "secret-guard-receipt-" + field)
    args = {
        "policy_version_id": policy_id,
        "status": "warn" if field in {"waived_by", "waiver_reason"} else "pass",
        "outcome": "waived_warning" if field in {"waived_by", "waiver_reason"} else "pass",
        "instrument_id": "ins_anchor",
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [_valid_rule()],
        field: bad_value,
    }
    if field == "rule_results":
        args["rule_results"] = bad_value
    if field == "waiver_reason":
        args["waived_by"] = "risk-officer"
    env = _env(home, "risk.check_record", args)
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == field


# ---------------------------------------------------------------------------
# Freeze-state regression (bead trade-trace-ur8w)
#
# The risk policy/receipt/evaluate cluster was UNFROZEN into the public Phase-2
# catalog now that the deterministic evaluator ships. These tests PIN that
# non-experimental state so a future accidental re-freeze (re-adding the tools
# to EXPERIMENTAL_AUTONOMOUS_OPS) is caught here rather than silently shipping a
# blank public risk surface.
# ---------------------------------------------------------------------------

_RISK_CLUSTER = ("risk.policy_version_add", "risk.check_record", "risk.evaluate")


def test_risk_cluster_is_not_frozen():
    from trade_trace.core import (
        EXPERIMENTAL_AUTONOMOUS_OPS,
        EXPERIMENTAL_FROZEN_TOOLS,
        build_registry,
    )

    reg = build_registry()
    public = set(reg.public_names())
    for name in _RISK_CLUSTER:
        entry = reg.get(name)
        assert entry is not None, f"{name} should be registered"
        assert entry.catalog_visibility != "experimental", (
            f"{name} regressed to catalog_visibility=experimental; the risk "
            "cluster was unfrozen in trade-trace-ur8w"
        )
        assert name in public, f"{name} must appear in the default public catalog"
        # Pin the SOURCE of the freeze, not just its registry effect.
        assert name not in EXPERIMENTAL_AUTONOMOUS_OPS, (
            f"{name} was re-added to EXPERIMENTAL_AUTONOMOUS_OPS"
        )
        assert name not in EXPERIMENTAL_FROZEN_TOOLS, (
            f"{name} re-entered the frozen-tools union"
        )


# ---------------------------------------------------------------------------
# Verdict provenance consistency guard (bead trade-trace-ur8w)
#
# risk.check_record still accepts a caller-asserted verdict (the legacy
# external/profile-risk-layer path). But when the caller also supplies the
# deterministic evaluator's inputs, the recorded verdict is re-checked against
# evaluate_risk_policy and the write is refused on mismatch — so the public
# risk.evaluate -> risk.check_record flow is verifiable, not trust-me.
# ---------------------------------------------------------------------------


def _eval_policy(home: Path, version: str) -> str:
    policy = _env(home, "risk.policy_version_add", {
        "policy_key": "profile/default",
        "version": version,
        "limits_json": {"max_position_notional": 1000},
        "rules_json": [{
            "rule_id": "notional",
            "limit_class": "notional",
            "severity": "hard_block",
            "threshold": 1000,
        }],
        "source": "profile_fixture",
        "effective_from": "2026-05-28T00:00:00Z",
    })
    assert policy["ok"], policy
    return policy["data"]["id"]


def test_check_record_records_evaluator_consistent_verdict(home):
    policy_id = _eval_policy(home, "guard-consistent")
    verdict = _env(home, "risk.evaluate", {
        "policy_version_id": policy_id,
        "proposed_intent": {"proposed_shape": {"notional": 9999}},
    })
    assert verdict["ok"], verdict
    assert verdict["data"]["status"] == "fail"
    receipt = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": verdict["data"]["status"],
        "outcome": verdict["data"]["outcome"],
        "as_of": "2026-05-28T12:00:00Z",
        "proposed_intent_hash": "deadbeef",
        "rule_results": verdict["data"]["rule_results"],
        # Re-supplying the evaluator inputs activates the consistency guard.
        "proposed_intent": {"proposed_shape": {"notional": 9999}},
        "idempotency_key": "guarded-consistent",
    })
    assert receipt["ok"], receipt
    assert receipt["data"]["status"] == "fail"
    assert receipt["data"]["outcome"] == "hard_block"


def test_check_record_rejects_verdict_that_contradicts_the_evaluator(home):
    policy_id = _eval_policy(home, "guard-contradiction")
    # The evaluator would return fail/hard_block for this intent, but the caller
    # hand-asserts a clean pass while also supplying the contradicting inputs.
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "pass",
        "outcome": "pass",
        "as_of": "2026-05-28T12:00:00Z",
        "proposed_intent_hash": "deadbeef",
        "rule_results": [_valid_rule(rule_id="notional", reason_code="within_limit")],
        "proposed_intent": {"proposed_shape": {"notional": 9999}},
        "idempotency_key": "guarded-bad",
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "status"
    assert env["error"]["details"]["evaluated"]["status"] == "fail"
    assert env["error"]["details"]["recorded"]["status"] == "pass"


def test_check_record_legacy_caller_asserted_path_skips_guard(home):
    # No evaluator inputs (proposed_intent / proposed_intent_id) => the external
    # risk-layer's hand-built receipt is recorded as-is. This is the supported
    # backward-compatible path and must NOT require an evaluator round-trip.
    policy_id = _eval_policy(home, "guard-legacy")
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "pass",
        "outcome": "pass",
        "intended_action": "pretrade_audit",
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [_valid_rule(rule_id="notional", reason_code="within_limit")],
        "idempotency_key": "guarded-legacy",
    })
    assert env["ok"], env
    assert env["data"]["status"] == "pass"


# ---------------------------------------------------------------------------
# §9 acceptance gates — warning-waiver vs expired-waiver at the receipt layer
# (bead trade-trace-ur8w; autonomous-trader-substrate.md §9).
#
# RECEIPT-LAYER DISTINCTION: a warning waiver downgrades a warning to
# outcome="waived_warning" ONLY while the waiver is effective at the receipt's
# as_of. An EXPIRED waiver does NOT downgrade anything: the warning stays an
# active warning (outcome="warning"), and recording it as waived_warning while
# the waiver had already lapsed is the non-compliant case §3.3 forbids ("hard-
# block rules must not be silently waived"; warnings must not be silently
# downgraded by a lapsed waiver). The receipt itself does not enforce waiver
# expiry arithmetic — these fixtures pin the CALLER CONTRACT for how the two
# situations are recorded so reports can tell an honest warning-waiver from a
# masked expired one.
# ---------------------------------------------------------------------------

_WARNING_RULE = dict(
    rule_id="spread",
    reason_code="SPREAD_WARNING",
    severity="warning",
    observed_value={"spread": 0.08},
    threshold={"max_spread": 0.05},
    contributing_record_ids=["snap_1"],
    waiver_required=True,
)


def test_warning_waiver_receipt_downgrades_to_waived_warning(home):
    """An effective warning waiver: status=warn, outcome=waived_warning, with
    waiver provenance recorded."""

    policy_id = _risk_policy(home, "warning-waiver")
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "warn",
        "outcome": "waived_warning",
        "evidence_input_ids_json": ["snap_1"],
        "as_of": "2026-05-28T12:00:00Z",
        # Waiver is effective at as_of: provenance present, outcome downgraded.
        "waived_by": "risk-officer",
        "waiver_reason": "spread acceptable for this liquidity tier (waiver eff. through 2026-06-30)",
        "rule_results": [_valid_rule(**_WARNING_RULE)],
        "idempotency_key": "warning-waiver-1",
    })
    assert env["ok"], env
    assert env["data"]["status"] == "warn"
    assert env["data"]["outcome"] == "waived_warning"
    # The waiver actor/reason are stored on the receipt row but not echoed in the
    # response contract; the load-bearing receipt-layer signal is the outcome.


def test_expired_waiver_receipt_does_not_downgrade_the_warning(home):
    """An EXPIRED waiver must NOT be recorded as waived_warning.

    Same warning rule and same waiver provenance as the effective case, but the
    waiver had lapsed before the receipt's as_of. The honest receipt keeps the
    warning active: status=warn, outcome=warning (NOT waived_warning). This is
    the §9 expired-waiver gate and the receipt-layer distinction from
    test_warning_waiver_receipt_downgrades_to_waived_warning above.
    """

    policy_id = _risk_policy(home, "expired-waiver")
    env = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "warn",
        # Waiver lapsed before as_of => warning is NOT downgraded.
        "outcome": "warning",
        "evidence_input_ids_json": ["snap_1"],
        "as_of": "2026-07-15T12:00:00Z",
        # Provenance still carried for audit, but it does not waive anything now.
        "waived_by": "risk-officer",
        "waiver_reason": "prior spread waiver EXPIRED 2026-06-30; no longer effective at as_of",
        "rule_results": [_valid_rule(**_WARNING_RULE)],
        "idempotency_key": "expired-waiver-1",
    })
    assert env["ok"], env
    assert env["data"]["status"] == "warn"
    # The load-bearing distinction: an expired waiver yields an active warning.
    assert env["data"]["outcome"] == "warning"
    assert env["data"]["outcome"] != "waived_warning"


def test_warning_waiver_and_expired_waiver_receipts_are_distinguishable(home):
    """Both receipts carry identical waiver provenance + the same warning rule;
    only the outcome separates the effective waiver from the expired one, so a
    report can never confuse a real waiver for a masked expired one."""

    policy_id = _risk_policy(home, "waiver-vs-expired")
    effective = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "warn",
        "outcome": "waived_warning",
        "evidence_input_ids_json": ["snap_1"],
        "as_of": "2026-05-28T12:00:00Z",
        "waived_by": "risk-officer",
        "waiver_reason": "effective waiver",
        "rule_results": [_valid_rule(**_WARNING_RULE)],
        "idempotency_key": "vs-effective",
    })
    expired = _env(home, "risk.check_record", {
        "policy_version_id": policy_id,
        "status": "warn",
        "outcome": "warning",
        "evidence_input_ids_json": ["snap_1"],
        "as_of": "2026-07-15T12:00:00Z",
        "waived_by": "risk-officer",
        "waiver_reason": "expired waiver",
        "rule_results": [_valid_rule(**_WARNING_RULE)],
        "idempotency_key": "vs-expired",
    })
    assert effective["ok"] and expired["ok"]
    assert effective["data"]["outcome"] == "waived_warning"
    assert expired["data"]["outcome"] == "warning"
    assert effective["data"]["id"] != expired["data"]["id"]
    # Receipt hashes differ purely on the outcome field even though the rule,
    # instrument anchor, and waiver actor are identical.
    assert effective["data"]["receipt_hash"] != expired["data"]["receipt_hash"]
