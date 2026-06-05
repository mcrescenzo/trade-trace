from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path

AS_OF = "2026-05-21T00:00:00Z"


def _cli(home: Path, *args: str) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "trade_trace.cli", *args, "--home", str(home)]
    result = subprocess.run(cmd, cwd=Path(__file__).parents[2], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def _cli_write(home: Path, *args: str) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "trade_trace.cli", "--allow-no-idempotency", *args, "--home", str(home)]
    result = subprocess.run(cmd, cwd=Path(__file__).parents[2], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    body = _cli(h, "journal", "init")
    assert body["ok"] is True
    return h


def _instrument(home: Path, suffix: str) -> str:
    venue = _cli_write(home, "venue", "add", "--name", f"PM {suffix}", "--kind", "prediction_market")
    assert venue["ok"] is True
    inst = _cli_write(
        home,
        "instrument",
        "add",
        "--venue-id",
        venue["data"]["id"],
        "--asset-class",
        "prediction_market",
        "--title",
        f"Will scenario {suffix} settle yes?",
    )
    assert inst["ok"] is True
    return inst["data"]["id"]


def _insert_decision(
    home: Path,
    *,
    decision_id: str,
    instrument_id: str,
    type_: str,
    created_at: str = "2026-05-20T00:00:00Z",
    side: str = "yes",
    quantity: float = 1.0,
    price: float = 0.42,
    reason: str = "agent-surface seeded decision",
) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            """
            INSERT INTO decisions(
                id, instrument_id, type, side, quantity, price, reason,
                run_id, metadata_json, created_at, actor_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'run_agent_surface', '{}', ?, 'agent:test')
            """,
            (decision_id, instrument_id, type_, side, quantity, price, reason, created_at),
        )
        db.connection.commit()
    finally:
        db.close()


def _insert_position(
    home: Path,
    *,
    position_id: str,
    instrument_id: str,
    decision_id: str | None,
    kind: str = "paper",
    status: str = "open",
    opened_at: str = "2026-05-20T00:00:00Z",
    closed_at: str | None = None,
    unrealized_pnl: float | None = 3.25,
) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            """
            INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, closed_at,
                                  resolved_at, realized_pnl, unrealized_pnl, avg_entry_price,
                                  updated_at, initial_risk_amount)
            VALUES (?, ?, ?, 'yes', ?, ?, ?, NULL, NULL, ?, 0.42, ?, 10.0)
            """,
            (position_id, instrument_id, kind, status, opened_at, closed_at, unrealized_pnl, opened_at),
        )
        if status in {"open", "partial"}:
            event_type = "open"
            qty = 1.0
        else:
            event_type = "close"
            qty = -1.0
        db.connection.execute(
            """
            INSERT INTO position_events(id, position_id, instrument_id, decision_id, event_type,
                                        quantity_delta, price, fees, slippage, metadata_json, created_at, actor_id,
                                        initial_risk_amount, unrealized_r_multiple)
            VALUES (?, ?, ?, ?, ?, ?, 0.42, 0.0, 0.0, '{}', ?, 'agent:test', 10.0, 0.325)
            """,
            (f"pe_{position_id}", position_id, instrument_id, decision_id, event_type, qty, opened_at),
        )
        db.connection.commit()
    finally:
        db.close()


def _insert_snapshot(home: Path, *, snapshot_id: str, instrument_id: str, captured_at: str) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            """
            INSERT INTO snapshots(id, instrument_id, captured_at, source, source_url,
                                  price, bid, ask, mid, implied_probability, created_at, actor_id)
            VALUES (?, ?, ?, 'agent_surface_test', 'https://example.test/mark',
                    0.44, NULL, NULL, NULL, NULL, ?, 'agent:test')
            """,
            (snapshot_id, instrument_id, captured_at, captured_at),
        )
        db.connection.commit()
    finally:
        db.close()


def _codes(rows: list[dict[str, Any]]) -> set[str]:
    return {code for row in rows for code in row.get("caveat_codes", [])}


def test_cli_empty_journal_has_canonical_zero_open_positions_and_valid_json_envelopes(home: Path) -> None:
    current = _cli(home, "report", "current_exposure", "--as-of", AS_OF)
    assert current["ok"] is True
    assert current["meta"]["tool"] == "report.current_exposure"
    data = current["data"]
    assert data["summary"]["bucket"] == "current_exposure"
    assert data["summary"]["buckets"] == [
        "open_positions",
        "event_exposure_sets",
        "watchlist",
        "recent_trade_activity",
        "projection_anomalies",
    ]
    assert data["summary"]["open_position_count"] == 0
    assert data["summary"]["watch_count"] == 0
    assert data["summary"]["recent_trade_decision_count"] == 0
    assert data["summary"]["anomaly_count"] == 0
    assert data["open_positions"] == []
    assert data["watchlist"] == []
    assert data["recent_trade_activity"] == []
    assert data["projection_anomalies"] == []
    assert data["event_exposure_sets"] == []
    assert any(
        hint in data["agent_answer_hints"]
        for hint in ("Canonical open positions: zero.", "Canonical open positions: 0.")
    )

    open_positions = _cli(home, "report", "open_positions", "--as-of", AS_OF)
    assert open_positions["ok"] is True
    assert open_positions["meta"]["tool"] == "report.open_positions"
    assert open_positions["data"]["summary"]["bucket"] == "open_positions"
    assert open_positions["data"]["summary"]["count"] == 0
    assert open_positions["data"]["summary"]["open_position_count"] == 0
    assert open_positions["data"]["summary"]["caveat_codes"] == ["NO_OPEN_POSITIONS"]
    assert open_positions["data"]["open_positions"] == []


