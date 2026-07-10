from __future__ import annotations

import sqlite3

import pytest

from trade_trace.contracts.schema_validation import (
    MCP_STDIO_FULL_SCHEMA,
    reportable_schema_validation_error,
)
from trade_trace.core import default_registry
from trade_trace.mcp_server import TOP_LEVEL_JSON_SCHEMA_COMBINATORS, mcp_call, mcp_tool_specs
from trade_trace.storage.paths import db_path


@pytest.mark.parametrize("include_experimental", [False, True])
def test_mcp_advertised_schemas_have_no_top_level_combinators(
    include_experimental: bool,
) -> None:
    specs = mcp_tool_specs(include_experimental=include_experimental)
    assert specs

    offenders = {
        spec["name"]: sorted(set(spec["input_schema"]) & set(TOP_LEVEL_JSON_SCHEMA_COMBINATORS))
        for spec in specs
        if set(spec["input_schema"]) & set(TOP_LEVEL_JSON_SCHEMA_COMBINATORS)
    }
    assert offenders == {}


@pytest.mark.parametrize(
    ("tool_name", "include_experimental"),
    [("market.bind", False), ("snapshot.fetch", True)],
)
def test_phase5_retryable_catalog_tools_advertise_idempotency_key(
    tool_name: str, include_experimental: bool
) -> None:
    registry = default_registry()
    advertised = next(
        spec["input_schema"]
        for spec in mcp_tool_specs(registry, include_experimental=include_experimental)
        if spec["name"] == tool_name
    )

    assert advertised["type"] == "object"
    assert "idempotency_key" in advertised.get("properties", {})
    assert advertised["properties"]["idempotency_key"]["type"] == "string"
    assert not (set(advertised) & set(TOP_LEVEL_JSON_SCHEMA_COMBINATORS))


def test_market_bind_preserves_distinct_caller_idempotency_keys_for_shared_market(tmp_path) -> None:
    home = tmp_path / "home"
    init = mcp_call("journal.init", {"home": str(home)}, actor_id="agent:init")
    assert init.ok, init

    base_args = {
        "home": str(home),
        "source": "polymarket",
        "external_id": "phase5-shared-market",
        "title": "Phase 5 shared market",
        "question": "Will Phase 5 idempotency remain uncollided?",
        "state": "open",
        "mechanism": "clob",
        "bound_via": "manual",
    }
    first = mcp_call(
        "market.bind",
        {**base_args, "idempotency_key": "phase5-market-bind-actor-a"},
        actor_id="agent:phase5-a",
    )
    second = mcp_call(
        "market.bind",
        {**base_args, "idempotency_key": "phase5-market-bind-actor-b"},
        actor_id="agent:phase5-b",
    )
    assert first.ok, first
    assert second.ok, second
    first_data = first.model_dump(mode="json", exclude_none=True)["data"]
    second_data = second.model_dump(mode="json", exclude_none=True)["data"]
    assert first_data["id"] == second_data["id"]
    assert second_data["already_bound"] is True

    with sqlite3.connect(db_path(home)) as conn:
        rows = conn.execute(
            """
            SELECT actor_id, idempotency_key
            FROM events
            WHERE event_type = 'market.bound'
            ORDER BY id ASC
            """
        ).fetchall()

    assert rows == [
        ("agent:phase5-a", "phase5-market-bind-actor-a"),
        ("agent:phase5-b", "phase5-market-bind-actor-b"),
    ]
    assert not any(str(key).startswith("auto:") for _actor, key in rows)


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
