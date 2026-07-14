"""decision.add exposes its runtime matrix and actionable validation recovery."""

from __future__ import annotations

from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path
from trade_trace.tools.decision_matrix import (
    allowed_decision_types,
    decision_matrix_contract,
    material_non_action_taxonomy,
    validate_material_non_action,
)


def _mcp(initialized_home, tool: str, args: dict):
    payload = {**args, "home": str(initialized_home)}
    return mcp_call(tool, payload, actor_id="cli:test")


def test_decision_add_schema_exposes_matrix_enum_and_examples(initialized_home):
    env = _mcp(initialized_home, "tool.schema", {"tool": "decision.add"})

    assert env.ok, env
    schema = env.data["json_schema"]
    assert schema["properties"]["type"]["enum"] == allowed_decision_types()
    assert schema["x-decision-matrix"] == decision_matrix_contract()
    assert schema["x-material-non-action-taxonomy"] == material_non_action_taxonomy()
    assert "defer" in schema["x-material-non-action-taxonomy"]["categories"]
    assert schema["x-decision-matrix"]["skip"]["required"] == ["instrument_id", "reason"]
    assert "quantity" in schema["x-decision-matrix"]["skip"]["forbidden"]
    # forecast_id is an OPTIONAL field on the non-trade decision types so a bot
    # that recorded a real forecast and then deliberately skipped/watched/held
    # can carry the linkage on the decision row (bead trade-trace-t9n5). It must
    # be optional (not required, not forbidden) for skip/watch/hold.
    for non_trade in ("skip", "watch", "hold"):
        matrix_row = schema["x-decision-matrix"][non_trade]
        assert "forecast_id" in matrix_row["optional"], non_trade
        assert "forecast_id" not in matrix_row["required"], non_trade
        assert "forecast_id" not in matrix_row["forbidden"], non_trade
    examples = schema["x-decision-examples"]
    for decision_type in ("skip", "watch", "actual_enter", "actual_exit"):
        assert examples[decision_type]["type"] == decision_type


def test_skip_decision_accepts_optional_forecast_id(initialized_home):
    """A forecasted-then-skipped market can carry forecast_id on the skip row
    (bead trade-trace-t9n5). forecast_id is optional on skip, so supplying it
    must not raise a forbidden-field validation error; the linkage persists."""

    venue = _mcp(initialized_home, "venue.add", {
        "name": "Skip Forecast PM", "kind": "prediction_market",
    })
    assert venue.ok is True
    instrument = _mcp(initialized_home, "instrument.add", {
        "venue_id": venue.data["id"],
        "asset_class": "prediction_market",
        "title": "Forecasted-then-skipped market",
    })
    assert instrument.ok is True
    thesis = _mcp(initialized_home, "thesis.add", {
        "instrument_id": instrument.data["id"], "side": "yes", "body": "...",
    })
    assert thesis.ok is True
    forecast = _mcp(initialized_home, "forecast.add", {
        "thesis_id": thesis.data["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.55},
            {"outcome_label": "no", "probability": 0.45},
        ],
    })
    assert forecast.ok is True

    env = _mcp(initialized_home, "decision.add", {
        "type": "skip",
        "instrument_id": instrument.data["id"],
        "reason": "Real forecast recorded, but insufficient edge after costs.",
        "forecast_id": forecast.data["id"],
        "idempotency_key": "00000000-0000-4000-8000-000000000131",
    })

    assert env.ok is True, env
    assert env.data["type"] == "skip"


def test_forbidden_field_error_includes_matrix_and_corrected_payload(initialized_home):
    env = _mcp(initialized_home, "decision.add", {
        "type": "skip",
        "instrument_id": "ins_example",
        "reason": "No edge after costs.",
        "quantity": 10,
        "idempotency_key": "00000000-0000-4000-8000-000000000101",
        "_dry_run": True,
    })

    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    details = env.error.details
    assert details["field"] == "quantity"
    assert details["violation"] == "forbidden_present"
    assert details["decision_type"] == "skip"
    assert details["required_fields"] == ["instrument_id", "reason"]
    assert "quantity" in details["forbidden_fields"]
    assert details["allowed_decision_types"] == allowed_decision_types()
    assert "quantity" not in details["corrected_payload_hint"]
    assert details["corrected_payload_hint"]["reason"] == "No edge after costs."
    assert "Remove 'quantity'" in details["recovery"]
    assert env.meta.dry_run is True


