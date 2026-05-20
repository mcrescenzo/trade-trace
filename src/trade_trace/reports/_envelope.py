"""Small private helpers for report result envelopes.

These helpers deliberately do not define a public report framework. They only
centralize the repeated insertion-order-sensitive data-envelope shell used by
report functions.
"""

from __future__ import annotations

from typing import Any


def standard_report_result(
    *,
    summary: dict[str, Any],
    groups: list[dict[str, Any]],
    truncated: bool = False,
    next_cursor: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the standard report data envelope preserving key order.

    The canonical order is summary, groups, any report-specific top-level
    fields, then pagination metadata. Passing ``extra`` lets reports such as
    calibration keep fields like ``bin_policy`` in their existing position.
    """

    result: dict[str, Any] = {
        "summary": summary,
        "groups": groups,
    }
    if extra:
        result.update(extra)
    result["truncated"] = truncated
    result["next_cursor"] = next_cursor
    return result