def test_cli_golden_recent_journal_entry_is_not_open_exposure(home: Path) -> None:
    instrument_id = _instrument(home, "recent-only")
    _insert_decision(home, decision_id="dec_recent_actual_only", instrument_id=instrument_id, type_="actual_enter")

    body = _cli(home, "report", "current_exposure", "--recent-limit", "5", "--as-of", AS_OF)
    data = body["data"]

    assert data["summary"]["open_position_count"] == 0
    assert data["summary"]["recent_trade_decision_count"] == 1
    assert data["summary"]["anomaly_count"] >= 1
    assert data["open_positions"] == []
    assert data["agent_answer_hints"].count(
        "Canonical open positions: zero; recent journal entries exist but are not open exposure."
    ) == 1
    recent = {row["decision_id"]: row for row in data["recent_trade_activity"]}
    assert "JOURNAL_ACTIVITY_NOT_CANONICAL_EXPOSURE" in recent["dec_recent_actual_only"]["caveat_codes"]
    assert "RECORD_ONLY_ACTUAL" in recent["dec_recent_actual_only"]["caveat_codes"]
    anomaly_codes = {row["code"] for row in data["projection_anomalies"]}
    assert {"RECORD_ONLY_ACTUAL", "ENTRY_DECISION_WITHOUT_POSITION_EVENT"} <= anomaly_codes


def test_cli_open_paper_position_with_fresh_mark_supports_llm_summary(home: Path) -> None:
    instrument_id = _instrument(home, "paper-open")
    _insert_decision(home, decision_id="dec_paper_open", instrument_id=instrument_id, type_="paper_enter")
    _insert_position(home, position_id="pos_paper_open", instrument_id=instrument_id, decision_id="dec_paper_open")
    _insert_snapshot(home, snapshot_id="snap_fresh_mark", instrument_id=instrument_id, captured_at="2026-05-20T12:00:00Z")

    current = _cli(home, "report", "current_exposure", "--as-of", AS_OF, "--stale-mark-threshold-days", "14")
    row = current["data"]["open_positions"][0]
    assert current["data"]["summary"]["open_position_count"] == 1
    assert row["position_id"] == "pos_paper_open"
    assert row["instrument_id"] == instrument_id
    assert row["kind"] == "paper"
    assert row["latest_mark"]["snapshot_id"] == "snap_fresh_mark"
    assert row["mark_state"] == "available"
    assert "OPEN_PAPER_POSITION" in row["caveat_codes"]
    assert "STALE_MARK" not in row["caveat_codes"]
    assert "MISSING_MARK" not in row["caveat_codes"]

    open_positions = _cli(home, "report", "open_positions", "--as-of", AS_OF, "--stale-mark-threshold-days", "14")
    assert open_positions["data"]["open_positions"][0]["position_id"] == "pos_paper_open"


def test_exposure_reports_groups_reference_event_exposure_sets_not_reembedded(home: Path) -> None:
    """report.open_positions and report.current_exposure must not double-serialize the
    same event_exposure_sets list under BOTH 'groups' and 'event_exposure_sets'
    (trade-trace-lszg / AX-034). 'groups' is a lightweight reference so the envelope
    stays under the MCP token cap as open positions accumulate; the full sets live only
    under 'event_exposure_sets'."""
    instrument_id = _instrument(home, "groups-ref")
    _insert_decision(home, decision_id="dec_groups_ref", instrument_id=instrument_id, type_="paper_enter")
    _insert_position(home, position_id="pos_groups_ref", instrument_id=instrument_id, decision_id="dec_groups_ref")

    for report_name in ("open_positions", "current_exposure"):
        body = _cli(home, "report", report_name, "--as-of", AS_OF)
        data = body["data"]
        event_sets = data["event_exposure_sets"]
        assert isinstance(event_sets, list), f"{report_name}: event_exposure_sets should be a list"
        assert data["groups"] == {"ref": "event_exposure_sets", "count": len(event_sets)}, (
            f"{report_name}: groups should be a reference to event_exposure_sets, "
            f"not a re-embedded copy; got {data['groups']!r}"
        )


