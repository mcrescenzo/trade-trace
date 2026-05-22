"""Error-path coverage for the new strategy / forecast diagnostics /
strategy_health surfaces per trade-trace-l6ot.

These error branches were under-covered: the handlers raised typed
ToolErrors but no integration test exercised them, so a future refactor
could silently change the error code/details and only surface in
production. Each case asserts the envelope is `ok=False`, the error code
matches, and (where the handler carries one) the `details.field`.
"""

from __future__ import annotations

import pytest

from tests._mcp_helpers import mcp_default as _mcp

# -- strategy.create error branches ---------------------------------


def test_strategy_create_rejects_missing_required_fields(home):
    env = _mcp(home, "strategy.create", {
        "idempotency_key": "00000000-0000-4000-8000-strat-missing-1",
    })
    assert env.ok is False, env
    err = env.error.model_dump(mode="json")
    assert err["code"] == "VALIDATION_ERROR"


def test_strategy_create_rejects_missing_slug_only(home):
    env = _mcp(home, "strategy.create", {
        "name": "No Slug Test",
        "idempotency_key": "00000000-0000-4000-8000-strat-missing-2",
    })
    assert env.ok is False
    err = env.error.model_dump(mode="json")
    assert err["code"] == "VALIDATION_ERROR"


# -- strategy.show error branches -----------------------------------


def test_strategy_show_returns_not_found_for_unknown_id(home):
    env = _mcp(home, "strategy.show", {"strategy_id": "strat-does-not-exist"})
    assert env.ok is False, env
    err = env.error.model_dump(mode="json")
    assert err["code"] == "NOT_FOUND"


def test_strategy_show_returns_not_found_for_unknown_slug(home):
    env = _mcp(home, "strategy.show", {"slug": "missing-strategy"})
    assert env.ok is False, env
    err = env.error.model_dump(mode="json")
    assert err["code"] == "NOT_FOUND"


# -- strategy.list error branches -----------------------------------


@pytest.mark.parametrize("bad_limit", [0, -1, 1001, 99999])
def test_strategy_list_rejects_out_of_range_limit(home, bad_limit):
    env = _mcp(home, "strategy.list", {"limit": bad_limit})
    assert env.ok is False, env
    err = env.error.model_dump(mode="json")
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"]["field"] == "limit"


def test_strategy_list_rejects_unknown_status(home):
    env = _mcp(home, "strategy.list", {"status": "banana"})
    assert env.ok is False, env
    err = env.error.model_dump(mode="json")
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"]["field"] == "status"


# -- report.strategy_health error branches --------------------------


def test_report_strategy_health_rejects_unknown_status(home):
    env = _mcp(home, "report.strategy_health", {"status": "banana"})
    assert env.ok is False, env
    err = env.error.model_dump(mode="json")
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"]["field"] == "status"


@pytest.mark.parametrize("bad_min_sample", [0, -1, -100])
def test_report_strategy_health_rejects_non_positive_min_sample(home, bad_min_sample):
    env = _mcp(home, "report.strategy_health", {"min_sample": bad_min_sample})
    assert env.ok is False, env
    err = env.error.model_dump(mode="json")
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"]["field"] == "min_sample"


def test_report_strategy_health_rejects_non_integer_min_sample(home):
    env = _mcp(home, "report.strategy_health", {"min_sample": "five"})
    assert env.ok is False, env
    err = env.error.model_dump(mode="json")
    assert err["code"] == "VALIDATION_ERROR"


def test_report_strategy_health_rejects_none_sentinel_strategy_id(home):
    env = _mcp(home, "report.strategy_health", {
        "filter": {"strategy_id": "__none__"},
    })
    assert env.ok is False, env
    err = env.error.model_dump(mode="json")
    assert err["code"] == "VALIDATION_ERROR"


def test_report_strategy_health_rejects_non_string_as_of(home):
    env = _mcp(home, "report.strategy_health", {"as_of": 12345})
    assert env.ok is False, env
    err = env.error.model_dump(mode="json")
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"]["field"] == "as_of"


# -- report.forecast_diagnostics error branches ---------------------


def test_report_forecast_diagnostics_rejects_unsupported_filter_key(home):
    env = _mcp(home, "report.forecast_diagnostics", {
        "filter": {"symbols": ["ABC"]},
    })
    assert env.ok is False, env
    err = env.error.model_dump(mode="json")
    assert err["code"] == "VALIDATION_ERROR"
