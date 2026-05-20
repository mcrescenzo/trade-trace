"""decision.add exposes its runtime matrix and actionable validation recovery."""

from __future__ import annotations

from trade_trace.mcp_server import mcp_call
from trade_trace.tools.decision_matrix import allowed_decision_types, decision_matrix_contract


def _mcp(initialized_home, tool: str, args: dict):
    payload = {**args, "home": str(initialized_home)}
    return mcp_call(tool, payload, actor_id="cli:test")


def test_decision_add_schema_exposes_matrix_enum_and_examples(initialized_home):
    env = _mcp(initialized_home, "tool.schema", {"tool": "decision.add"})

    assert env.ok, env
    schema = env.data["json_schema"]
    assert schema["properties"]["type"]["enum"] == allowed_decision_types()
    assert schema["x-decision-matrix"] == decision_matrix_contract()
    assert schema["x-decision-matrix"]["skip"]["required"] == ["instrument_id", "reason"]
    assert "quantity" in schema["x-decision-matrix"]["skip"]["forbidden"]
    examples = schema["x-decision-examples"]
    for decision_type in ("skip", "watch", "actual_enter", "actual_exit"):
        assert examples[decision_type]["type"] == decision_type


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
