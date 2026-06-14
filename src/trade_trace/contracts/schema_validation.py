"""Shared transport schema-validation policy helpers.

The CLI and MCP stdio transports intentionally apply different portions of a
registered JSON Schema.  This module centralizes that policy without changing
transport-specific envelope/error handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import jsonschema


class SchemaValidationPolicy(Enum):
    """Transport-level schema-validation policies."""

    CLI_NUMERIC_BOUNDS_ONLY = "cli_numeric_bounds_only"
    MCP_STDIO_FULL_SCHEMA = "mcp_stdio_full_schema"


CLI_NUMERIC_BOUNDS_ONLY = SchemaValidationPolicy.CLI_NUMERIC_BOUNDS_ONLY
MCP_STDIO_FULL_SCHEMA = SchemaValidationPolicy.MCP_STDIO_FULL_SCHEMA

_NUMERIC_BOUND_VALIDATORS = frozenset({
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "pattern",
})


@dataclass(frozen=True)
class SchemaValidationError:
    """Normalized validation failure payload consumed by transports."""

    message: str
    details: dict[str, Any]


def reportable_schema_validation_error(
    *,
    tool: str,
    instance: Any,
    schema: dict[str, Any],
    policy: SchemaValidationPolicy,
    validator: Any | None = None,
) -> SchemaValidationError | None:
    """Return a normalized reportable schema error for ``policy`` or ``None``.

    ``CLI_NUMERIC_BOUNDS_ONLY`` keeps handler-owned friendly errors for
    required/type/enum failures by ignoring non numeric-bound validators;
    ``MCP_STDIO_FULL_SCHEMA`` reports every schema validation failure at the
    stdio boundary.

    When ``validator`` is supplied it must be a pre-built jsonschema validator
    instance for ``schema`` (e.g. ``ToolRegistration.compiled_validator``); the
    pre-built validator is reused so the hot dispatch path skips the per-call
    draft detection, schema re-validation, and validator instantiation that
    ``jsonschema.validate`` performs (see trade-trace-u5l3). The reported error
    is selected with ``best_match`` exactly as ``jsonschema.validate`` does, so
    the validation error contract is identical whether or not a pre-built
    validator is passed.
    """

    try:
        if validator is not None:
            error = jsonschema.exceptions.best_match(validator.iter_errors(instance))
            if error is not None:
                raise error
        else:
            jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as exc:
        if (
            policy is CLI_NUMERIC_BOUNDS_ONLY
            and exc.validator not in _NUMERIC_BOUND_VALIDATORS
        ):
            return None
        return SchemaValidationError(
            message=f"Input validation error: {exc.message}",
            details={
                "tool": tool,
                "field": ".".join(str(part) for part in exc.path) or None,
                "validator": exc.validator,
                "validator_value": exc.validator_value,
            },
        )
    return None
