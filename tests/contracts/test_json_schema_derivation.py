from __future__ import annotations

from jsonschema.validators import Draft202012Validator  # type: ignore[import-untyped]

from trade_trace.contracts.json_schema_derive import derive_schema
from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.core import build_registry, dispatch


def _noop(args, ctx):  # noqa: ANN001
    return {"ok": True}


def _assert_valid_json_schema(schema: dict) -> None:
    Draft202012Validator.check_schema(schema)


def test_per_primitive_derivation_str_int_float_bool() -> None:
    schema = derive_schema({"s": "x", "i": 1, "f": 1.25, "b": True})

    assert schema["properties"]["s"] == {"type": "string"}
    assert schema["properties"]["i"] == {"type": "integer"}
    assert schema["properties"]["f"] == {"type": "number"}
    assert schema["properties"]["b"] == {"type": "boolean"}
    assert schema["required"] == ["s", "i", "f", "b"]
    _assert_valid_json_schema(schema)


def test_nested_object_handling_without_nested_required() -> None:
    schema = derive_schema({"outer": {"name": "alice", "count": 2}})

    outer = schema["properties"]["outer"]
    assert outer["type"] == "object"
    assert outer["properties"] == {
        "name": {"type": "string"},
        "count": {"type": "integer"},
    }
    assert "required" not in outer
    assert schema["required"] == ["outer"]
    _assert_valid_json_schema(schema)


def test_list_of_objects_derivation() -> None:
    schema = derive_schema({"items": [{"label": "yes", "probability": 0.7}]})

    items = schema["properties"]["items"]
    assert items["type"] == "array"
    assert items["items"]["type"] == "object"
    assert items["items"]["properties"]["label"] == {"type": "string"}
    assert items["items"]["properties"]["probability"] == {"type": "number"}
    _assert_valid_json_schema(schema)


def test_tools_without_example_minimal_leave_json_schema_null() -> None:
    registry = ToolRegistry()
    registry.register("example.no_schema", _noop)

    assert registry.get("example.no_schema").example_minimal is None
    assert registry.get("example.no_schema").json_schema is None


def test_explicit_json_schema_override_wins() -> None:
    override = {"type": "object", "properties": {"explicit": {"type": "boolean"}}}
    registry = ToolRegistry()
    registry.register(
        "example.override",
        _noop,
        example_minimal={"derived": "nope"},
        json_schema=override,
    )

    reg_schema = registry.get("example.override").json_schema
    assert reg_schema is override
    assert reg_schema is not None
    assert "derived" not in reg_schema["properties"]
    _assert_valid_json_schema(reg_schema)


def test_report_filter_typed_filter_args_land_canonical_schema() -> None:
    schema = derive_schema({"filter": {"strategy": {"strategy_id": "__none__"}}})

    assert schema["properties"]["filter"] == ReportFilter.model_json_schema(mode="validation")
    assert "$defs" in schema["properties"]["filter"]
    assert schema["required"] == ["filter"]
    _assert_valid_json_schema(schema)


def test_build_registry_derives_schema_for_every_tool_with_example_minimal() -> None:
    registry = build_registry()
    missing = [reg.name for reg in registry.by_name.values() if reg.example_minimal and reg.json_schema is None]

    assert missing == []
    for reg in registry.by_name.values():
        if reg.example_minimal is not None:
            assert reg.json_schema is not None
            _assert_valid_json_schema(reg.json_schema)


def test_tool_schema_envelope_echoes_valid_json_schema() -> None:
    registry = build_registry()
    env = dispatch(
        "tool.schema",
        {"tool": "forecast.add"},
        actor_id="agent:schema-test",
        registry=registry,
    )
    dumped = env.model_dump(mode="json")

    schema = dumped["data"]["json_schema"]
    assert schema == registry.get("forecast.add").json_schema
    _assert_valid_json_schema(schema)


def test_tool_schema_self_schema_advertises_optional_tool_argument() -> None:
    registry = build_registry()
    schema = registry.get("tool.schema").json_schema

    assert schema is not None
    assert schema["type"] == "object"
    assert schema["required"] == []
    assert schema["properties"]["tool"]["type"] == "string"
    _assert_valid_json_schema(schema)

    env = dispatch(
        "tool.schema",
        {"tool": "tool.schema"},
        actor_id="agent:schema-test",
        registry=registry,
    )
    dumped = env.model_dump(mode="json")
    assert dumped["data"]["json_schema"] == schema


def test_transport_control_keys_are_optional_not_required() -> None:
    schema = derive_schema({"name": "x", "_dry_run": True, "_confirm": False})

    assert schema["required"] == ["name"]
    assert schema["properties"]["_dry_run"] == {"type": "boolean"}
    assert schema["properties"]["_confirm"] == {"type": "boolean"}
    _assert_valid_json_schema(schema)
