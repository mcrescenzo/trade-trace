"""report.compare (trade-trace-4md)."""

from __future__ import annotations

from pathlib import Path

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _env(home: Path, tool: str, args: dict):
    return mcp_call(tool, {"home": str(home), **args}, actor_id="agent:default").model_dump(
        mode="json", exclude_none=True
    )


def _seed_positions(home: Path) -> None:
    v = _env(home, "venue.add", {"name": "Compare PM", "kind": "prediction_market"})["data"]["id"]
    i1 = _env(home, "instrument.add", {"venue_id": v, "asset_class": "prediction_market", "title": "A"})["data"]["id"]
    i2 = _env(home, "instrument.add", {"venue_id": v, "asset_class": "prediction_market", "title": "B"})["data"]["id"]
    db = open_database(db_path(home))
    try:
        with db.transaction():
            for pos_id, instr, status, realized, unrealized in [
                ("pos_b", i1, "closed", 2.0, None),
                ("pos_a", i2, "closed", 1.0, None),
                ("pos_c", i2, "open", None, 0.5),
            ]:
                db.connection.execute(
                    "INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, closed_at, resolved_at, realized_pnl, unrealized_pnl, avg_entry_price, updated_at) "
                    "VALUES (?, ?, 'paper', 'long', ?, '2026-05-18T00:00:00Z', NULL, NULL, ?, ?, 1.0, '2026-05-18T01:00:00Z')",
                    (pos_id, instr, status, realized, unrealized),
                )
    finally:
        db.close()


def test_compare_registered():
    names = default_registry().names()
    assert "report.compare" in names


def test_compare_pnl_grouping_stable_order_and_sample_warning(home):
    _seed_positions(home)
    first = _env(home, "report.compare", {"base_report": "pnl", "group_by": "status"})
    second = _env(home, "report.compare", {"base_report": "pnl", "group_by": "status"})
    assert first["ok"], first
    groups = first["data"]["groups"]
    assert [g["key"] for g in groups] == ["closed", "open"]
    assert [g["key"] for g in groups] == [g["key"] for g in second["data"]["groups"]]
    closed = groups[0]
    assert closed["metrics"]["closed_count"] == 2
    assert closed["sample_warning"] == "only 2 closed positions; pnl trend is unreliable below 5"
    assert first["data"]["summary"]["sample_warning"] == "one_or_more_groups_below_min_sample"


def test_compare_rejects_injected_group_by(home):
    env = _env(home, "report.compare", {"base_report": "pnl", "group_by": "status; DROP TABLE positions"})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_unsupported_group_by_error_lists_allowed_set(home):
    """AX-049: rejecting an unsupported group_by must name the allowed set
    for that base_report so an MCP-only bot can recover, instead of echoing
    only the offending value (the AX-004/005/032/035 self-documenting class).
    `tag` is in neither allowlist, so it is the canonical no-recovery case."""
    cal = _env(home, "report.compare", {"base_report": "calibration", "group_by": "tag"})
    assert cal["ok"] is False
    assert cal["error"]["code"] == "VALIDATION_ERROR"
    msg = cal["error"]["message"]
    # names the allowed set, not just the rejected value
    assert "allowed group_by values are" in msg
    assert "strategy_id" in msg and "instrument_id" in msg
    assert "'tag'" in msg  # still echoes the offending value

    pnl = _env(home, "report.compare", {"base_report": "pnl", "group_by": "tag"})
    assert pnl["ok"] is False
    pnl_msg = pnl["error"]["message"]
    assert "allowed group_by values are" in pnl_msg
    # pnl allowlist is the narrower one — must reflect the per-base set
    assert "instrument_id" in pnl_msg and "asset_class" in pnl_msg


def test_compare_schema_does_not_advertise_unsupported_tag_group_by():
    """AX-049: the advertised report.compare group_by description must not
    list `tag` as a usable value, since it is rejected for both base_reports
    (advertising-vs-runtime drift, the trade-trace-cs0r class)."""
    from trade_trace.reports.compare import CALIBRATION_GROUP_SQL, PNL_GROUP_SQL
    from trade_trace.reports.tool_schemas import _REPORT_SCHEMAS

    assert "tag" not in CALIBRATION_GROUP_SQL
    assert "tag" not in PNL_GROUP_SQL
    desc = _REPORT_SCHEMAS["report.compare"]["properties"]["group_by"]["description"]
    # every group_by the description names as supported must actually be in an allowlist
    allowed = set(CALIBRATION_GROUP_SQL) | set(PNL_GROUP_SQL)
    assert "tag" in desc and "not a supported" in desc  # explicitly corrects the prior claim
    for value in ("strategy_id", "instrument_id", "asset_class", "venue_id"):
        assert value in desc and value in allowed


def test_compare_schema_advertises_every_runtime_group_by():
    """AX-050: the advertised group_by description must name EVERY value the
    runtime allowlists accept — not just a sample. The AX-049 fix enumerated the
    allowlist into the description but missed `outcome_status` (a working alias of
    `status` in CALIBRATION_GROUP_SQL that the rejection error itself advertises),
    re-opening the same advertising-vs-runtime drift (trade-trace-cs0r class) on
    one value. A bot reading the schema must learn every group_by it could pass."""
    from trade_trace.reports.compare import CALIBRATION_GROUP_SQL, PNL_GROUP_SQL
    from trade_trace.reports.tool_schemas import _REPORT_SCHEMAS

    desc = _REPORT_SCHEMAS["report.compare"]["properties"]["group_by"]["description"]
    for value in set(CALIBRATION_GROUP_SQL) | set(PNL_GROUP_SQL):
        assert value in desc, f"group_by {value!r} is runtime-supported but unadvertised in the schema description"


# -- documented group_by matches runtime (trade-trace-cs0r) -----------


def test_documented_group_by_matches_runtime_support():
    """Per trade-trace-cs0r: `DOCUMENTED_GROUP_BY` must equal the union
    of the per-base-report runtime allowlists. Adding a value to the
    docs without wiring the SQL mapping silently breaks agents."""

    from trade_trace.reports.compare import (
        CALIBRATION_GROUP_SQL,
        DOCUMENTED_GROUP_BY,
        PNL_GROUP_SQL,
        SUPPORTED_GROUP_BY_BY_BASE_REPORT,
    )

    assert DOCUMENTED_GROUP_BY == set(CALIBRATION_GROUP_SQL) | set(PNL_GROUP_SQL)
    assert SUPPORTED_GROUP_BY_BY_BASE_REPORT == {
        "calibration": set(CALIBRATION_GROUP_SQL),
        "pnl": set(PNL_GROUP_SQL),
    }
