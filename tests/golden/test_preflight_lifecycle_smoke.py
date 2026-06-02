from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from tools.tracelab.reconcile import reconcile
from trade_trace.dispatch_trace import ENABLE_ENV, PATH_ENV, REPLAY_SECRET_ENV
from trade_trace.mcp_server import mcp_call

ACTOR_ID = "agent:golden-preflight"
SECRET = "synthetic-golden-preflight-secret"


def _call(tool: str, args: dict[str, Any], *, actor_id: str = ACTOR_ID):
    env = mcp_call(tool, args, actor_id=actor_id)
    assert env.ok, (tool, env)
    return cast(Any, env).data


def _score_rows(home: Path, forecast_id: str | None = None) -> list[sqlite3.Row]:
    conn = sqlite3.connect(home / "trade-trace.sqlite")
    conn.row_factory = sqlite3.Row
    try:
        if forecast_id is None:
            return conn.execute("SELECT * FROM forecast_scores ORDER BY id").fetchall()
        return conn.execute("SELECT * FROM forecast_scores WHERE forecast_id = ? ORDER BY id", (forecast_id,)).fetchall()
    finally:
        conn.close()


def _seed_forecast(home: Path, slug: str, *, reveal: bool = True) -> dict[str, str]:
    market = _call(
        "market.bind",
        {
            "home": str(home),
            "source": "polymarket",
            "external_id": f"golden-{slug}",
            "state": "open",
            "mechanism": "clob",
            "bound_via": "manual",
            "title": f"Golden preflight {slug}",
            "condition_id": f"{int(slug, 16):064x}" if all(c in "0123456789abcdef" for c in slug) else "1" * 64,
            "outcome_ids_by_label": {"yes": f"yes-{slug}", "no": f"no-{slug}"},
            "idempotency_key": f"golden:{slug}:bind",
        },
    )
    instrument_id = market["instrument_id"]
    snapshot = _call(
        "snapshot.add",
        {
            "home": str(home),
            "instrument_id": instrument_id,
            "captured_at": "2026-06-01T00:00:00Z",
            "source": "manual",
            "price": 0.62,
            "bid": 0.61,
            "ask": 0.63,
            "tradable": True,
            "idempotency_key": f"golden:{slug}:snapshot",
        },
    )
    thesis = _call(
        "thesis.add",
        {
            "home": str(home),
            "instrument_id": instrument_id,
            "side": "yes",
            "body": "Deterministic golden smoke thesis.",
            "idempotency_key": f"golden:{slug}:thesis",
        },
    )
    forecast = _call(
        "forecast.add",
        {
            "home": str(home),
            "thesis_id": thesis["id"],
            "kind": "binary",
            "yes_label": "yes",
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.7},
                {"outcome_label": "no", "probability": 0.3},
            ],
            "idempotency_key": f"golden:{slug}:forecast",
        },
    )
    _call("forecast.commit_blind", {"home": str(home), "forecast_id": forecast["id"], "as_of": "2026-06-01T00:01:00Z", "idempotency_key": f"golden:{slug}:commit"})
    if reveal:
        _call("forecast.reveal_snapshot", {"home": str(home), "forecast_id": forecast["id"], "snapshot_id": snapshot["id"], "as_of": "2026-06-01T00:02:00Z", "idempotency_key": f"golden:{slug}:reveal"})
    _call(
        "forecast.interpret_resolution",
        {
            "home": str(home),
            "forecast_id": forecast["id"],
            "interpreted_yes_condition": "The market contract resolves to YES.",
            "interpreted_resolution_source": "market_contract",
            "expected_outcome_label": "yes",
            "as_of": "2026-06-01T00:03:00Z",
            "idempotency_key": f"golden:{slug}:interpret",
        },
    )
    _call(
        "decision.add",
        {
            "home": str(home),
            "type": "paper_enter",
            "instrument_id": instrument_id,
            "thesis_id": thesis["id"],
            "forecast_id": forecast["id"],
            "snapshot_id": snapshot["id"],
            "side": "yes",
            "quantity": 1,
            "price": 0.62,
            "reason": "Golden preflight paper entry.",
            "idempotency_key": f"golden:{slug}:decision",
        },
    )
    return {"instrument_id": instrument_id, "forecast_id": forecast["id"]}