def test_cli_actual_recorded_open_position_has_broker_truth_caveat(home: Path) -> None:
    instrument_id = _instrument(home, "actual-open")
    _insert_decision(home, decision_id="dec_actual_open", instrument_id=instrument_id, type_="actual_enter")
    _insert_position(home, position_id="pos_actual_open", instrument_id=instrument_id, decision_id="dec_actual_open", kind="actual")
    _insert_snapshot(home, snapshot_id="snap_actual_fresh", instrument_id=instrument_id, captured_at="2026-05-20T12:00:00Z")

    body = _cli(home, "report", "current_exposure", "--kind", "actual", "--as-of", AS_OF)
    row = body["data"]["open_positions"][0]

    assert body["data"]["summary"]["open_position_count"] == 1
    assert row["position_id"] == "pos_actual_open"
    assert row["kind"] == "actual"
    assert "OPEN_ACTUAL_RECORDED_POSITION" in row["caveat_codes"]
    assert any("broker" in hint.lower() or "local" in hint.lower() for hint in body["data"]["agent_answer_hints"])


def test_cli_closed_position_and_watch_only_idea_are_not_open_exposure(home: Path) -> None:
    closed_instrument = _instrument(home, "closed")
    watch_instrument = _instrument(home, "watch")
    _insert_decision(home, decision_id="dec_closed", instrument_id=closed_instrument, type_="paper_enter")
    _insert_position(
        home,
        position_id="pos_closed",
        instrument_id=closed_instrument,
        decision_id="dec_closed",
        status="closed",
        closed_at="2026-05-20T01:00:00Z",
    )
    watch = _cli_write(home, "decision", "add", "--instrument-id", watch_instrument, "--type", "watch", "--reason", "watch only")
    assert watch["ok"] is True

    body = _cli(home, "report", "current_exposure", "--recent-limit", "10", "--as-of", AS_OF)
    data = body["data"]

    assert data["summary"]["open_position_count"] == 0
    assert data["open_positions"] == []
    assert all(row.get("position_id") != "pos_closed" for row in data["open_positions"])
    assert data["summary"]["watch_count"] == 1
    assert data["watchlist"][0]["decision_id"] == watch["data"]["id"]
    assert data["watchlist"][0]["instrument_id"] == watch_instrument
    assert data["watchlist"][0]["caveat_codes"] == ["WATCH_ONLY_IDEA"]
    assert "WATCH_ONLY_IDEA" in _codes(data["watchlist"])


def test_cli_duplicate_missing_projection_and_stale_missing_marks_surface_stable_codes(home: Path) -> None:
    dup_instrument = _instrument(home, "duplicates")
    missing_mark_instrument = _instrument(home, "missing-mark")
    stale_mark_instrument = _instrument(home, "stale-mark")

    _insert_decision(home, decision_id="dec_dup_one", instrument_id=dup_instrument, type_="paper_enter", created_at="2026-05-20T00:00:00Z")
    _insert_decision(home, decision_id="dec_dup_two", instrument_id=dup_instrument, type_="paper_enter", created_at="2026-05-20T00:01:00Z")
    _insert_decision(home, decision_id="dec_missing_mark", instrument_id=missing_mark_instrument, type_="paper_enter")
    _insert_position(
        home,
        position_id="pos_missing_mark",
        instrument_id=missing_mark_instrument,
        decision_id="dec_missing_mark",
        unrealized_pnl=None,
    )
    _insert_decision(home, decision_id="dec_stale_mark", instrument_id=stale_mark_instrument, type_="paper_enter")
    _insert_position(home, position_id="pos_stale_mark", instrument_id=stale_mark_instrument, decision_id="dec_stale_mark")
    _insert_snapshot(home, snapshot_id="snap_stale", instrument_id=stale_mark_instrument, captured_at="2026-05-01T00:00:00Z")

    body = _cli(
        home,
        "report",
        "current_exposure",
        "--recent-limit",
        "10",
        "--as-of",
        AS_OF,
        "--stale-mark-threshold-days",
        "14",
    )
    data = body["data"]
    rows = {row["position_id"]: row for row in data["open_positions"]}

    assert data["summary"]["open_position_count"] == 2
    assert rows["pos_missing_mark"]["mark_state"] == "missing"
    assert "MISSING_MARK" in rows["pos_missing_mark"]["caveat_codes"]
    assert rows["pos_stale_mark"]["mark_state"] == "stale"
    assert rows["pos_stale_mark"]["latest_mark"]["snapshot_id"] == "snap_stale"
    assert "STALE_MARK" in rows["pos_stale_mark"]["caveat_codes"]

    anomaly_codes = {row["code"] for row in data["projection_anomalies"]}
    assert {"DUPLICATE_DECISIONS", "ENTRY_DECISION_WITHOUT_POSITION_EVENT", "MISSING_MARK", "STALE_MARK"} <= anomaly_codes
    assert data["summary"]["anomaly_count"] >= 4
    assert any("Projection anomalies" in hint for hint in data["agent_answer_hints"])
