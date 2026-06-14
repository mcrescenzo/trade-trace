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
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path
from trade_trace.tools.ledger import derive_scoring_state


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


def test_blind_committed_without_independence_blocks_autoscoring(home: Path):
    """End-to-end guard for the `_autoscore_pending_forecasts` SQL filter at
    `_scoring.py:113-135`: a forecast that is `forecast.blind_committed` but
    whose independence lock is NOT proven must be INELIGIBLE for auto-scoring
    when a `resolved_final` outcome lands — otherwise an agent could see the
    outcome, then back-date a blind-committed forecast to game its Brier score.

    Phase 1 pins the "blocked" side of the gate (blind commit, no reveal →
    outcome lands → nothing scores, state stays `pending`). Phase 2 pins the
    "unblocked" side (reveal proves independence → re-firing the outcome
    trigger now scores). Without this test a refactor that drops the
    `NOT EXISTS(independence_proven=1)` clause would pass silently.
    """

    inst, forecast, snapshot = _setup(home)

    # Blind-commit the forecast but do NOT reveal: independence is unproven.
    blind = _call(home, "forecast.commit_blind", {"forecast_id": forecast})
    assert blind["ok"], blind
    proof = _call(home, "forecast.independence", {"forecast_id": forecast})
    assert proof["data"]["status"] == "blind_committed"
    assert proof["data"]["independence_proven"] is False

    # -- Phase 1: a safe, auto-scoreable final outcome lands -----------------
    out1 = _call(
        home, "outcome.add",
        {
            "instrument_id": inst,
            "resolved_at": "2027-02-01T00:00:00Z",
            "outcome_label": "yes",
            "status": "resolved_final",
            "confidence": 0.99,
            "idempotency_key": "blind-gate-phase1",
        },
    )
    assert out1["ok"], out1
    # The outcome itself IS auto-scoreable (status/confidence/label all pass);
    # the ONLY thing blocking the score is the unproven independence lock —
    # this isolates the gate under test from the finality predicate.
    assert out1["data"]["auto_scoreable"] is True
    assert out1["data"]["auto_score_skipped_reason"] is None
    assert out1["data"]["auto_scored_forecasts"] == []

    db = open_database(db_path(home))
    try:
        assert derive_scoring_state(db.connection, forecast) == "pending"
    finally:
        db.close()

    # -- Phase 2: prove independence, then re-fire the outcome trigger -------
    revealed = _call(
        home, "forecast.reveal_snapshot",
        {"forecast_id": forecast, "snapshot_id": snapshot},
    )
    assert revealed["ok"], revealed
    assert revealed["data"]["independence_proven"] is True

    # A fresh idempotency_key writes a new resolved_final outcome row, which
    # re-triggers _autoscore_pending_forecasts. Now that independence is
    # proven the forecast passes the gate and scores.
    out2 = _call(
        home, "outcome.add",
        {
            "instrument_id": inst,
            "resolved_at": "2027-02-01T00:00:00Z",
            "outcome_label": "yes",
            "status": "resolved_final",
            "confidence": 0.99,
            "idempotency_key": "blind-gate-phase2",
        },
    )
    assert out2["ok"], out2
    scored = out2["data"]["auto_scored_forecasts"]
    assert len(scored) == 1
    assert scored[0]["forecast_id"] == forecast
    # yes-probability 0.7, outcome yes → Brier (0.7 - 1.0)**2 == 0.09.
    assert scored[0]["score"] == pytest.approx(0.09)
    assert scored[0]["failure_reason"] is None

    db = open_database(db_path(home))
    try:
        assert derive_scoring_state(db.connection, forecast) == "scored"
    finally:
        db.close()


def _anchor_count(home: Path, forecast: str) -> int:
    db = open_database(db_path(home))
    try:
        row = db.connection.execute(
            "SELECT COUNT(*) FROM forecast_snapshot_anchor WHERE forecast_id = ?",
            (forecast,),
        ).fetchone()
        return int(row[0])
    finally:
        db.close()


