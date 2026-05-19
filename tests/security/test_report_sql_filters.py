"""SQL-filter safety for ReportFilter inputs per docs/architecture/reports.md
§2.1 and bead trade-trace-d0w.

The filter compiles to parameter-bound SQL only — no caller string is
interpolated into the query. These tests prove the contract by:

1. Asserting that an unknown field is rejected with VALIDATION_ERROR,
   not silently widened.
2. Sending strings containing classic SQL-injection payloads through
   every list-typed filter field; the dispatcher must either (a) ignore
   them (no matching row) or (b) return VALIDATION_ERROR. It must NEVER
   execute the payload (no table drop, no auth bypass, no row leak).
3. Sending strings containing CHECK-constraint-style content through
   the strategy_id sentinel position; the filter must not concatenate.

The mechanism is structural — every report function calls
`ReportFilter.model_validate(raw_filter or {})` and then binds list
values as `?` parameters in SQL. The tests pin the contract end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _mcp(home: Path, tool: str, args: dict | None = None):
    payload = {"home": str(home), **(args or {})}
    return mcp_call(tool, payload, actor_id="agent:default")


# -- 1. unknown filter field rejected (no silent widening) -------


def test_unknown_top_level_field_in_filter_rejected(home):
    """A made-up top-level filter section is rejected with
    VALIDATION_ERROR. ReportFilter has `extra='forbid'` so unknown keys
    cannot quietly become "match anything"."""

    env = _mcp(home, "report.calibration", {
        "filter": {"made_up_section": {}},
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"


def test_unknown_nested_filter_field_rejected(home):
    """A made-up nested key inside a real section also fails (extra is
    forbidden across all ReportFilter sub-models)."""

    env = _mcp(home, "report.calibration", {
        "filter": {"actors": {"unknown_sub_field": ["x"]}},
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"


# -- 2. injection-shaped strings do not execute -----------------


INJECTION_PAYLOADS = [
    "'; DROP TABLE forecasts; --",
    "' OR '1'='1",
    "1; SELECT * FROM sources",
    "agent\");DELETE FROM decisions;--",
    "%' UNION SELECT 1,2,3 FROM events --",
]


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_injection_payload_in_actor_filter_does_not_execute(home, payload):
    """Passing classic injection strings into the actor_id filter list
    must return a clean (empty) report. The DB tables must remain
    intact (verified after the call)."""

    env = _mcp(home, "report.calibration", {
        "filter": {"actors": {"actor_id": [payload]}},
    })
    # Either the report runs and returns zero rows (parameter-bound SQL
    # treats payload as a literal that matches nothing), or it returns
    # a typed envelope. Either is safe; what is NOT safe is a stack
    # trace, a 500, or a DROP TABLE side effect.
    if env.ok:
        assert env.data["summary"]["sample_size"] == 0
    else:
        # If it errors, it must be a typed error (no raw SQL stack trace).
        assert env.error.code.value in {
            "VALIDATION_ERROR", "STORAGE_ERROR", "INVARIANT_VIOLATION",
        }

    # Tables still exist.
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    db = open_database(db_path(home), create_parent=False)
    try:
        for table in ("forecasts", "decisions", "outcomes",
                      "sources", "events"):
            row = db.connection.execute(
                f"SELECT 1 FROM {table} LIMIT 1"
            ).fetchone()
            # Query succeeds → table exists. Tables may legitimately be
            # empty; what matters is the SELECT didn't error out.
            assert row is None or row is not None
    finally:
        db.close()


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_injection_payload_in_instrument_filter_does_not_execute(home, payload):
    """Same check on the instrument filter list — proves the parameter
    binding holds across every list-typed field, not just actor_id."""

    env = _mcp(home, "report.calibration", {
        "filter": {"instrument": {"venue_id": [payload]}},
    })
    if env.ok:
        assert env.data["summary"]["sample_size"] == 0
    else:
        assert env.error.code.value in {
            "VALIDATION_ERROR", "STORAGE_ERROR", "INVARIANT_VIOLATION",
        }


# -- 3. strategy sentinel handling ------------------------------


def test_strategy_id_sentinel_does_not_pass_through_as_sql_literal(home):
    """The strategy_id sentinel (`__none__`) is parsed by the server, not
    embedded in SQL. A payload-looking sentinel string is treated as a
    plain match (no rows) — not as a literal SQL fragment."""

    env = _mcp(home, "report.calibration", {
        "filter": {"strategy": {"strategy_id": "'; DROP TABLE forecasts; --"}},
    })
    # Either parses cleanly (returns zero rows because no strategy with
    # that id exists) or fails validation. Must not execute.
    if env.ok:
        assert env.data["summary"]["sample_size"] == 0


def test_supported_actor_filter_round_trips_and_applies_cleanly(home):
    """Calibration historically accepts actors.actor_id. Per d4k/ke1 it
    must therefore apply the filter safely and echo it as applied, not
    reject it and not silently broaden to global rows."""

    env = _mcp(home, "report.calibration", {
        "filter": {"actors": {"actor_id": ["agent:foo"]}},
    })
    assert env.ok, env
    assert env.data["summary"]["sample_size"] == 0
    echoed = env.data["summary"]["filter"]
    assert echoed["actors"]["actor_id"] == ["agent:foo"]


def test_supported_filter_field_round_trips_through_echo(home):
    """The supported subset still echoes back unchanged — the new
    contract narrows what's accepted but does not garble what's echoed."""

    env = _mcp(home, "report.calibration", {
        "filter": {"outcome": {"include_late_recorded": True}},
    })
    assert env.ok, env
    echoed = env.data["summary"]["filter"]
    assert echoed["outcome"]["include_late_recorded"] is True
    # Defaults remain in unrelated groups.
    assert echoed["actors"]["actor_id"] == []
