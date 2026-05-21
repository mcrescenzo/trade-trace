from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.contracts.envelope import dump_envelope
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    init = mcp_call("journal.init", {"home": str(h)})
    assert init.ok, init
    return h


@pytest.fixture
def rich_home(home: Path) -> Path:
    seed = mcp_call(
        "journal.fixture_seed",
        {
            "home": str(home),
            "target": "mvp-eval-rich",
            "idempotency_key": "00000000-0000-4000-8000-00000000d401",
        },
    )
    assert seed.ok, seed
    return home


def _call(home: Path, args: dict | None = None) -> dict:
    env = mcp_call("report.open_positions", {"home": str(home), **(args or {})})
    return dump_envelope(env)


def _insert_actual_open_position(home: Path) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        instrument_id = db.connection.execute("SELECT id FROM instruments LIMIT 1").fetchone()[0]
        db.connection.execute(
            """
            INSERT INTO positions(
                id, instrument_id, kind, side, status, opened_at, closed_at,
                resolved_at, realized_pnl, unrealized_pnl, avg_entry_price,
                updated_at, initial_risk_amount, realized_r_multiple,
                unrealized_r_multiple
            ) VALUES (?, ?, 'actual', 'yes', 'open', ?, NULL, NULL, NULL,
                      3.25, 0.55, ?, 10.0, NULL, 0.325)
            """,
            ("pos_actual_open_dr4m", instrument_id, "2026-05-20T00:00:00Z", "2026-05-20T00:00:00Z"),
        )
        db.connection.execute(
            """
            INSERT INTO position_events(
                id, position_id, instrument_id, decision_id, event_type,
                quantity_delta, price, fees, slippage, metadata_json,
                created_at, actor_id, initial_risk_amount,
                realized_r_multiple, unrealized_r_multiple
            ) VALUES (?, ?, ?, NULL, 'open', 2.0, 0.55, 0.0, 0.0, '{}', ?,
                      'agent:test', 10.0, NULL, 0.325)
            """,
            ("pe_actual_open_dr4m", "pos_actual_open_dr4m", instrument_id, "2026-05-20T00:00:00Z"),
        )
        db.connection.commit()
    finally:
        db.close()


def _insert_latest_snapshot(home: Path, *, instrument_id: str, captured_at: str, snapshot_id: str) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            """
            INSERT INTO snapshots(
                id, instrument_id, captured_at, source, source_url,
                price, bid, ask, mid, implied_probability, created_at, actor_id
            ) VALUES (?, ?, ?, 'test_source', 'https://example.test/mark',
                      0.42, NULL, NULL, NULL, NULL, ?, 'agent:test')
            """,
            (snapshot_id, instrument_id, captured_at, captured_at),
        )
        db.connection.commit()
    finally:
        db.close()


def test_report_open_positions_no_positions_returns_positive_empty(home: Path) -> None:
    body = _call(home)

    assert body["ok"] is True
    assert body["data"]["summary"]["bucket"] == "open_positions"
    assert body["data"]["summary"]["count"] == 0
    assert body["data"]["summary"]["open_position_count"] == 0
    assert body["data"]["summary"]["caveat_codes"] == ["NO_OPEN_POSITIONS"]
    assert body["data"]["open_positions"] == []
    assert "Canonical open positions: zero." in body["data"]["agent_answer_hints"]


def test_report_open_positions_lists_open_paper_position_and_missing_mark(rich_home: Path) -> None:
    body = _call(rich_home, {"limit": 100})

    rows = body["data"]["open_positions"]
    assert rows
    paper = next(row for row in rows if row["kind"] == "paper" and "MISSING_MARK" in row["caveat_codes"])
    assert paper["status"] in {"open", "partial"}
    assert paper["position_id"]
    assert paper["instrument_id"]
    assert paper["net_quantity"] is not None
    assert "OPEN_PAPER_POSITION" in paper["caveat_codes"]
    assert "MISSING_MARK" in paper["caveat_codes"]
    assert paper["mark_state"] == "missing"
    assert body["data"]["summary"]["open_position_count"] == len(rows)


def test_report_open_positions_surfaces_latest_mark_and_stale_caveat(rich_home: Path) -> None:
    before = _call(rich_home, {"limit": 100})
    target = next(row for row in before["data"]["open_positions"] if row["kind"] == "paper")
    _insert_latest_snapshot(
        rich_home,
        instrument_id=target["instrument_id"],
        captured_at="2026-05-01T00:00:00Z",
        snapshot_id="snap_stale_open_position_dr4m",
    )

    body = _call(
        rich_home,
        {
            "instrument_id": target["instrument_id"],
            "limit": 10,
            "as_of": "2026-05-21T00:00:00Z",
            "stale_mark_threshold_days": 14,
        },
    )

    rows = body["data"]["open_positions"]
    assert rows
    row = next(row for row in rows if row["position_id"] == target["position_id"])
    assert row["latest_mark"] == {
        "snapshot_id": "snap_stale_open_position_dr4m",
        "captured_at": "2026-05-01T00:00:00Z",
        "source": "test_source",
        "source_url": "https://example.test/mark",
        "value_type": "price",
        "value": 0.42,
        "price": 0.42,
        "bid": None,
        "ask": None,
        "mid": None,
        "implied_probability": None,
    }
    assert row["mark_state"] == "stale"
    assert "STALE_MARK" in row["caveat_codes"]
    assert "MISSING_MARK" not in row["caveat_codes"]
    assert "STALE_MARK" in body["data"]["summary"]["caveat_codes"]
    assert body["data"]["summary"]["filter"]["as_of"] == "2026-05-21T00:00:00.000Z"


def test_report_open_positions_lists_actual_recorded_position_when_backed_by_projection(rich_home: Path) -> None:
    _insert_actual_open_position(rich_home)

    body = _call(rich_home, {"kind": "actual", "limit": 10})

    rows = body["data"]["open_positions"]
    assert len(rows) == 1
    row = rows[0]
    assert row["position_id"] == "pos_actual_open_dr4m"
    assert row["kind"] == "actual"
    assert "OPEN_ACTUAL_RECORDED_POSITION" in row["caveat_codes"]
    assert "MISSING_MARK" not in row["caveat_codes"]
    assert row["event_counts"]["total"] == 1


def test_report_open_positions_excludes_closed_positions_by_default(rich_home: Path) -> None:
    body = _call(rich_home, {"limit": 100})

    rows = body["data"]["open_positions"]
    assert rows
    assert all(row["status"] in {"open", "partial"} for row in rows)
    assert all(row["closed_at"] is None for row in rows)


def test_report_open_positions_schema_mentions_current_exposure_semantics() -> None:
    reg = __import__("trade_trace.core", fromlist=["default_registry"]).default_registry()
    registration = reg.get("report.open_positions")

    assert registration.json_schema is not None
    text = (registration.description + " " + registration.json_schema.get("description", "")).lower()
    assert "current exposure" in text
    assert "positions projection" in text
    assert "do not infer" in text
