"""ReportFilter Pydantic schema + report.filter_schema tool per trade-trace-fo7.

Covers ux0 chunk 1 acceptance:
- Pydantic ReportFilter schema implements every field per reports.md §2.
- report.filter_schema returns canonical JSON Schema introspectable at runtime.
- Strategy-id sentinel semantics work as documented.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from trade_trace.contracts.report_filter import (
    STRATEGY_NONE_SENTINEL,
    ReportFilter,
)
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


# -- schema completeness --------------------------------------------------


def test_report_filter_top_level_groups_complete():
    """Every group enumerated in reports.md §2 is a field on ReportFilter."""

    schema = ReportFilter.model_json_schema()
    properties = schema["properties"]
    expected = {
        "time_window", "actors", "strategy", "instrument",
        "decision", "market_context", "outcome", "source",
    }
    assert set(properties) == expected


def test_time_window_fields_complete():
    rf = ReportFilter()
    expected = {
        "created_at_gte", "created_at_lt",
        "decision_at_gte", "decision_at_lt",
        "resolved_at_gte", "resolved_at_lt",
    }
    assert set(rf.time_window.model_dump()) == expected


def test_actors_fields_complete():
    rf = ReportFilter()
    expected = {"actor_id", "agent_id", "model_id", "environment", "run_id"}
    assert set(rf.actors.model_dump()) == expected


def test_decision_fields_complete():
    rf = ReportFilter()
    expected = {
        "decision_type", "side", "tags_any", "tags_all",
        "has_thesis", "has_forecast", "has_reflection",
        "has_playbook_adherence",
    }
    assert set(rf.decision.model_dump()) == expected


def test_outcome_fields_include_late_recorded_with_correct_default():
    """dogfood-protocol.md §2.2: late-recorded forecasts are EXCLUDED by
    default from calibration aggregates; explicit opt-in switches to
    include them with caveat."""

    rf = ReportFilter()
    assert rf.outcome.include_late_recorded is False
    assert "score_gte" in rf.outcome.model_dump()
    assert "score_lt" in rf.outcome.model_dump()


# -- empty filter matches everything --------------------------------------


def test_empty_filter_default_constructs():
    rf = ReportFilter()
    # Empty groups: arrays empty, scalars None, defaults applied.
    assert rf.actors.actor_id == []
    assert rf.strategy.strategy_id is None
    assert rf.time_window.created_at_gte is None
    assert rf.outcome.include_late_recorded is False


def test_empty_dict_filter_round_trips():
    rf = ReportFilter.model_validate({})
    # Re-dumping produces the same default-populated shape.
    assert rf == ReportFilter()


# -- unknown fields rejected (per reports.md §2.1) ----------------------


def test_unknown_top_level_field_rejected():
    with pytest.raises(ValidationError):
        ReportFilter.model_validate({"unknown_group": {}})


def test_unknown_nested_field_rejected():
    with pytest.raises(ValidationError):
        ReportFilter.model_validate({"time_window": {"made_up_field": "x"}})


# -- strategy_id sentinel semantics ------------------------------------


def test_strategy_filter_mode_none_when_unset():
    rf = ReportFilter()
    assert rf.strategy_filter_mode() == "none"


def test_strategy_filter_mode_is_null_for_sentinel():
    rf = ReportFilter.model_validate({"strategy": {"strategy_id": STRATEGY_NONE_SENTINEL}})
    assert rf.strategy_filter_mode() == "is_null"


def test_strategy_filter_mode_match_for_concrete_id():
    rf = ReportFilter.model_validate({"strategy": {"strategy_id": "strat_abc"}})
    assert rf.strategy_filter_mode() == "match"


def test_strategy_filter_mode_match_for_slug():
    rf = ReportFilter.model_validate({"strategy": {"strategy_id": "my-slug"}})
    assert rf.strategy_filter_mode() == "match"


def test_strategy_sentinel_constant_pinned():
    """The sentinel value is part of the public contract; pin it so an
    accidental rename surfaces immediately."""

    assert STRATEGY_NONE_SENTINEL == "__none__"


# -- report.filter_schema tool ----------------------------------------


def test_report_filter_schema_registered():
    assert "report.filter_schema" in default_registry().names()


def test_report_filter_schema_returns_json_schema(tmp_path: Path):
    env = mcp_call("report.filter_schema", {}).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is True
    data = env["data"]
    schema = data["schema"]
    assert schema["type"] == "object"
    # The same groups visible on the Pydantic surface land in the JSON schema.
    assert "time_window" in schema["properties"]
    assert "decision" in schema["properties"]


def test_report_filter_schema_surfaces_strategy_sentinel(tmp_path: Path):
    env = mcp_call("report.filter_schema", {}).model_dump(mode="json", exclude_none=True)
    sentinel = env["data"]["strategy_id_sentinel"]
    assert sentinel["value"] == STRATEGY_NONE_SENTINEL
    assert "IS NULL" in sentinel["meaning"]


def test_report_filter_schema_rejects_unknown_mode():
    env = mcp_call("report.filter_schema", {"mode": "made_up"}).model_dump(
        mode="json", exclude_none=True
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_report_filter_schema_serialization_mode():
    env = mcp_call("report.filter_schema", {"mode": "serialization"}).model_dump(
        mode="json", exclude_none=True
    )
    assert env["ok"] is True
    assert env["data"]["mode"] == "serialization"
