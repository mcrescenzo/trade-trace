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
) -> SchemaValidationError | None:
    """Return a normalized reportable schema error for ``policy`` or ``None``.

    The underlying jsonschema.validate call is deliberately unchanged from the
    former transport-local implementations.  ``CLI_NUMERIC_BOUNDS_ONLY`` keeps
    handler-owned friendly errors for required/type/enum failures by ignoring
    non numeric-bound validators; ``MCP_STDIO_FULL_SCHEMA`` reports every schema
    validation failure at the stdio boundary.
    """

    try:
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
