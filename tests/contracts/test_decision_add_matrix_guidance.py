"""decision.add exposes its runtime matrix and actionable validation recovery."""

from __future__ import annotations

from trade_trace.mcp_server import mcp_call
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
