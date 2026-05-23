"""Shared helpers for the per-domain ledger submodules.

Extracted from the monolithic `tools/ledger.py` per bead trade-trace-ji9c.
This module owns the tiny utilities every domain handler needs:

- `_idempotency_key` / `_allow_no_idempotency`: caller-key plumbing.
- `_TAG_FORBIDDEN_CHARS` + `_store_tags`: decision-tag normalization +
  HTML/whitespace rejection (bead trade-trace-8u3s).

Anything domain-specific (forecast validators, scoring, etc.) lives
in its own submodule and imports from this one.
"""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.tools.errors import ToolError


def _idempotency_key(args: dict[str, Any]) -> str | None:
    """Extract the caller-supplied idempotency_key. Returns None for the
    `_allow_no_idempotency: true` opt-in path; EventWriter then enforces the
    at-least-once semantics."""

    return args.get("idempotency_key")


def _allow_no_idempotency(args: dict[str, Any]) -> bool:
    return bool(args.get("_allow_no_idempotency"))


_TAG_FORBIDDEN_CHARS = frozenset("<>")


def _store_tags(tags: Any) -> list[str]:
    """Normalize a tags argument into a sorted list of lowercased, trimmed,
    deduplicated strings per PRD §3.1 decision_tags.

    Per bead trade-trace-8u3s, the normalizer rejects:
    - tags that contain HTML-like angle brackets (`<` or `>`), so a
      payload such as `<script>alert(1)</script>` is refused at
      ingestion rather than persisted for later rendering.
    - empty / whitespace-only tags, which previously round-tripped as
      silent drops and masked obviously broken inputs.
    """

    if tags is None:
        return []
    if isinstance(tags, str):
        # Allow comma-separated CLI input.
        tags = [t.strip() for t in tags.split(",")]
    out = set()
    for t in tags:
        raw = str(t)
        if _TAG_FORBIDDEN_CHARS.intersection(raw):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "decision tag must not contain `<` or `>` characters",
                details={
                    "field": "tags",
                    "value": raw,
                    "reason": "html_like_content",
                },
            )
        normalized = raw.strip().lower()
        if not normalized:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "decision tag must not be empty or whitespace-only",
                details={
                    "field": "tags",
                    "value": raw,
                    "reason": "empty_tag",
                },
            )
        if len(normalized) > 64:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "decision tag exceeds 64-char cap",
                details={"field": "tags", "value": normalized},
            )
        out.add(normalized)
    return sorted(out)
