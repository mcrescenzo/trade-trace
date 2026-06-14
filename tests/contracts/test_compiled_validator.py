"""Tests for the pre-built per-registration validator (trade-trace-u5l3).

``ToolRegistration`` builds a ``compiled_validator`` once at registration time
so the MCP dispatch hot path no longer re-detects the draft, re-checks the
schema, and re-instantiates a validator on every call. These tests assert the
validator is built and that routing ``reportable_schema_validation_error``
through the pre-built validator yields the identical error contract as the
``jsonschema.validate``-backed schema path — including ``best_match`` selection
for combinator (``anyOf``) schemas.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp import types

import trade_trace.contracts.schema_validation as schema_validation_mod
from trade_trace.contracts.schema_validation import (
    CLI_NUMERIC_BOUNDS_ONLY,
    MCP_STDIO_FULL_SCHEMA,
    reportable_schema_validation_error,
)
from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.core import default_registry
from trade_trace.mcp_server import _build_stdio_server

_SCHEMA = {
    "type": "object",
    "properties": {
        "min_sample": {"type": "integer", "minimum": 1},
        "mode": {"type": "string", "enum": ["fast", "safe"]},
    },
    "required": ["min_sample", "mode"],
}


def _noop_handler(args, ctx):  # pragma: no cover - never invoked
    return {}


def test_register_builds_compiled_validator() -> None:
    registry = ToolRegistry()
    registry.register(
        "report.calibration",
        _noop_handler,
        json_schema=_SCHEMA,
    )
    reg = registry.get("report.calibration")
    assert reg.compiled_validator is not None
    # The pre-built validator must already match its own schema.
    assert reg.compiled_validator.schema is reg.json_schema


def test_register_without_schema_leaves_validator_none() -> None:
    registry = ToolRegistry()
    registry.register("report.noschema", _noop_handler)
    assert registry.get("report.noschema").compiled_validator is None


def test_alias_rebuilds_compiled_validator() -> None:
    registry = ToolRegistry()
    registry.register("report.calibration", _noop_handler, json_schema=_SCHEMA)
    registry.alias("calibration.report", "report.calibration")
    assert registry.get("calibration.report").compiled_validator is not None


def test_mark_preserves_compiled_validator() -> None:
    registry = ToolRegistry()
    registry.register("report.calibration", _noop_handler, json_schema=_SCHEMA)
    registry.mark("report.calibration", catalog_visibility="experimental")
    reg = registry.get("report.calibration")
    assert reg.compiled_validator is not None
    assert reg.compiled_validator.schema is reg.json_schema


def test_default_registry_validators_built_for_every_schema() -> None:
    registry = default_registry()
    for name in registry.names():
        reg = registry.get(name)
        if reg.json_schema is not None:
            assert reg.compiled_validator is not None, name


@pytest.mark.parametrize(
    ("instance", "validator_name"),
    [
        ({"mode": "fast"}, "required"),
        ({"min_sample": "1", "mode": "fast"}, "type"),
        ({"min_sample": 1, "mode": "turbo"}, "enum"),
        ({"min_sample": 0, "mode": "fast"}, "minimum"),
    ],
)
def test_prebuilt_validator_matches_schema_path_mcp(instance, validator_name) -> None:
    registry = ToolRegistry()
    registry.register("report.calibration", _noop_handler, json_schema=_SCHEMA)
    prebuilt = registry.get("report.calibration").compiled_validator

    via_schema = reportable_schema_validation_error(
        tool="report.calibration",
        instance=instance,
        schema=_SCHEMA,
        policy=MCP_STDIO_FULL_SCHEMA,
    )
    via_validator = reportable_schema_validation_error(
        tool="report.calibration",
        instance=instance,
        schema=_SCHEMA,
        policy=MCP_STDIO_FULL_SCHEMA,
        validator=prebuilt,
    )

    assert via_schema is not None
    assert via_validator is not None
    assert via_validator == via_schema
    assert via_validator.details["validator"] == validator_name


def test_prebuilt_validator_matches_schema_path_cli_bounds_only() -> None:
    registry = ToolRegistry()
    registry.register("report.calibration", _noop_handler, json_schema=_SCHEMA)
    prebuilt = registry.get("report.calibration").compiled_validator

    # A handler-owned (non numeric-bound) failure is suppressed identically.
    handler_owned = {"mode": "fast"}
    assert reportable_schema_validation_error(
        tool="report.calibration",
        instance=handler_owned,
        schema=_SCHEMA,
        policy=CLI_NUMERIC_BOUNDS_ONLY,
        validator=prebuilt,
    ) is None

    # A numeric-bound failure is reported identically.
    bound = {"min_sample": 0, "mode": "fast"}
    via_validator = reportable_schema_validation_error(
        tool="report.calibration",
        instance=bound,
        schema=_SCHEMA,
        policy=CLI_NUMERIC_BOUNDS_ONLY,
        validator=prebuilt,
    )
    assert via_validator is not None
    assert via_validator.details["validator"] == "minimum"


def test_prebuilt_validator_best_match_on_anyof_combinator() -> None:
    """The combinator (``anyOf``) error contract must be identical, which
    requires ``best_match`` selection rather than the first ``iter_errors``
    result (``Validator.validate`` would diverge here)."""

    registry = default_registry()
    reg = registry.get("forecast.add")
    canonical = reg.json_schema
    assert canonical is not None
    assert reg.compiled_validator is not None

    missing_forecast_parent_args = {
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.5},
            {"outcome_label": "no", "probability": 0.5},
        ],
        "idempotency_key": "compiled-validator-anyof",
    }

    via_schema = reportable_schema_validation_error(
        tool="forecast.add",
        instance=missing_forecast_parent_args,
        schema=canonical,
        policy=MCP_STDIO_FULL_SCHEMA,
    )
    via_validator = reportable_schema_validation_error(
        tool="forecast.add",
        instance=missing_forecast_parent_args,
        schema=canonical,
        policy=MCP_STDIO_FULL_SCHEMA,
        validator=reg.compiled_validator,
    )

    assert via_schema is not None
    assert via_validator is not None
    assert via_validator == via_schema
    assert via_validator.details["validator"] == "anyOf"


def _stdio_call_result(server: Any, name: str, arguments: Any) -> Any:
    request = types.CallToolRequest.model_construct(
        params=types.CallToolRequestParams.model_construct(name=name, arguments=arguments)
    )
    return asyncio.run(server.request_handlers[types.CallToolRequest](request))


class _SpyValidator:
    """Delegating wrapper around a pre-built jsonschema validator that records
    every ``iter_errors`` call so a test can prove the dispatch path reused the
    compiled validator instead of ``jsonschema.validate``. ``Draft*Validator``
    instances expose ``iter_errors`` as a read-only attribute, so the dispatch
    wiring is spied by substituting this proxy for ``compiled_validator`` rather
    than monkeypatching a method on the validator instance directly.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.iter_errors_calls: list[Any] = []

    @property
    def schema(self) -> Any:
        return self._inner.schema

    def iter_errors(self, instance: Any) -> Any:
        self.iter_errors_calls.append(instance)
        return self._inner.iter_errors(instance)


