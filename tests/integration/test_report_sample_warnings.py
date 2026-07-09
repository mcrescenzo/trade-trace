"""Per-report sample-size warnings per docs/architecture/reports.md §3.2
and bead trade-trace-d0w (test QC).

Required by the QC bead:
    - calibration < 20  (covered separately in test_report_calibration.py)
    - mistakes < 10
    - pnl < 5
    - playbook_adherence < 10 (covered in
      test_playbook_layer.py::test_report_playbook_adherence_low_sample_summary_and_meta_warning)

This file adds positive + negative cases for the report kinds that the
calibration suite does not already cover.
"""

from __future__ import annotations

from pathlib import Path

from tests._mcp_helpers import mcp_default as _mcp


def _seed_decision_with_tag(home: Path, tag: str, n: int) -> None:
    """Walk `n` decisions with the same tag against fresh instruments so
    the tag aggregate has `n` rows."""

    venue = _mcp(home, "venue.add",
                 {"name": "PM", "kind": "prediction_market"}).data["id"]
    for i in range(n):
        inst = _mcp(home, "instrument.add", {
            "venue_id": venue,
            "asset_class": "prediction_market", "title": f"X-{i}",
        }).data["id"]
        thesis = _mcp(home, "thesis.add", {
            "instrument_id": inst, "side": "yes", "body": "t",
        }).data["id"]
        fcst = _mcp(home, "forecast.add", {
            "thesis_id": thesis, "kind": "binary", "yes_label": "yes",
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.6},
                {"outcome_label": "no", "probability": 0.4},
            ],
        }).data["id"]
        _mcp(home, "resolution.add", {
            "instrument_id": inst,
            "resolved_at": f"2026-06-{i + 1:02d}T00:00:00Z",
            "outcome_label": "yes", "status": "resolved_final",
            "confidence": 0.99,
        })
        _mcp(home, "decision.add", {
            "type": "actual_enter", "instrument_id": inst,
            "thesis_id": thesis, "forecast_id": fcst,
            "side": "yes", "quantity": 1, "price": 0.6,
            "tags": [tag],
            "idempotency_key": f"00000000-0000-4000-8000-{i:012d}",
        })


# -- mistakes sample_warning ----------------------------------------


def test_mistakes_per_group_sample_warning_fires_below_10(home):
    """report.mistakes default min_sample is 10. A tag with 3 scored
    decisions surfaces a per-group sample_warning."""

    _seed_decision_with_tag(home, "rare-pattern", n=3)
    env = _mcp(home, "report.mistakes", {})
    assert env.ok
    groups = env.data["groups"]
    rare = next(g for g in groups if g["key"] == "rare-pattern")
    assert rare["sample_warning"] is not None
    assert "10" in rare["sample_warning"]


def test_mistakes_per_group_sample_warning_silent_at_threshold(home):
    """When a tag's scored sample size reaches min_sample, the per-group
    warning clears."""

    _seed_decision_with_tag(home, "common-pattern", n=10)
    env = _mcp(home, "report.mistakes", {})
    common = next(g for g in env.data["groups"] if g["key"] == "common-pattern")
    assert common["sample_warning"] is None


# -- pnl sample_warning ----------------------------------------------


def test_pnl_sample_warning_fires_below_five_closed_positions(home):
    """report.pnl default min_sample is 5 *closed* positions
    (src/trade_trace/reports/pnl.py). The positions projection is wired
    off `position_events` (persistence.md §7); decision.add does not
    write position_events directly in MVP (M3 work), so this test seeds
    the projection via the documented rebuild path that the existing
    pnl integration test uses — same code path `report.pnl` consumes."""

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    from trade_trace.tools._helpers import new_id

    venue = _mcp(home, "venue.add",
                 {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": "X",
    }).data["id"]
    db = open_database(db_path(home))
    try:
        with db.transaction():
            for i in range(3):
                pos_id = new_id("pos")
                db.connection.execute(
                    "INSERT INTO position_events(id, position_id, instrument_id, "
                    "event_type, quantity_delta, price, fees, slippage, "
                    "created_at, actor_id) "
                    "VALUES (?, ?, ?, 'open', 100, 0.40, 0, 0, ?, ?)",
                    (new_id("pev"), pos_id, inst,
                     f"2026-05-18T{14 + i:02d}:00:00Z", "agent:default"),
                )
                db.connection.execute(
                    "INSERT INTO position_events(id, position_id, instrument_id, "
                    "event_type, quantity_delta, price, fees, slippage, "
                    "created_at, actor_id) "
                    "VALUES (?, ?, ?, 'close', -100, 0.50, 0, 0, ?, ?)",
                    (new_id("pev"), pos_id, inst,
                     f"2026-05-18T{15 + i:02d}:00:00Z", "agent:default"),
                )
    finally:
        db.close()
    _mcp(home, "journal.rebuild_projections", {"projection": "positions"})

    env = _mcp(home, "report.pnl", {})
    assert env.ok
    warn = env.data["summary"]["sample_warning"]
    assert warn is not None, env.data["summary"]
    assert "5" in warn


def test_pnl_empty_db_no_sample_warning(home):
    """Negative: an empty journal yields zero positions; the report
    explicitly emits sample_warning=null (no positions to warn about)."""

    env = _mcp(home, "report.pnl", {})
    assert env.ok
    summary = env.data["summary"]
    # An empty pnl returns sample_size=0; the warning fires only when
    # 0 < sample_size < min_sample per src/trade_trace/reports/pnl.py.
    assert summary["sample_warning"] is None