def test_unknown_decision_type_error_includes_allowed_types_and_matrix(initialized_home):
    env = _mcp(initialized_home, "decision.add", {
        "type": "mystery",
        "instrument_id": "ins_example",
        "idempotency_key": "00000000-0000-4000-8000-000000000102",
        "_dry_run": True,
    })

    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    details = env.error.details
    assert details["field"] == "type"
    assert details["allowed_decision_types"] == allowed_decision_types()
    assert details["decision_matrix"] == decision_matrix_contract()
    assert "Choose one" in details["recovery"]
    assert env.meta.dry_run is True


def test_material_non_action_metadata_validates_allowed_category_and_reason(initialized_home):
    validate_material_non_action("watch", {
        "type": "watch",
        "instrument_id": "ins_example",
        "reason": "Waiting for caller-supplied liquidity update.",
        "metadata_json": {"material_non_action": {"category": "watch", "materiality_reason": "liquidity"}},
    })


def test_material_non_action_requires_valid_reason_and_compatible_category(initialized_home):
    env = _mcp(initialized_home, "decision.add", {
        "type": "watch",
        "instrument_id": "ins_example",
        "reason": "Waiting for source refresh.",
        "metadata_json": {"material_non_action": {"category": "skip", "materiality_reason": "source_stale"}},
        "idempotency_key": "00000000-0000-4000-8000-000000000112",
        "_dry_run": True,
    })

    assert env.ok is False
    assert env.error.details["field"] == "metadata_json.material_non_action.category"
    assert env.error.details["allowed_decision_types_for_category"] == ["skip"]

    env = _mcp(initialized_home, "decision.add", {
        "type": "watch",
        "instrument_id": "ins_example",
        "reason": "Waiting for source refresh.",
        "metadata_json": {"material_non_action": {"category": "watch", "materiality_reason": "vibes"}},
        "idempotency_key": "00000000-0000-4000-8000-000000000113",
        "_dry_run": True,
    })

    assert env.ok is False
    assert env.error.details["field"] == "metadata_json.material_non_action.materiality_reason"


def test_defer_material_non_action_requires_review_by(initialized_home):
    env = _mcp(initialized_home, "decision.add", {
        "type": "watch",
        "instrument_id": "ins_example",
        "reason": "Need caller-supplied outcome before deciding.",
        "metadata_json": {"material_non_action": {"category": "defer", "materiality_reason": "waiting_for_resolution"}},
        "idempotency_key": "00000000-0000-4000-8000-000000000114",
        "_dry_run": True,
    })

    assert env.ok is False
    assert env.error.details["field"] == "review_by"


def test_defer_material_non_action_accepts_all_documented_decision_types(initialized_home):
    venue = _mcp(initialized_home, "venue.add", {
        "name": "Defer Validity PM",
        "kind": "prediction_market",
    })
    assert venue.ok is True
    instrument = _mcp(initialized_home, "instrument.add", {
        "venue_id": venue.data["id"],
        "asset_class": "prediction_market",
        "title": "Defer validity market",
    })
    assert instrument.ok is True

    for idx, decision_type in enumerate(["watch", "hold", "review"], start=1):
        env = _mcp(initialized_home, "decision.add", {
            "type": decision_type,
            "instrument_id": instrument.data["id"],
            "reason": f"Waiting for resolution checkpoint via {decision_type}.",
            "review_by": "2026-06-01T12:00:00Z",
            "metadata_json": {
                "material_non_action": {
                    "category": "defer",
                    "materiality_reason": "waiting_for_resolution",
                }
            },
            "idempotency_key": f"00000000-0000-4000-8000-00000000012{idx}",
            "_dry_run": True,
        })

        assert env.ok is True, (decision_type, env)
        assert env.data["type"] == decision_type
        assert env.data["review_by"] == "2026-06-01T12:00:00.000Z"


def test_declared_risk_fields_are_optional_on_entry_types_and_self_documenting(initialized_home):
    """declared_risk_amount/unit are accepted by the handler and feed
    report.risk R-multiples + report.opportunity edge thresholds, but were
    invisible on the advertised surface (AX-045): absent from x-decision-matrix
    optional lists, the JSON-schema properties, and the examples — so a bot
    following the schema could never discover the field. They must now surface
    as OPTIONAL on the entry/add decision types (additive; forbidden nowhere)."""

    env = _mcp(initialized_home, "tool.schema", {"tool": "decision.add"})
    assert env.ok, env
    schema = env.data["json_schema"]

    for entry_type in ("paper_enter", "actual_enter", "add"):
        row = schema["x-decision-matrix"][entry_type]
        for field in ("declared_risk_amount", "declared_risk_unit"):
            assert field in row["optional"], (entry_type, field)
            assert field not in row["required"], (entry_type, field)
            assert field not in row["forbidden"], (entry_type, field)

    # Surfaced in the advertised JSON-schema properties so a bot reading the
    # schema (not just the matrix) sees the field exists.
    assert "declared_risk_amount" in schema["properties"]
    assert "declared_risk_unit" in schema["properties"]

    # The copy-paste entry example now records risk.
    actual_enter_example = schema["x-decision-examples"]["actual_enter"]
    assert "declared_risk_amount" in actual_enter_example
    assert "declared_risk_unit" in actual_enter_example


