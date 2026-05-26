from __future__ import annotations

import pytest

from trade_trace.contracts.schema_validation import (
    MCP_STDIO_FULL_SCHEMA,
    reportable_schema_validation_error,
)
from trade_trace.core import default_registry
from trade_trace.mcp_server import TOP_LEVEL_JSON_SCHEMA_COMBINATORS, mcp_tool_specs


def test_mcp_advertised_schemas_have_no_top_level_combinators() -> None:
    specs = mcp_tool_specs()
    assert specs

    offenders = {
        spec["name"]: sorted(set(spec["input_schema"]) & set(TOP_LEVEL_JSON_SCHEMA_COMBINATORS))
        for spec in specs
        if set(spec["input_schema"]) & set(TOP_LEVEL_JSON_SCHEMA_COMBINATORS)
    }
    assert offenders == {}


def test_forecast_add_advertises_claude_compatible_schema_but_keeps_canonical_runtime_schema() -> None:
    registry = default_registry()
    canonical = registry.get("forecast.add").json_schema
    assert canonical is not None
    assert "anyOf" in canonical

    advertised = next(spec["input_schema"] for spec in mcp_tool_specs(registry) if spec["name"] == "forecast.add")
    assert advertised["type"] == "object"
    assert "anyOf" not in advertised
    assert advertised["properties"] == canonical["properties"]
    assert advertised["required"] == canonical["required"]
    assert "top-level combinators omitted" in advertised["x-trade-trace-mcp-schema-note"]


@pytest.mark.parametrize("tool_name", ["forecast.add"])
def test_runtime_validation_still_uses_canonical_top_level_combinators(tool_name: str) -> None:
    registry = default_registry()
    canonical = registry.get(tool_name).json_schema
    assert canonical is not None

    missing_forecast_parent_args = {
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.5},
            {"outcome_label": "no", "probability": 0.5},
        ],
        "idempotency_key": "schema-compat-runtime-validation",
    }
    validation_error = reportable_schema_validation_error(
        tool=tool_name,
        instance=missing_forecast_parent_args,
        schema=canonical,
        policy=MCP_STDIO_FULL_SCHEMA,
    )
    assert validation_error is not None
    assert validation_error.details["validator"] == "anyOf"
