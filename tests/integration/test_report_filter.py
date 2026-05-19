"""ReportFilter Pydantic schema + report.filter_schema tool per trade-trace-fo7.

Covers ux0 chunk 1 acceptance:
- Pydantic ReportFilter schema implements every field per reports.md §2.
- report.filter_schema returns canonical JSON Schema introspectable at runtime.
- Strategy-id sentinel semantics work as documented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


# -- per-report supported-filter rejection contract (beads d4k / ke1) ------
#
# Each report.* tool now declares the exact set of ReportFilter leaves it
# applies at SQL time; any non-default value in an unsupported leaf is
# rejected with VALIDATION_ERROR rather than silently broadened to global
# rows. These tests pin the contract per report so a future regression
# (e.g. a report drops a leaf without trimming its supported set) lands
# as a clear test failure.


def _journal_home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


# Each row is (report tool, MCP args mixed in alongside `filter`, a leaf
# the report does NOT support). Reports with no SQL-applied filter leaves
# get `decision.decision_type` as the canary; reports that do apply a
# leaf get one chosen from outside their supported set.
_UNSUPPORTED_LEAF_CASES: list[tuple[str, dict[str, Any], dict[str, Any], str]] = [
    ("report.calibration", {}, {"decision": {"decision_type": ["actual_enter"]}},
     "decision.decision_type"),
    ("report.mistakes", {}, {"actors": {"actor_id": ["agent:foo"]}},
     "actors.actor_id"),
    ("report.strengths", {}, {"actors": {"actor_id": ["agent:foo"]}},
     "actors.actor_id"),
    ("report.pnl", {}, {"instrument": {"venue_id": ["v_x"]}},
     "instrument.venue_id"),
    ("report.watchlist", {}, {"actors": {"actor_id": ["agent:foo"]}},
     "actors.actor_id"),
    ("report.unscored_forecasts", {}, {"strategy": {"strategy_id": "s_x"}},
     "strategy.strategy_id"),
    ("report.playbook_adherence", {}, {"decision": {"decision_type": ["actual_enter"]}},
     "decision.decision_type"),
    ("report.decision_velocity", {}, {"actors": {"actor_id": ["agent:foo"]}},
     "actors.actor_id"),
    ("report.coach", {}, {"actors": {"actor_id": ["agent:foo"]}},
     "actors.actor_id"),
]


@pytest.mark.parametrize(
    "tool,extra,filter_input,unsupported_leaf",
    _UNSUPPORTED_LEAF_CASES,
)
def test_report_rejects_unsupported_filter_leaf(
    tmp_path, tool, extra, filter_input, unsupported_leaf,
):
    """Per d4k/ke1: a non-default value in a ReportFilter leaf the report
    does not apply at SQL time must be rejected with VALIDATION_ERROR and
    the offending leaf surfaced in `error.details`."""

    home = _journal_home(tmp_path)
    env = mcp_call(
        tool,
        {"home": str(home), "filter": filter_input, **extra},
        actor_id="agent:default",
    )
    assert env.ok is False, (
        f"{tool} accepted unsupported filter leaf {unsupported_leaf!r}; "
        "must reject to avoid silently broadening"
    )
    assert env.error.code.value == "VALIDATION_ERROR"
    details = env.error.details
    assert details["field"] == "filter"
    assert details["report"] == tool
    assert unsupported_leaf in details["unsupported_filter_paths"]


def test_calibration_supports_actor_strategy_instrument_and_late_recorded(
    tmp_path,
):
    """Calibration's declared supported set is the source of truth; pin
    it so a future drift (add or remove) is visible in this test rather
    than silently changing behavior across the report surface."""

    from trade_trace.reports._filter_support import SUPPORTED_FILTER_FIELDS

    assert SUPPORTED_FILTER_FIELDS["report.calibration"] == frozenset({
        "actors.actor_id",
        "instrument.venue_id",
        "strategy.strategy_id",
        "outcome.include_late_recorded",
    })


def test_empty_supported_set_reports_accept_empty_filter(tmp_path):
    """Reports with an empty supported set still accept the empty
    ReportFilter (the default) — only non-default unsupported leaves
    trigger rejection."""

    home = _journal_home(tmp_path)
    for tool in (
        "report.mistakes", "report.strengths", "report.pnl",
        "report.watchlist", "report.unscored_forecasts",
        "report.playbook_adherence", "report.coach",
    ):
        env = mcp_call(
            tool,
            {"home": str(home), "filter": {}},
            actor_id="agent:default",
        )
        assert env.ok, f"{tool} rejected the empty filter: {env}"
