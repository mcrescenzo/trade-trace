"""Characterization tests for shared CLI/MCP schema validation policy."""

from __future__ import annotations

import pytest

from trade_trace.contracts.schema_validation import (
    CLI_NUMERIC_BOUNDS_ONLY,
    MCP_STDIO_FULL_SCHEMA,
    reportable_schema_validation_error,
)


_SCHEMA = {
    "type": "object",
    "properties": {
        "min_sample": {"type": "integer", "minimum": 1},
        "mode": {"type": "string", "enum": ["fast", "safe"]},
    },
    "required": ["min_sample", "mode"],
}


def test_cli_policy_reports_numeric_bound_failure():
    error = reportable_schema_validation_error(
        tool="report.calibration",
        instance={"min_sample": 0, "mode": "fast"},
        schema=_SCHEMA,
        policy=CLI_NUMERIC_BOUNDS_ONLY,
    )

    assert error is not None
    assert error.message == "Input validation error: 0 is less than the minimum of 1"
    assert error.details == {
        "tool": "report.calibration",
        "field": "min_sample",
        "validator": "minimum",
        "validator_value": 1,
    }


@pytest.mark.parametrize(
    "instance",
    [
        {"mode": "fast"},  # required
        {"min_sample": "1", "mode": "fast"},  # type
        {"min_sample": 1, "mode": "turbo"},  # enum
    ],
)
def test_cli_policy_ignores_handler_owned_failures(instance):
    assert reportable_schema_validation_error(
        tool="report.calibration",
        instance=instance,
        schema=_SCHEMA,
        policy=CLI_NUMERIC_BOUNDS_ONLY,
    ) is None


@pytest.mark.parametrize(
    ("instance", "validator"),
    [
        ({"mode": "fast"}, "required"),
        ({"min_sample": "1", "mode": "fast"}, "type"),
        ({"min_sample": 1, "mode": "turbo"}, "enum"),
        ({"min_sample": 0, "mode": "fast"}, "minimum"),
    ],
)
def test_mcp_stdio_policy_reports_full_schema_failures(instance, validator):
    error = reportable_schema_validation_error(
        tool="report.calibration",
        instance=instance,
        schema=_SCHEMA,
        policy=MCP_STDIO_FULL_SCHEMA,
    )

    assert error is not None
    assert error.message.startswith("Input validation error: ")
    assert error.details["tool"] == "report.calibration"
    assert error.details["validator"] == validator
