from __future__ import annotations

from pathlib import Path

from trade_trace.contracts.envelope import SuccessEnvelope
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _mcp(home: str, tool: str, args: dict[str, object]) -> SuccessEnvelope:
    env = mcp_call(tool, {"home": home, **args}, actor_id="agent:test")
    assert isinstance(env, SuccessEnvelope), env
    return env


def _seed_pm_market(home: str, external_id: str = "pm-finality-1") -> str:
    market = _mcp(home, "market.bind", {
        "source": "polymarket",
        "external_id": external_id,
        "title": "Will finality modeling work?",
        "question": "Will finality modeling work?",
        "state": "closed_for_trading",
        "mechanism": "clob",
        "bound_via": "manual",
        "close_at": "2020-01-01T00:00:00Z",
        "resolution_rule": {"text": "Official rules decide YES.", "provenance": "caller_supplied"},
        "condition_id": f"0x{external_id}",
        "outcome_ids_by_label": {"yes": "1", "no": "2"},
    }).data
    return str(market["instrument_id"])


def _seed_binary_forecast(home: str, instrument_id: str) -> str:
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": instrument_id,
        "side": "yes",
        "body": "local calibration thesis",
    }).data
    forecast = _mcp(home, "forecast.add", {
        "thesis_id": thesis["id"],
        "kind": "binary",
        "yes_label": "yes",
        "resolution_at": "2020-01-02T00:00:00Z",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    }).data
    return str(forecast["id"])


def test_polymarket_finality_statuses_are_local_evidence_and_reported(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok
    instrument_id = _seed_pm_market(home)

    provisional = _mcp(home, "outcome.add", {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-02T00:00:00Z",
        "outcome_label": "yes",
        "status": "proposed",
        "source": "polymarket_import",
        "confidence": 0.8,
        "metadata_json": {
            "as_of": "2020-01-02T00:00:00Z",
            "retrieved_at": "2020-01-02T00:01:00Z",
            "imported_at": "2020-01-02T00:02:00Z",
            "provenance": {"kind": "official_rule", "ref": "pm-finality-1"},
        },
    }).data
    assert provisional["finality_uncertain"] is True
    assert provisional["auto_scored_forecasts"] == []
    assert provisional["auto_scoreable"] is False

    imported = _mcp(home, "outcome.add", {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-03T00:00:00Z",
        "outcome_label": "yes",
        "status": "imported_settled",
        "source": "local_import",
        "confidence": 0.95,
        "metadata_json": {"imported_at": "2020-01-03T00:01:00Z", "evidence_only": True},
    }).data
    assert imported["finality_uncertain"] is True
    assert imported["auto_scoreable"] is False

    lifecycle = _mcp(home, "report.market_lifecycle", {}).data
    assert instrument_id in lifecycle["summary"]["metrics"]["resolution_due_market_ids"]
    assert instrument_id in lifecycle["summary"]["metrics"]["finality_uncertain_market_ids"]

    quality = _mcp(home, "report.resolution_quality", {}).data
    statuses = quality["summary"]["metrics"]["status_counts"]
    assert statuses["proposed"] == 1
    assert statuses["imported_settled"] == 1
    assert quality["summary"]["metrics"]["finality_uncertain_count"] == 2
    assert all("finality_uncertain" in group["caveat_codes"] for group in quality["groups"])


def test_resolved_final_requires_explicit_high_confidence_to_auto_score(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok
    instrument_id = _seed_pm_market(home, "pm-finality-confidence")
    forecast_id = _seed_binary_forecast(home, instrument_id)

    missing_conf = _mcp(home, "outcome.add", {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-02T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "idempotency_key": "missing-confidence",
    }).data
    assert missing_conf["auto_scoreable"] is False
    assert missing_conf["finality_uncertain"] is True
    assert missing_conf["auto_scored_forecasts"] == []
    pending = _mcp(home, "resolve.pending", {}).data
    assert forecast_id in {item["forecast_id"] for item in pending["items"]}

    low_conf = _mcp(home, "outcome.add", {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-03T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.89,
    }).data
    assert low_conf["auto_scoreable"] is False
    assert low_conf["finality_uncertain"] is True
    assert low_conf["auto_scored_forecasts"] == []

    high_conf = _mcp(home, "outcome.add", {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-04T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": "0.90",
    }).data
    assert high_conf["auto_scoreable"] is True
    assert high_conf["finality_uncertain"] is False
    assert [score["forecast_id"] for score in high_conf["auto_scored_forecasts"]] == [forecast_id]


def test_malformed_confidence_resolved_final_does_not_score_or_hide_pending(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok
    instrument_id = _seed_pm_market(home, "pm-finality-malformed-confidence")
    forecast_id = _seed_binary_forecast(home, instrument_id)

    db = open_database(db_path(Path(home)))
    try:
        db.connection.execute(
            """
            INSERT INTO outcomes(
                id, instrument_id, resolved_at, outcome_label, outcome_value,
                status, source, confidence, metadata_json, created_at, actor_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "out_malformed_confidence",
                instrument_id,
                "2020-01-02T00:00:00Z",
                "yes",
                None,
                "resolved_final",
                "test",
                "0.95abc",
                "{}",
                "2020-01-02T00:01:00Z",
                "agent:test",
            ),
        )
        db.connection.commit()
    finally:
        db.close()

    late_forecast = _seed_binary_forecast(home, instrument_id)
    pending = _mcp(home, "resolve.pending", {}).data
    pending_ids = {item["forecast_id"] for item in pending["items"]}
    assert forecast_id in pending_ids
    assert late_forecast in pending_ids

    quality = _mcp(home, "report.resolution_quality", {}).data
    group = next(g for g in quality["groups"] if g["resolution"]["outcome_id"] == "out_malformed_confidence")
    assert group["metrics"]["finality_uncertain"] is True
    assert "finality_uncertain" in group["caveat_codes"]

    lifecycle = _mcp(home, "report.market_lifecycle", {}).data
    market = next(g for g in lifecycle["groups"] if g["key"] == instrument_id)
    assert market["market"]["finality_uncertain"] is True
    assert instrument_id in lifecycle["summary"]["metrics"]["finality_uncertain_market_ids"]


def test_outcome_add_idempotent_replay_preserves_finality_shape(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok
    instrument_id = _seed_pm_market(home, "pm-finality-replay")
    args = {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-02T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.99,
        "idempotency_key": "finality-replay",
    }

    first = _mcp(home, "outcome.add", args).data
    replay = _mcp(home, "outcome.add", args).data
    assert replay["id"] == first["id"]
    assert replay["auto_scoreable"] == first["auto_scoreable"] is True
    assert replay["finality_uncertain"] == first["finality_uncertain"] is False
    assert set(first) == set(replay)