def test_paper_enter_returns_already_exposed_advisory_on_fragmenting_same_side(initialized_home):
    """trade-trace-scx8: paper_enter ALWAYS opens an independent position; it
    does not increase an existing open paper position on the same
    instrument+side. The FIRST entry on a fresh market opens cleanly with no
    advisory. A SECOND same-side entry (the cross-run fragmentation hazard an
    autonomous feeder hits) still succeeds but now carries an advisory
    `already_exposed` caveat naming the existing open position, so the bot can
    choose to skip instead of silently fragmenting exposure."""

    venue = _mcp(initialized_home, "venue.add", {
        "name": "Already Exposed PM", "kind": "prediction_market",
    })
    assert venue.ok is True
    instrument = _mcp(initialized_home, "instrument.add", {
        "venue_id": venue.data["id"],
        "asset_class": "prediction_market",
        "title": "Already-exposed market",
    })
    assert instrument.ok is True
    thesis = _mcp(initialized_home, "thesis.add", {
        "instrument_id": instrument.data["id"], "side": "yes", "body": "...",
    })
    assert thesis.ok is True

    first = _mcp(initialized_home, "decision.add", {
        "type": "paper_enter",
        "instrument_id": instrument.data["id"],
        "thesis_id": thesis.data["id"],
        "side": "yes",
        "quantity": 100,
        "price": 0.54,
        "idempotency_key": "00000000-0000-4000-8000-000000000301",
    })
    assert first.ok is True, first
    # Fresh market: no prior open position, so no already_exposed advisory.
    # The risk-first advisory (trade-trace-yyegu) still fires because no
    # risk_check_receipt_id was supplied.
    first_advisory_codes = {a["code"] for a in first.data.get("advisories", [])}
    assert first_advisory_codes == {"missing_risk_check_receipt"}, first.data
    first_position_id = first.data["position_id"]

    # A different size + price + (default) run — would NOT trip the exact-replay
    # DUPLICATE_DECISIONS bucket, but DOES fragment same-side exposure.
    second = _mcp(initialized_home, "decision.add", {
        "type": "paper_enter",
        "instrument_id": instrument.data["id"],
        "thesis_id": thesis.data["id"],
        "side": "yes",
        "quantity": 20,
        "price": 0.37,
        "idempotency_key": "00000000-0000-4000-8000-000000000302",
    })
    assert second.ok is True, second
    advisories = second.data.get("advisories")
    assert advisories, second.data
    # Also carries the risk-first advisory (trade-trace-yyegu, no
    # risk_check_receipt_id supplied) alongside already_exposed.
    assert {a["code"] for a in advisories} == {
        "already_exposed", "missing_risk_check_receipt",
    }, advisories
    advisory = next(a for a in advisories if a["code"] == "already_exposed")
    assert advisory["severity"] == "advisory"
    assert advisory["instrument_id"] == instrument.data["id"]
    assert advisory["side"] == "yes"
    assert first_position_id in advisory["existing_open_position_ids"]
    # The advisory must NOT name the just-opened position as "existing".
    assert second.data["position_id"] not in advisory["existing_open_position_ids"]
    assert advisory["existing_open_position_count"] == 1
    assert "already_exposed" in advisory["message"]


