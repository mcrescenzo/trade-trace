"""forecast.commit_blind / reveal_snapshot / independence (trade-trace-4kec.9).

Pre-commit forecast independence lock: prove a forecast was made blind to the
market price before the snapshot was revealed. Append-only, ordering enforced
at write time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _setup(home: Path) -> tuple[str, str, str]:
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})["data"]["id"]
    inst = _envelope(
        home, "instrument.add",
        {"venue_id": venue, "asset_class": "prediction_market", "title": "Will X?"},
    )["data"]["id"]
    thesis = _envelope(home, "thesis.add", {"instrument_id": inst, "side": "yes", "body": "t"})["data"]["id"]
    forecast = _envelope(
        home, "forecast.add",
        {
            "thesis_id": thesis,
            "kind": "binary",
            "yes_label": "yes",
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.7},
                {"outcome_label": "no", "probability": 0.3},
            ],
        },
    )["data"]["id"]
    snapshot = _envelope(
        home, "snapshot.add",
        {"instrument_id": inst, "captured_at": "2027-01-02T00:00:00Z", "source": "manual", "mid": 0.5},
    )["data"]["id"]
    return inst, forecast, snapshot


def _call(home: Path, tool: str, args: dict):
    return mcp_call(tool, {"home": str(home), **args}, actor_id="agent:default").model_dump(mode="json", exclude_none=True)


def test_independence_tools_registered_public():
    names = set(default_registry().public_names())
    assert {"forecast.commit_blind", "forecast.reveal_snapshot", "forecast.independence"}.issubset(names)


def test_blind_commit_then_reveal_proves_independence(home: Path):
    _, forecast, snapshot = _setup(home)

    blind = _call(home, "forecast.commit_blind", {"forecast_id": forecast})
    assert blind["ok"], blind
    commit_seq = blind["data"]["blind_commit_seq"]

    revealed = _call(home, "forecast.reveal_snapshot", {"forecast_id": forecast, "snapshot_id": snapshot})
    assert revealed["ok"], revealed
    data = revealed["data"]
    assert data["snapshot_id"] == snapshot
    assert data["independence_proven"] is True
    assert data["reveal_seq"] > commit_seq

    proof = _call(home, "forecast.independence", {"forecast_id": forecast})
    assert proof["ok"]
    assert proof["data"]["status"] == "revealed"
    assert proof["data"]["independence_proven"] is True


def test_independence_status_progression(home: Path):
    _, forecast, snapshot = _setup(home)

    before = _call(home, "forecast.independence", {"forecast_id": forecast})
    assert before["data"]["status"] == "no_blind_commit"
    assert before["data"]["independence_proven"] is False

    _call(home, "forecast.commit_blind", {"forecast_id": forecast})
    mid = _call(home, "forecast.independence", {"forecast_id": forecast})
    assert mid["data"]["status"] == "blind_committed"
    assert mid["data"]["independence_proven"] is False

    _call(home, "forecast.reveal_snapshot", {"forecast_id": forecast, "snapshot_id": snapshot})
    after = _call(home, "forecast.independence", {"forecast_id": forecast})
    assert after["data"]["status"] == "revealed"


def test_reveal_requires_blind_commit_first(home: Path):
    _, forecast, snapshot = _setup(home)
    env = _call(home, "forecast.reveal_snapshot", {"forecast_id": forecast, "snapshot_id": snapshot})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_commit_blind_rejects_already_anchored_forecast(home: Path):
    inst, forecast, snapshot = _setup(home)
    # Bind a snapshot via the (frozen but dispatchable) anchor tool: the forecast
    # is then no longer blind.
    anchored = _call(home, "forecast.anchor_to_snapshot", {"forecast_id": forecast, "snapshot_id": snapshot, "idempotency_key": "anchor-1"})
    assert anchored["ok"], anchored
    env = _call(home, "forecast.commit_blind", {"forecast_id": forecast})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_commit_blind_is_idempotent(home: Path):
    _, forecast, _ = _setup(home)
    first = _call(home, "forecast.commit_blind", {"forecast_id": forecast})
    second = _call(home, "forecast.commit_blind", {"forecast_id": forecast})
    assert first["data"]["blind_commit_seq"] == second["data"]["blind_commit_seq"]
    assert second["data"]["already_committed"] is True


def test_reveal_is_idempotent_and_lock_append_only(home: Path):
    _, forecast, snapshot = _setup(home)
    _call(home, "forecast.commit_blind", {"forecast_id": forecast})
    first = _call(home, "forecast.reveal_snapshot", {"forecast_id": forecast, "snapshot_id": snapshot})
    second = _call(home, "forecast.reveal_snapshot", {"forecast_id": forecast, "snapshot_id": snapshot})
    assert first["data"]["id"] == second["data"]["id"]

    import sqlite3

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(home))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "UPDATE forecast_independence_locks SET independence_proven = 0 WHERE forecast_id = ?",
                (forecast,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "DELETE FROM forecast_independence_locks WHERE forecast_id = ?", (forecast,)
            )
    finally:
        db.close()


def test_reveal_rejects_missing_snapshot(home: Path):
    _, forecast, _ = _setup(home)
    _call(home, "forecast.commit_blind", {"forecast_id": forecast})
    env = _call(home, "forecast.reveal_snapshot", {"forecast_id": forecast, "snapshot_id": "snp_missing"})
    assert env["ok"] is False
    assert env["error"]["code"] == "NOT_FOUND"
