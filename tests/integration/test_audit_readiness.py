from __future__ import annotations

from pathlib import Path

from tests._mcp_helpers import mcp_default as _mcp


def test_audit_readiness_empty_journal_safe(home: Path):
    env = _mcp(home, "report.audit_readiness", {})
    assert env.ok, env
    assert env.data["summary"]["sample_size"] == 0
    assert env.data["summary"]["ready"] is False
    assert env.data["summary"]["sample_warning"] == "no_data"
    assert env.data["issues"] == []


def test_audit_readiness_surfaces_prediction_market_blockers_and_warnings(home: Path):
    venue = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue,
        "asset_class": "prediction_market",
        "title": "Will X happen?",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {"instrument_id": inst, "side": "yes", "body": "because"}).data["id"]
    fcst = _mcp(home, "forecast.add", {
        "thesis_id": thesis,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.55},
            {"outcome_label": "no", "probability": 0.45},
        ],
    }).data["id"]
    old_snap = _mcp(home, "snapshot.add", {
        "instrument_id": inst,
        "captured_at": "2026-01-01T00:00:00Z",
        "price": 0.55,
    }).data["id"]
    dec = _mcp(home, "decision.add", {
        "type": "actual_enter",
        "instrument_id": inst,
        "thesis_id": thesis,
        "forecast_id": fcst,
        "snapshot_id": old_snap,
        "side": "yes",
        "quantity": 1,
        "price": 0.55,
        "idempotency_key": "00000000-0000-4000-8000-566000000001",
    }).data["id"]
    stale_src = _mcp(home, "source.add", {
        "kind": "url",
        "stance": "supports",
        "uri": "https://example.test/old",
        "freshness_at": "2025-01-01T00:00:00Z",
        "idempotency_key": "00000000-0000-4000-8000-566000000002",
    }).data["id"]
    con_src = _mcp(home, "source.add", {
        "kind": "url",
        "stance": "contradicts",
        "uri": "https://example.test/no",
        "idempotency_key": "00000000-0000-4000-8000-566000000003",
    }).data["id"]
    _mcp(home, "source.attach_to_thesis", {"source_id": stale_src, "target_id": thesis, "idempotency_key": "00000000-0000-4000-8000-566000000004"})
    _mcp(home, "source.attach_to_thesis", {"source_id": con_src, "target_id": thesis, "idempotency_key": "00000000-0000-4000-8000-566000000005"})

    env = _mcp(home, "report.audit_readiness", {"stale_snapshot_threshold_days": 7, "stale_source_threshold_days": 7})
    assert env.ok, env
    data = env.data
    assert data["summary"]["ready"] is False
    by_check = {issue["check"]: issue for issue in data["issues"]}
    assert by_check["missing_resolution_rule_provenance"]["severity"] == "blocking"
    assert by_check["stale_snapshot"]["severity"] == "warning"
    assert by_check["missing_market_microstructure"]["severity"] == "warning"
    assert by_check["stale_source"]["severity"] == "warning"
    assert by_check["contradictory_sources"]["severity"] == "blocking"
    assert dec in by_check["stale_snapshot"]["sample_ids"]["decisions"]


def test_audit_readiness_ignores_non_prediction_market_entered_decisions(home: Path):
    venue = _mcp(home, "venue.add", {"name": "Broker", "kind": "broker"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue,
        "asset_class": "equity",
        "symbol": "XYZ",
        "title": "XYZ Corp",
    }).data["id"]
    _mcp(home, "decision.add", {
        "type": "actual_enter",
        "instrument_id": inst,
        "side": "long",
        "quantity": 1,
        "price": 10,
        "idempotency_key": "00000000-0000-4000-8000-566000000006",
    })

    env = _mcp(home, "report.audit_readiness", {})
    assert env.ok, env
    assert env.data["summary"]["sample_size"] == 0
    assert env.data["summary"]["sample_warning"] == "no_data"
    assert env.data["issues"] == []


def test_audit_readiness_registered_read_only_schema(home: Path):
    env = _mcp(home, "tool.schema", {"tool": "report.audit_readiness"})
    assert env.ok, env
    tool = env.data
    assert tool["tool"] == "report.audit_readiness"
    assert tool["is_write"] is False
    assert tool["json_schema"]["properties"]["stale_snapshot_threshold_days"]["minimum"] == 0