def test_paper_enter_opposite_side_does_not_trigger_already_exposed(initialized_home):
    """An open YES position must not raise already_exposed for a NEW NO entry —
    the advisory is same-instrument+SAME-side only (opposite sides are a
    deliberate hedge/reversal, not fragmentation)."""

    venue = _mcp(initialized_home, "venue.add", {
        "name": "Opposite Side PM", "kind": "prediction_market",
    })
    assert venue.ok is True
    instrument = _mcp(initialized_home, "instrument.add", {
        "venue_id": venue.data["id"],
        "asset_class": "prediction_market",
        "title": "Opposite-side market",
    })
    assert instrument.ok is True
    thesis = _mcp(initialized_home, "thesis.add", {
        "instrument_id": instrument.data["id"], "side": "yes", "body": "...",
    })
    assert thesis.ok is True

    yes_entry = _mcp(initialized_home, "decision.add", {
        "type": "paper_enter",
        "instrument_id": instrument.data["id"],
        "thesis_id": thesis.data["id"],
        "side": "yes",
        "quantity": 100,
        "price": 0.54,
        "idempotency_key": "00000000-0000-4000-8000-000000000311",
    })
    assert yes_entry.ok is True, yes_entry

    no_entry = _mcp(initialized_home, "decision.add", {
        "type": "paper_enter",
        "instrument_id": instrument.data["id"],
        "thesis_id": thesis.data["id"],
        "side": "no",
        "quantity": 50,
        "price": 0.46,
        "idempotency_key": "00000000-0000-4000-8000-000000000312",
    })
    assert no_entry.ok is True, no_entry
    no_entry_advisory_codes = {a["code"] for a in no_entry.data.get("advisories", [])}
    assert "already_exposed" not in no_entry_advisory_codes, no_entry.data


def test_paper_enter_declared_risk_flows_to_position_initial_risk(initialized_home):
    """A paper_enter carrying declared_risk_amount populates the position's
    initial_risk_amount and clears the missing_risk_budget caveat that
    report.open_positions otherwise attaches (AX-045 — the field report.risk
    depends on is now reachable from decision.add)."""

    venue = _mcp(initialized_home, "venue.add", {
        "name": "Declared Risk PM", "kind": "prediction_market",
    })
    assert venue.ok is True
    instrument = _mcp(initialized_home, "instrument.add", {
        "venue_id": venue.data["id"],
        "asset_class": "prediction_market",
        "title": "Declared-risk market",
    })
    assert instrument.ok is True
    thesis = _mcp(initialized_home, "thesis.add", {
        "instrument_id": instrument.data["id"], "side": "yes", "body": "...",
    })
    assert thesis.ok is True

    env = _mcp(initialized_home, "decision.add", {
        "type": "paper_enter",
        "instrument_id": instrument.data["id"],
        "thesis_id": thesis.data["id"],
        "side": "yes",
        "quantity": 100,
        "price": 0.40,
        "declared_risk_amount": 40.0,
        "declared_risk_unit": "dollar",
        "idempotency_key": "00000000-0000-4000-8000-000000000201",
    })
    assert env.ok is True, env

    positions = _mcp(initialized_home, "report.open_positions", {
        "instrument_id": instrument.data["id"],
    })
    assert positions.ok is True, positions
    row = positions.data["open_positions"][0]
    assert row["initial_risk_amount"] == 40.0
    caveat_codes = {c["code"] for c in row.get("caveats", [])}
    assert "missing_risk_budget" not in caveat_codes


# -- risk_check_receipt_id / risk-first advisory (trade-trace-yyegu) -----


def _record_pass_receipt(initialized_home, instrument_id: str) -> str:
    """Run the public risk.evaluate -> risk.check_record loop and return the
    immutable receipt id a decision can link via risk_check_receipt_id.
    `instrument_id` anchors the receipt to an already-existing row so the
    write clears the FK-enforced audit-anchor check."""

    policy = _mcp(initialized_home, "risk.policy_version_add", {
        "policy_key": "pm-default", "version": "1",
        "rules_json": [], "source": "operator",
        "effective_from": "2026-05-28T00:00:00.000Z",
        "idempotency_key": "00000000-0000-4000-8000-000000000401",
    })
    assert policy.ok is True, policy
    receipt = _mcp(initialized_home, "risk.check_record", {
        "policy_version_id": policy.data["id"],
        "status": "pass", "outcome": "pass", "rule_results": [],
        "as_of": "2026-05-28T00:00:00.000Z",
        "instrument_id": instrument_id,
        "idempotency_key": "00000000-0000-4000-8000-000000000402",
    })
    assert receipt.ok is True, receipt
    return receipt.data["id"]


def test_decision_matrix_declares_risk_check_receipt_id_o_for_enter_types_x_elsewhere(initialized_home):
    """x-decision-matrix must stay truthful: O(ptional) on paper_enter/
    actual_enter, X(forbidden) on every other decision type."""

    env = _mcp(initialized_home, "tool.schema", {"tool": "decision.add"})
    assert env.ok, env
    matrix = env.data["json_schema"]["x-decision-matrix"]
    for entry_type in ("paper_enter", "actual_enter"):
        assert "risk_check_receipt_id" in matrix[entry_type]["optional"], entry_type
    for other_type in allowed_decision_types():
        if other_type in ("paper_enter", "actual_enter"):
            continue
        assert "risk_check_receipt_id" in matrix[other_type]["forbidden"], other_type


