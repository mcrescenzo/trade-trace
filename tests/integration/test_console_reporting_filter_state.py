"""Filter URL-state contract tests per trade-trace-hayy.

The reporting product encodes the active filter in a single URL
query parameter `f=<base64url-json>`. These tests pin:

- round-trip (encode(decode(x)) == x; decode(encode(rf)) == rf),
- empty / omitted parameter resolves to the no-filter default,
- malformed URL state raises FilterStateError (typed) rather than
  silently falling back to no-filter,
- summarize_filter projects the canonical filter shape into the
  facet chip data the UI renders.
"""

from __future__ import annotations

import pytest

from trade_trace.console.reporting.filter_state import (
    FILTER_QUERY_PARAM,
    FilterStateError,
    decode_filter,
    encode_filter,
    summarize_filter,
)
from trade_trace.contracts.report_filter import ReportFilter


def test_filter_query_param_is_canonical_f() -> None:
    """The Console contract pins the parameter name to `f` so
    cross-dashboard URLs round-trip without conversion."""

    assert FILTER_QUERY_PARAM == "f"


def test_encode_empty_filter_is_compact() -> None:
    """An empty ReportFilter encodes to the base64url of `{}` so a
    no-filter URL doesn't carry hundreds of bytes."""

    encoded = encode_filter(ReportFilter())
    # base64url("{}") -> "e30" (length 3, no padding).
    assert encoded == "e30"


def test_decode_empty_string_returns_default_filter() -> None:
    assert decode_filter("") == ReportFilter()


def test_decode_none_returns_default_filter() -> None:
    assert decode_filter(None) == ReportFilter()


def test_round_trip_preserves_strategy_filter() -> None:
    rf = ReportFilter.model_validate({
        "strategy": {"strategy_id": "strat_test"},
    })
    encoded = encode_filter(rf)
    decoded = decode_filter(encoded)
    assert decoded == rf


def test_round_trip_preserves_strategy_none_sentinel() -> None:
    """The `__none__` sentinel (select-rows-where-strategy_id-IS-NULL)
    is a load-bearing string; the URL must preserve it verbatim."""

    rf = ReportFilter.model_validate({"strategy": {"strategy_id": "__none__"}})
    decoded = decode_filter(encode_filter(rf))
    assert decoded.strategy.strategy_id == "__none__"
    assert decoded.strategy_filter_mode() == "is_null"


def test_round_trip_preserves_array_fields() -> None:
    rf = ReportFilter.model_validate({
        "decision": {
            "decision_type": ["actual_enter", "paper_enter"],
            "tags_any": ["pre-earnings", "liquidity-ignored"],
        },
        "actors": {"agent_id": ["agent:trader"]},
    })
    decoded = decode_filter(encode_filter(rf))
    assert decoded == rf


def test_round_trip_preserves_time_window() -> None:
    rf = ReportFilter.model_validate({
        "time_window": {
            "decision_at_gte": "2026-01-01T00:00:00Z",
            "decision_at_lt": "2026-02-01T00:00:00Z",
        },
    })
    decoded = decode_filter(encode_filter(rf))
    assert decoded == rf


def test_decode_rejects_unknown_axis_with_validation_error() -> None:
    """An attacker crafting a URL with an unknown axis must NOT
    silently broaden the filter — `extra=\"forbid\"` raises and the
    decoder surfaces it as FilterStateError."""

    rf_with_unknown = {"strategy": {"strategy_id": "ok", "made_up_field": "boom"}}
    import base64
    import json

    raw = json.dumps(rf_with_unknown).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    with pytest.raises(FilterStateError) as excinfo:
        decode_filter(encoded)
    assert "validation" in str(excinfo.value).lower()
    assert "validation_errors" in excinfo.value.details


def test_decode_rejects_non_base64url_input() -> None:
    with pytest.raises(FilterStateError, match="base64url"):
        decode_filter("not_valid_base64!!!@#$")


def test_decode_rejects_non_object_payload() -> None:
    """A JSON array or string as the payload is structurally wrong;
    decode must reject it rather than coerce."""

    import base64

    encoded = base64.urlsafe_b64encode(b'["array_not_object"]').decode("ascii").rstrip("=")
    with pytest.raises(FilterStateError, match="object"):
        decode_filter(encoded)


def test_encode_rejects_non_validating_dict() -> None:
    with pytest.raises(FilterStateError, match="validate"):
        encode_filter({"made_up_axis": {"foo": "bar"}})


# -- summarize_filter ------------------------------------------------


def test_summarize_empty_filter_returns_no_facets() -> None:
    assert summarize_filter(ReportFilter()) == []


def test_summarize_active_facets_returns_one_entry_per_field() -> None:
    rf = ReportFilter.model_validate({
        "strategy": {"strategy_id": "strat_x"},
        "decision": {"decision_type": ["actual_enter"]},
    })
    facets = summarize_filter(rf)
    by_section = {(f["section"], f["field"]): f["value"] for f in facets}
    assert by_section[("strategy", "strategy_id")] == "strat_x"
    assert by_section[("decision", "decision_type")] == ["actual_enter"]
    # Empty sections must not surface.
    sections = {f["section"] for f in facets}
    assert "actors" not in sections
    assert "time_window" not in sections