def test_anchor_to_different_snapshot_raises_invariant_violation(home: Path):
    """Re-anchoring a forecast to a *different* snapshot must fail with
    INVARIANT_VIOLATION and steer the caller to forecast.supersede — covers the
    different-snapshot branch in `_anchor_forecast_to_snapshot_in_transaction`
    (forecast.py:206-210). Without this guard an agent could silently rebind a
    committed forecast to a more-favorable market price after the fact.
    """
    inst, forecast, snapshot_a = _setup(home)
    snapshot_b = _envelope(
        home, "snapshot.add",
        {"instrument_id": inst, "captured_at": "2027-01-03T00:00:00Z", "source": "manual", "mid": 0.6},
    )["data"]["id"]
    assert snapshot_b != snapshot_a

    first = _call(home, "forecast.anchor_to_snapshot", {"forecast_id": forecast, "snapshot_id": snapshot_a, "idempotency_key": "anchor-a"})
    assert first["ok"], first

    env = _call(home, "forecast.anchor_to_snapshot", {"forecast_id": forecast, "snapshot_id": snapshot_b, "idempotency_key": "anchor-b"})
    assert env["ok"] is False, env
    assert env["error"]["code"] == "INVARIANT_VIOLATION"
    details = env["error"]["details"]
    assert details["existing_snapshot_id"] == snapshot_a
    assert details["requested_snapshot_id"] == snapshot_b
    assert details["correction_path"] == "forecast.supersede"

    # The rejected re-anchor must not have inserted a row: still exactly one,
    # still bound to snapshot A.
    assert _anchor_count(home, forecast) == 1


def test_anchor_to_same_snapshot_twice_is_idempotent_replay(home: Path):
    """Anchoring a forecast to the *same* snapshot twice must return ok=True
    with idempotent_replay=True and insert no duplicate row — covers the
    idempotent-replay branch in `_anchor_forecast_to_snapshot_in_transaction`
    (forecast.py:204-205). Distinct idempotency_keys ensure the second call
    reaches the handler (not a dispatcher-level key collision) so the row-level
    replay check is what is exercised.
    """
    _, forecast, snapshot = _setup(home)

    first = _call(home, "forecast.anchor_to_snapshot", {"forecast_id": forecast, "snapshot_id": snapshot, "idempotency_key": "anchor-1"})
    assert first["ok"], first
    assert _anchor_count(home, forecast) == 1
    anchor_id = first["data"]["id"]

    second = _call(home, "forecast.anchor_to_snapshot", {"forecast_id": forecast, "snapshot_id": snapshot, "idempotency_key": "anchor-2"})
    assert second["ok"], second
    assert second["data"]["idempotent_replay"] is True
    assert second["data"]["id"] == anchor_id
    assert second["data"]["snapshot_id"] == snapshot

    # No duplicate row from the replay.
    assert _anchor_count(home, forecast) == 1


def test_anchor_to_nonexistent_snapshot_raises_not_found(home: Path):
    """Anchoring a forecast to a snapshot_id that does not exist must fail with
    NOT_FOUND and echo the offending snapshot_id in error.details — covers the
    missing-snapshot branch in `_anchor_forecast_to_snapshot_in_transaction`
    (forecast.py:198-199), reached here via the public `forecast.anchor_to_snapshot`
    tool. The forecast itself is valid, so this isolates the snapshot lookup from
    the separate forecast_id existence check in `_forecast_anchor_to_snapshot`.
    """
    _, forecast, _ = _setup(home)

    env = _call(
        home, "forecast.anchor_to_snapshot",
        {"forecast_id": forecast, "snapshot_id": "snp_missing", "idempotency_key": "anchor-missing"},
    )
    assert env["ok"] is False, env
    assert env["error"]["code"] == "NOT_FOUND"
    assert env["error"]["details"]["snapshot_id"] == "snp_missing"

    # The failed anchor must not have inserted any row.
    assert _anchor_count(home, forecast) == 0