def test_paper_enter_risk_check_receipt_id_persists_and_fk_validates(initialized_home):
    """A linked risk_check_receipt_id persists on the decision row (echoed on
    the response) and clears the risk-first advisory; an unknown receipt id
    is rejected as a missing FK reference rather than silently accepted."""

    venue = _mcp(initialized_home, "venue.add", {
        "name": "Risk Receipt PM", "kind": "prediction_market",
    })
    assert venue.ok is True
    instrument = _mcp(initialized_home, "instrument.add", {
        "venue_id": venue.data["id"], "asset_class": "prediction_market",
        "title": "Risk-receipt market",
    })
    assert instrument.ok is True
    thesis = _mcp(initialized_home, "thesis.add", {
        "instrument_id": instrument.data["id"], "side": "yes", "body": "...",
    })
    assert thesis.ok is True
    receipt_id = _record_pass_receipt(initialized_home, instrument.data["id"])

    linked = _mcp(initialized_home, "decision.add", {
        "type": "paper_enter",
        "instrument_id": instrument.data["id"],
        "thesis_id": thesis.data["id"],
        "side": "yes", "quantity": 10, "price": 0.5,
        "risk_check_receipt_id": receipt_id,
        "idempotency_key": "00000000-0000-4000-8000-000000000403",
    })
    assert linked.ok is True, linked
    assert linked.data["risk_check_receipt_id"] == receipt_id
    linked_codes = {a["code"] for a in linked.data.get("advisories", [])}
    assert "missing_risk_check_receipt" not in linked_codes

    db = open_database(db_path(initialized_home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT risk_check_receipt_id FROM decisions WHERE id = ?",
            (linked.data["id"],),
        ).fetchone()
    finally:
        db.close()
    assert row[0] == receipt_id

    bogus = _mcp(initialized_home, "decision.add", {
        "type": "paper_enter",
        "instrument_id": instrument.data["id"],
        "thesis_id": thesis.data["id"],
        "side": "yes", "quantity": 10, "price": 0.5,
        "risk_check_receipt_id": "risk_check_receipts_does_not_exist",
        "idempotency_key": "00000000-0000-4000-8000-000000000404",
    })
    assert bogus.ok is False, bogus
    assert bogus.error.code.value == "VALIDATION_ERROR"
    missing = bogus.error.details["missing_refs"]
    assert any(m["field"] == "risk_check_receipt_id" for m in missing), missing


def test_actual_enter_absent_risk_check_receipt_id_carries_advisory(initialized_home):
    """decision.add(actual_enter) with no risk_check_receipt_id carries the
    non-blocking risk-first advisory; the entry still succeeds."""

    venue = _mcp(initialized_home, "venue.add", {
        "name": "Actual Enter Advisory PM", "kind": "prediction_market",
    })
    assert venue.ok is True
    instrument = _mcp(initialized_home, "instrument.add", {
        "venue_id": venue.data["id"], "asset_class": "prediction_market",
        "title": "Actual-enter advisory market",
    })
    assert instrument.ok is True
    thesis = _mcp(initialized_home, "thesis.add", {
        "instrument_id": instrument.data["id"], "side": "yes", "body": "...",
    })
    assert thesis.ok is True

    env = _mcp(initialized_home, "decision.add", {
        "type": "actual_enter",
        "instrument_id": instrument.data["id"],
        "thesis_id": thesis.data["id"],
        "side": "yes", "quantity": 10, "price": 0.5,
        "idempotency_key": "00000000-0000-4000-8000-000000000405",
    })
    assert env.ok is True, env
    advisories = env.data.get("advisories")
    assert advisories, env.data
    advisory = next(a for a in advisories if a["code"] == "missing_risk_check_receipt")
    assert advisory["severity"] == "advisory"
    assert "risk-first" in advisory["message"]


def test_risk_check_receipt_id_forbidden_on_skip(initialized_home):
    """risk_check_receipt_id is X(forbidden) outside paper_enter/actual_enter;
    supplying it on `skip` raises the standard forbidden-field VALIDATION_ERROR."""

    env = _mcp(initialized_home, "decision.add", {
        "type": "skip",
        "instrument_id": "ins_example",
        "reason": "No edge after costs.",
        "risk_check_receipt_id": "rcr_whatever",
        "idempotency_key": "00000000-0000-4000-8000-000000000406",
        "_dry_run": True,
    })

    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    details = env.error.details
    assert details["field"] == "risk_check_receipt_id"
    assert details["violation"] == "forbidden_present"
    assert details["decision_type"] == "skip"