def test_preflight_golden_scoreable_lifecycle_reports_and_trace_reconcile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}, actor_id=ACTOR_ID).ok
    monkeypatch.setenv("TRADE_TRACE_HOME", str(home))
    trace_path = tmp_path / "dispatch-trace.jsonl"
    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.setenv(PATH_ENV, str(trace_path))
    monkeypatch.setenv(REPLAY_SECRET_ENV, SECRET)

    ids = _seed_forecast(home, "a")
    outcome = _call(
        "resolution.add",
        {
            "home": str(home),
            "instrument_id": ids["instrument_id"],
            "resolved_at": "2026-06-02T00:00:00Z",
            "outcome_label": "yes",
            "status": "resolved_final",
            "confidence": 0.99,
            "idempotency_key": "golden:a:resolution",
        },
    )

    rows = _score_rows(home, ids["forecast_id"])
    assert len(rows) == 1
    assert outcome["auto_scored_forecasts"][0]["forecast_id"] == ids["forecast_id"]

    report = reconcile(trace_path, home / "trade-trace.sqlite", replay_secret=SECRET)
    assert report["trace_count"] > 0
    assert set(report["buckets"]) <= {"request_id_events", "idempotent_replay_zero_new_rows"}
    trace_text = trace_path.read_text(encoding="utf-8")
    assert "idempotency_key" not in trace_text
    assert SECRET not in trace_text
    assert "golden:a:" not in trace_text

    monkeypatch.delenv(ENABLE_ENV)
    for report_tool in ("report.calibration", "report.coach", "report.pnl"):
        env = mcp_call(report_tool, {"home": str(home)}, actor_id=ACTOR_ID)
        assert env.ok, (report_tool, env)


@pytest.mark.parametrize(
    ("slug", "resolution_args", "reveal"),
    [
        ("b", {"outcome_label": "yes", "status": "resolved_final"}, True),
        ("c", {"outcome_label": "yes", "status": "resolved_final", "confidence": 0.89}, True),
        ("d", {"outcome_label": "maybe", "status": "resolved_final", "confidence": 0.99}, True),
        ("e", {"outcome_label": "yes", "status": "resolved_final", "confidence": 0.99}, False),
    ],
)
def test_preflight_golden_negative_paths_do_not_write_forecast_scores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, slug: str, resolution_args: dict[str, Any], reveal: bool) -> None:
    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}, actor_id=ACTOR_ID).ok
    monkeypatch.setenv("TRADE_TRACE_HOME", str(home))
    ids = _seed_forecast(home, slug, reveal=reveal)

    env = mcp_call(
        "resolution.add",
        {
            "home": str(home),
            "instrument_id": ids["instrument_id"],
            "resolved_at": "2026-06-02T00:00:00Z",
            "idempotency_key": f"golden:{slug}:resolution",
            **resolution_args,
        },
        actor_id=ACTOR_ID,
    )
    assert env.ok, env
    assert _score_rows(home, ids["forecast_id"]) == []


def test_preflight_golden_resolution_without_forecast_does_not_write_forecast_scores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}, actor_id=ACTOR_ID).ok
    monkeypatch.setenv("TRADE_TRACE_HOME", str(home))
    market = _call(
        "market.bind",
        {
            "home": str(home),
            "source": "polymarket",
            "external_id": "golden-no-forecast",
            "state": "open",
            "mechanism": "clob",
            "bound_via": "manual",
            "title": "Golden preflight no forecast",
            "condition_id": "f" * 64,
            "outcome_ids_by_label": {"yes": "yes-empty", "no": "no-empty"},
            "idempotency_key": "golden:no-forecast:bind",
        },
    )
    env = mcp_call(
        "resolution.add",
        {
            "home": str(home),
            "instrument_id": market["instrument_id"],
            "resolved_at": "2026-06-02T00:00:00Z",
            "outcome_label": "yes",
            "status": "resolved_final",
            "confidence": 0.99,
            "idempotency_key": "golden:no-forecast:resolution",
        },
        actor_id=ACTOR_ID,
    )
    assert env.ok, env
    assert _score_rows(home) == []
