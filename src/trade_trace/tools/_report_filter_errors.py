"""Shared tool-layer ReportFilter error conversion helpers."""

from __future__ import annotations

from pydantic import ValidationError

from trade_trace.contracts.errors import ErrorCode
from trade_trace.reports._filter_support import (
    SUPPORTED_FILTER_FIELDS,
    UnsupportedFilterError,
)
from trade_trace.tools.errors import ToolError


def report_filter_validation_to_tool_error(exc: ValidationError) -> ToolError:
    """Translate ReportFilter Pydantic failures to the tool error envelope."""

    return ToolError(
        ErrorCode.VALIDATION_ERROR,
        f"ReportFilter validation failed: {exc.errors()}",
        details={"field": "filter", "validation_errors": exc.errors()},
    )


def unsupported_filter_to_tool_error(exc: UnsupportedFilterError) -> ToolError:
    """Translate UnsupportedFilterError to the tool error envelope."""

    return ToolError(
        ErrorCode.VALIDATION_ERROR,
        str(exc),
        details={
            "field": "filter",
            "report": exc.report,
            "unsupported_filter_paths": exc.paths,
            "supported_filter_paths": sorted(
                SUPPORTED_FILTER_FIELDS.get(exc.report, frozenset())
            ),
        },
    )


__all__ = [
    "report_filter_validation_to_tool_error",
    "unsupported_filter_to_tool_error",
]
