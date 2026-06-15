"""Regression for trade-trace-rpb8: a NULL `outcome_label` in
`forecast_outcomes` (or in `outcomes`) used to crash both
`report.forecast_diagnostics` and `report.calibration` with an
`AttributeError` because both helpers called `.strip().lower()` on the
DB-returned label without a None guard.

The schema declares both columns `NOT NULL`, so corruption is the only way
to reach this state — but the report tools are expected to surface corrupt
rows as excluded cases, not crash the whole envelope. These tests poke a
NULL into the rows via the `writable_schema` pragma (drop NOT NULL on the
relevant column for the duration of the test) and then assert the reports
still return a clean envelope.
"""

from __future__ import annotations

from pathlib import Path

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _init_home(tmp_path) -> Path:
    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}).model_dump(mode="json")["ok"] is True
    return home


def _seed_scored_binary(home: Path) -> dict[str, str]:
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    snap = _envelope(home, "snapshot.add", {
        "instrument_id": inst["data"]["id"],
        "captured_at": "2026-05-18T14:00:00Z",
        "implied_probability": 0.55, "spread": 0.03, "volume": 100.0,
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    forecast = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.7},
            {"outcome_label": "no", "probability": 0.3},
        ],
    })
    decision = _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "thesis_id": thesis["data"]["id"],
        "forecast_id": forecast["data"]["id"], "snapshot_id": snap["data"]["id"],
        "type": "skip", "reason": "diagnostic fixture",
    })
    outcome = _envelope(home, "resolution.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
    })
    return {
        "forecast": forecast["data"]["id"],
        "decision": decision["data"]["id"],
        "outcome": outcome["data"]["id"],
    }


def _drop_not_null_and_set_label_to_null(home: Path, table: str, where_id: str) -> None:
    """Simulate historical/migration-drift corruption: drop the NOT NULL
    constraint on `outcome_label`, drop the append-only UPDATE trigger so
    the test can poke a NULL into one row, then perform the UPDATE. The
    test DB is throwaway, so we don't restore the trigger after."""

    # Phase 1: drop the trigger + rewrite the table's NOT NULL clause via
    # writable_schema. SQLite caches the parsed schema per connection, so
    # we close after the rewrite to force the next connection to re-read.
    db = open_database(db_path(home))
    try:
        conn = db.connection
        conn.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
        conn.execute("PRAGMA writable_schema = 1")
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        assert row is not None, f"table {table} not found"
        original = row[0]
        relaxed = original.replace("outcome_label TEXT NOT NULL", "outcome_label TEXT")
        assert relaxed != original, "expected outcome_label TEXT NOT NULL clause"
        conn.execute(
            "UPDATE sqlite_master SET sql=? WHERE type='table' AND name=?",
            (relaxed, table),
        )
        conn.execute("PRAGMA writable_schema = 0")
        conn.commit()
    finally:
        db.close()

    # Phase 2: fresh connection, NOT NULL is now gone, write the NULL.
    db = open_database(db_path(home))
    try:
        db.connection.execute(
            f"UPDATE {table} SET outcome_label = NULL WHERE id = ?",
            (where_id,),
        )
        db.connection.commit()
    finally:
        db.close()


def test_forecast_diagnostics_handles_null_forecast_outcome_label(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_scored_binary(home)

    # Pick one forecast_outcomes row to corrupt.
    db = open_database(db_path(home))
    try:
        fo_row = db.connection.execute(
            "SELECT id FROM forecast_outcomes WHERE forecast_id = ? LIMIT 1",
            (ids["forecast"],),
        ).fetchone()
        assert fo_row is not None
        fo_id = fo_row[0]
    finally:
        db.close()
    _drop_not_null_and_set_label_to_null(home, "forecast_outcomes", fo_id)

    env = _envelope(home, "report.forecast_diagnostics", {"min_sample": 1})
    assert env["ok"] is True, env
    data = env["data"]
    # The forecast is now unusable (NULL label) — it should be excluded
    # cleanly, not crash the report.
    assert data["summary"]["sample_size"] == 0, data
    counts = data["summary"]["exclusions"]["counts_by_reason"]
    assert counts.get("binary_probability_unusable", 0) >= 1, data["summary"]["exclusions"]


def test_calibration_handles_null_outcomes_label(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_scored_binary(home)
    _drop_not_null_and_set_label_to_null(home, "outcomes", ids["outcome"])

    env = _envelope(home, "report.calibration", {})
    assert env["ok"] is True, env
    # The corrupt row should be excluded; sample_size is 0 with the usual
    # "n < min_sample" warning.
    assert env["data"]["summary"]["sample_size"] == 0
    assert env["data"]["summary"]["sample_warning"] is not None


def test_calibration_handles_null_forecast_outcome_label(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_scored_binary(home)
    db = open_database(db_path(home))
    try:
        fo_row = db.connection.execute(
            "SELECT id FROM forecast_outcomes WHERE forecast_id = ? LIMIT 1",
            (ids["forecast"],),
        ).fetchone()
        fo_id = fo_row[0]
    finally:
        db.close()
    _drop_not_null_and_set_label_to_null(home, "forecast_outcomes", fo_id)

    env = _envelope(home, "report.calibration", {})
    assert env["ok"] is True, env
    assert env["data"]["summary"]["sample_size"] == 0