def _install_spy_validator(registration: Any) -> _SpyValidator:
    assert registration.compiled_validator is not None
    spy = _SpyValidator(registration.compiled_validator)
    registration.compiled_validator = spy
    return spy


def _forbid_per_call_validate(monkeypatch) -> None:
    def _no_per_call_validate(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            "MCP dispatch must reuse the pre-built validator, not call "
            "jsonschema.validate per dispatch (trade-trace-u5l3)"
        )

    monkeypatch.setattr(schema_validation_mod.jsonschema, "validate", _no_per_call_validate)


def test_mcp_dispatch_uses_prebuilt_validator_not_jsonschema_validate(monkeypatch) -> None:
    """The production MCP dispatch hot path must route schema validation through
    the pre-built ``registration.compiled_validator`` (its ``iter_errors``) and
    must NOT incur the per-call ``jsonschema.validate`` overhead the parent bead
    (trade-trace-u5l3) set out to eliminate.
    """

    registry = ToolRegistry()
    registry.register(
        "boundary.echo",
        _noop_handler,
        json_schema=_SCHEMA,
    )
    registry.validate()

    _forbid_per_call_validate(monkeypatch)
    spy = _install_spy_validator(registry.get("boundary.echo"))

    # A schema-violating instance (missing required fields) must still produce a
    # VALIDATION_ERROR envelope via the pre-built validator.
    server = _build_stdio_server(registry)
    result = _stdio_call_result(server, "boundary.echo", {})
    structured = result.root.structuredContent
    assert structured is not None
    assert structured["ok"] is False
    assert structured["error"]["code"] == "VALIDATION_ERROR"
    assert structured["error"]["details"]["validator"] == "required"

    # Proof the pre-built validator was the path: iter_errors saw the instance.
    assert spy.iter_errors_calls == [{}]


def test_mcp_dispatch_valid_args_skip_jsonschema_validate(monkeypatch) -> None:
    """A schema-valid dispatch must also avoid jsonschema.validate and pass the
    pre-built validator through (iter_errors returns no errors)."""

    registry = ToolRegistry()
    registry.register(
        "boundary.echo",
        _noop_handler,
        json_schema=_SCHEMA,
    )
    registry.validate()

    _forbid_per_call_validate(monkeypatch)
    spy = _install_spy_validator(registry.get("boundary.echo"))

    server = _build_stdio_server(registry)
    valid_args = {"min_sample": 3, "mode": "fast"}
    result = _stdio_call_result(server, "boundary.echo", valid_args)
    structured = result.root.structuredContent
    assert structured is not None
    assert structured["ok"] is True
    assert spy.iter_errors_calls == [valid_args]
