"""Global ReportFilter URL-state encoder/decoder per trade-trace-hayy.

The reporting product overhaul (EPIC trade-trace-3o4a) encodes the
active filter in a single URL query parameter `f=<base64url-json>`
(per `docs/architecture/reporting-product.md` §5 contract):

- Empty / omitted `f` means "no filter" (the default
  `ReportFilter()`).
- Non-empty `f` decodes to canonical `ReportFilter` JSON.
- Round-trip is lossless: `encode(decode(f)) == f` for any
  valid string.

The decode path validates against the live `ReportFilter` schema
(`extra="forbid"`), so a URL crafted with an unknown axis raises a
typed `FilterStateError` instead of silently broadening results.

This module is the single source of truth for the URL contract. The
filter UI (the form / facet macros / JS) consumes these helpers; it
MUST NOT re-implement encode/decode logic.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from pydantic import ValidationError

from trade_trace.contracts.report_filter import ReportFilter

_BASE64URL_ALPHABET_RE = re.compile(r"^[A-Za-z0-9_\-]*={0,2}$")
"""Strict base64url alphabet (RFC 4648 §5) plus optional trailing
padding. Used to reject malformed URL state before
`urlsafe_b64decode` falls through to garbage bytes."""

FILTER_QUERY_PARAM = "f"
"""The single query parameter the Console uses for filter URL state.
Reporting links MUST use exactly this key so cross-dashboard URLs
round-trip without conversion."""


class FilterStateError(ValueError):
    """Raised when the filter URL state is malformed or fails
    `ReportFilter` validation. The Console renders this as a typed
    user-facing error rather than silently falling back to no-filter."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


def encode_filter(filter_obj: ReportFilter | dict[str, Any]) -> str:
    """Encode a `ReportFilter` (or its dict form) into the
    base64url-JSON shape used as the `f=` query parameter value.

    The encoder omits unset sub-filter fields via Pydantic's
    `exclude_defaults=True` so the URL stays compact for the common
    case (one or two facets active); a fully empty filter encodes to
    a base64url representation of `{}`.

    Padding is stripped (per RFC 4648 §5 base64url-no-pad) so the
    URL doesn't carry `=` characters.
    """

    if isinstance(filter_obj, ReportFilter):
        # Validate via model so the encoder rejects nonsense before
        # it lands in a URL.
        rf = filter_obj
    else:
        try:
            rf = ReportFilter.model_validate(filter_obj)
        except ValidationError as exc:
            raise FilterStateError(
                "filter does not validate as ReportFilter",
                details={"validation_errors": exc.errors()},
            ) from exc

    # `exclude_defaults=True` strips every sub-filter field whose
    # value matches the schema default (empty list, None). The result
    # is a minimal JSON payload — empty `{}` for ReportFilter() — so
    # the URL doesn't bloat with every default-empty array.
    payload = rf.model_dump(mode="json", exclude_defaults=True)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_filter(value: str | None) -> ReportFilter:
    """Decode a `f=<base64url-json>` query parameter into a
    `ReportFilter`. `None` or `""` returns the default no-filter
    instance.

    Raises `FilterStateError` on:

    - non-base64url input,
    - JSON that does not decode to an object,
    - validation failures against the `ReportFilter` schema
      (unknown axes, wrong types, etc.).
    """

    if value is None or value == "":
        return ReportFilter()

    if not _BASE64URL_ALPHABET_RE.match(value):
        raise FilterStateError(
            "filter parameter is not valid base64url",
            details={"raw": value},
        )
    padding = "=" * (-len(value) % 4)
    try:
        raw = base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise FilterStateError(
            f"filter parameter is not valid base64url: {exc}",
            details={"raw": value},
        ) from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FilterStateError(
            f"filter parameter is not valid JSON: {exc}",
            details={"raw": value},
        ) from exc

    if not isinstance(payload, dict):
        raise FilterStateError(
            f"filter parameter must decode to a JSON object; got {type(payload).__name__}",
            details={"raw_type": type(payload).__name__},
        )

    try:
        return ReportFilter.model_validate(payload)
    except ValidationError as exc:
        raise FilterStateError(
            "filter parameter failed ReportFilter validation",
            details={"validation_errors": exc.errors()},
        ) from exc


def summarize_filter(filter_obj: ReportFilter | dict[str, Any]) -> list[dict[str, Any]]:
    """Return a human-readable list of active filter facets for the
    chips/breadcrumb UI. Each entry is `{"section": str, "field": str,
    "value": Any}` for one applied facet; an empty list means no facets
    are active.

    The summary is derived from `ReportFilter.model_dump(exclude_defaults=True)`
    — the same shape the encoder uses — so the UI never disagrees with
    the URL. Sub-filter sections with no active fields are skipped.
    """

    if isinstance(filter_obj, ReportFilter):
        rf = filter_obj
    else:
        rf = ReportFilter.model_validate(filter_obj)

    facets: list[dict[str, Any]] = []
    payload = rf.model_dump(mode="json", exclude_defaults=True)
    for section, fields in payload.items():
        if not isinstance(fields, dict):
            # Top-level scalar (none today, but keep the shape robust).
            facets.append({"section": section, "field": "", "value": fields})
            continue
        for field, value in fields.items():
            # Skip empty arrays / None (defaults that snuck through
            # because Pydantic considers an explicitly-set empty array
            # non-default).
            if value is None or value == []:
                continue
            facets.append({"section": section, "field": field, "value": value})
    return facets


__all__ = [
    "FILTER_QUERY_PARAM",
    "FilterStateError",
    "decode_filter",
    "encode_filter",
    "summarize_filter",
]
