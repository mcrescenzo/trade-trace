"""Agent-continuity foundation provenance contracts.

These tests pin Epic A behavior: run/session provenance that is advertised to
agents must actually persist, and reports that claim to filter/group by run
metadata must apply those fields to SQL rather than merely echoing them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _ok(tool: str, args: dict[str, Any]):
    env = mcp_call(tool, args)
    assert env.ok, env
    return env.model_dump(mode="json", exclude_none=True)["data"]


def _initialized_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    _ok("journal.init", {"home": str(home)})
    return home


def _instrument(home: Path, suffix: str) -> str:
    venue = _ok(
        "venue.add",
        {
            "home": str(home),
            "name": f"PM {suffix}",
            "kind": "prediction_market",
            "idempotency_key": f"00000000-0000-4000-8000-venue-{suffix}",
        },
    )
    instrument = _ok(
        "instrument.add",
        {
            "home": str(home),
            "venue_id": venue["id"],
            "asset_class": "prediction_market",
            "title": f"Event {suffix}",
            "idempotency_key": f"00000000-0000-4000-8000-instr-{suffix}",
        },
    )
    return instrument["id"]


def _scored_forecast(home: Path, suffix: str, *, agent_id: str, run_id: str) -> str:
    instrument_id = _instrument(home, suffix)
    common = {
        "home": str(home),
        "agent_id": agent_id,
        "model_id": "model:test",
        "environment": "paper",
        "run_id": run_id,
    }
    thesis = _ok(
        "thesis.add",
        {
            **common,
            "instrument_id": instrument_id,
            "side": "yes",
            "body": f"thesis {suffix}",
            "idempotency_key": f"00000000-0000-4000-8000-thesis-{suffix}",
        },
    )
    forecast = _ok(
        "forecast.add",
        {
            **common,
            "thesis_id": thesis["id"],
            "kind": "binary",
            "yes_label": "yes",
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.7},
                {"outcome_label": "no", "probability": 0.3},
            ],
            "idempotency_key": f"00000000-0000-4000-8000-forecast-{suffix}",
        },
    )
    _ok(
        "outcome.add",
        {
            **common,
            "instrument_id": instrument_id,
            "resolved_at": "2026-05-22T20:00:00.000Z",
            "outcome_label": "yes",
            "status": "resolved_final",
            "idempotency_key": f"00000000-0000-4000-8000-outcome-{suffix}",
        },
    )
    return forecast["id"]


def test_snapshot_and_source_persist_agent_run_provenance(tmp_path: Path):
    home = _initialized_home(tmp_path)
    instrument_id = _instrument(home, "prov")
    common = {
        "agent_id": "agent:cron-scout",
        "model_id": "model:test-llm",
        "environment": "simulation",
        "run_id": "run:2026-05-22T14:00Z",
    }

    snapshot = _ok(
        "snapshot.add",
        {
            "home": str(home),
            "instrument_id": instrument_id,
            "captured_at": "2026-05-22T14:30:00.000Z",
            "price": 0.52,
            **common,
            "idempotency_key": "00000000-0000-4000-8000-snapshot-prov",
        },
    )
    source = _ok(
        "source.add",
        {
            "home": str(home),
            "kind": "note",
            "title": "caller supplied note",
            **common,
            "idempotency_key": "00000000-0000-4000-8000-source-prov",
        },
    )

    db = open_database(db_path(home), create_parent=False)
    try:
        snapshot_row = db.connection.execute(
            "SELECT agent_id, model_id, environment, run_id FROM snapshots WHERE id = ?",
            (snapshot["id"],),
        ).fetchone()
        source_row = db.connection.execute(
            "SELECT agent_id, model_id, environment, run_id FROM sources WHERE id = ?",
            (source["id"],),
        ).fetchone()
    finally:
        db.close()

    assert tuple(snapshot_row) == tuple(common.values())
    assert tuple(source_row) == tuple(common.values())


def test_calibration_filter_and_compare_group_by_run_metadata(tmp_path: Path):
    home = _initialized_home(tmp_path)
    forecast_a = _scored_forecast(home, "run-a", agent_id="agent:alpha", run_id="run:a")
    forecast_b = _scored_forecast(home, "run-b", agent_id="agent:beta", run_id="run:b")

    filtered = _ok(
        "report.calibration",
        {
            "home": str(home),
            "filter": {"actors": {"run_id": ["run:a"]}},
            "min_sample": 1,
        },
    )
    assert filtered["summary"]["sample_size"] == 1
    assert filtered["summary"]["filter"]["actors"]["run_id"] == ["run:a"]

    compared = _ok(
        "report.compare",
        {
            "home": str(home),
            "base_report": "calibration",
            "group_by": "agent_id",
            "filter": {},
            "min_sample": 1,
        },
    )
    groups = {group["key"]: group for group in compared["groups"]}
    assert {"agent:alpha", "agent:beta"}.issubset(groups)
    assert groups["agent:alpha"]["filter"]["actors"]["agent_id"] == ["agent:alpha"]
    assert forecast_a in groups["agent:alpha"]["record_ids"]["forecasts"]

    compared_by_run = _ok(
        "report.compare",
        {
            "home": str(home),
            "base_report": "calibration",
            "group_by": "run_id",
            "filter": {},
            "min_sample": 1,
        },
    )
    run_groups = {group["key"]: group for group in compared_by_run["groups"]}
    assert {"run:a", "run:b"}.issubset(run_groups)
    assert forecast_b in run_groups["run:b"]["record_ids"]["forecasts"]
