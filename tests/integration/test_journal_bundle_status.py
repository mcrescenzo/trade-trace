from __future__ import annotations

import json
from pathlib import Path

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.contracts.envelope import ErrorEnvelope, SuccessEnvelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_tool_specs
from trade_trace.security.credential_keys import PROJECT_CREDENTIAL_KEYS
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def test_journal_bundle_status_registered_and_self_describing():
    reg = default_registry().get("journal.bundle.status")
    assert reg.is_write is False
    assert reg.json_schema is not None
    assert "decision_id" in reg.json_schema["properties"]
    assert reg.metadata()["next_actions"]
    assert "without external" in reg.description.lower()


def test_journal_bundle_status_mcp_spec_omits_private_auth_fragments():
    specs = [spec for spec in mcp_tool_specs() if spec["name"] == "journal.bundle.status"]
    assert len(specs) == 1
    rendered = json.dumps(specs[0], sort_keys=True).lower()
    forbidden_fragments = sorted(
        PROJECT_CREDENTIAL_KEYS
        | {
            "access_key",
            "credential",
            "credentials",
            "secret",
            "token",
            "transport_hint",
            "mcp_transport_hints",
        }
    )
    assert not [fragment for fragment in forbidden_fragments if fragment in rendered]


def test_partial_market_journal_returns_missing_steps_ids_and_next_calls(home):
    capture = _mcp(home, "idea.capture", {
        "thought": "Investigate a manually supplied prediction-market dislocation later.",
        "title": "Partial arc draft",
        "captured_at": "2026-05-20T14:00:00Z",
        "idempotency_key": "00000000-0000-4000-8000-zgea00000001",
    })
    assert capture.ok, capture
    assert isinstance(capture, SuccessEnvelope)
    venue = _mcp(home, "venue.add", {
        "name": "Manual PM",
        "kind": "prediction_market",
        "idempotency_key": "00000000-0000-4000-8000-zgea00000002",
    })
    assert venue.ok, venue
    assert isinstance(venue, SuccessEnvelope)
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"],
        "title": "Manual event market",
        "asset_class": "prediction_market",
        "metadata_json": {
            "raw_source_id": capture.data["source_id"],
            "draft_memory_node_id": capture.data["memory_node_id"],
        },
        "idempotency_key": "00000000-0000-4000-8000-zgea00000003",
    })
    assert instrument.ok, instrument
    assert isinstance(instrument, SuccessEnvelope)

    status = _mcp(home, "journal.bundle.status", {"source_id": capture.data["source_id"]})
    assert status.ok, status
    assert isinstance(status, SuccessEnvelope)
    data = status.data
    assert data["status"] == "needs_enrichment"
    assert capture.data["source_id"] in data["relevant_ids"]["source"]
    assert capture.data["memory_node_id"] in data["relevant_ids"]["memory_node"]
    assert instrument.data["id"] in data["relevant_ids"]["instrument"]
    assert data["idea_capture_provenance"]["present"] is True

    checks = {item["step"]: item for item in data["checklist"]}
    assert checks["venue_recorded"]["status"] == "ok"
    assert checks["instrument_recorded"]["status"] == "ok"
    assert checks["snapshot_recorded"]["status"] == "missing"
    assert checks["thesis_recorded"]["status"] == "missing"
    assert checks["forecast_recorded"]["status"] == "missing"
    assert checks["decision_recorded"]["status"] == "missing"
    assert checks["source_attached"]["record_ids"]["sources"] == [capture.data["source_id"]]

    tools = " ".join(call["tool"] for call in data["next_calls"])
    assert "snapshot.add" in tools
    assert "thesis.add" in tools
    assert "forecast.add" in tools
    assert "decision.add" in tools
    assert any(
        call["for_step"] == "thesis_recorded"
        and call["carry_forward_ids"]["source_ids"] == [capture.data["source_id"]]
        and call["carry_forward_ids"]["instrument_ids"] == [instrument.data["id"]]
        for call in data["next_calls"]
    )
    assert data["no_advice_boundary"] == {
        "external_fetch_performed": False,
        "trade_execution_performed": False,
        "advice_generated": False,
    }


def test_journal_bundle_status_missing_home_does_not_create_directory(tmp_path: Path):
    missing_home = tmp_path / "never-created"

    status = _mcp(missing_home, "journal.bundle.status", {"instrument_id": "i_missing"})

    assert isinstance(status, ErrorEnvelope)
    assert status.ok is False
    assert status.error.code == "STORAGE_ERROR"
    assert not missing_home.exists()


def test_journal_bundle_status_expands_thesis_to_forecasts_and_weak_unresolved(home):
    venue = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    assert isinstance(venue, SuccessEnvelope)
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"],
        "title": "Event with standalone forecast",
        "asset_class": "prediction_market",
    })
    assert isinstance(instrument, SuccessEnvelope)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": instrument.data["id"],
        "side": "yes",
        "body": "Thesis body.",
    })
    assert isinstance(thesis, SuccessEnvelope)
    forecast = _mcp(home, "forecast.add", {
        "thesis_id": thesis.data["id"],
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.55},
            {"outcome_label": "no", "probability": 0.45},
        ],
    })
    assert isinstance(forecast, SuccessEnvelope)

    status = _mcp(home, "journal.bundle.status", {"thesis_id": thesis.data["id"]})

    assert isinstance(status, SuccessEnvelope)
    assert forecast.data["id"] in status.data["relevant_ids"]["forecast"]
    checks = {item["step"]: item for item in status.data["checklist"]}
    assert checks["thesis_recorded"]["record_ids"] == {"theses": [thesis.data["id"]]}
    assert checks["forecast_recorded"]["status"] == "ok"
    assert checks["unresolved_forecasts"]["status"] == "weak"
    assert checks["unresolved_forecasts"]["record_ids"]["forecasts"] == [forecast.data["id"]]


def test_journal_bundle_status_source_weakness_keeps_all_sources_distinct(home):
    venue = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    assert isinstance(venue, SuccessEnvelope)
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"],
        "title": "Event with mixed source freshness",
        "asset_class": "prediction_market",
    })
    assert isinstance(instrument, SuccessEnvelope)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": instrument.data["id"],
        "side": "yes",
        "body": "Thesis body.",
    })
    assert isinstance(thesis, SuccessEnvelope)
    stale_source = _mcp(home, "source.add", {
        "kind": "url",
        "uri": "https://example.com/stale",
        "freshness_at": "2026-01-01T00:00:00.000Z",
    })
    assert isinstance(stale_source, SuccessEnvelope)
    fresh_source = _mcp(home, "source.add", {
        "kind": "url",
        "uri": "https://example.com/fresh",
        "freshness_at": "2999-01-01T00:00:00.000Z",
    })
    assert isinstance(fresh_source, SuccessEnvelope)
    for source in (stale_source, fresh_source):
        attach = _mcp(home, "source.attach_to_thesis", {
            "source_id": source.data["id"],
            "target_id": thesis.data["id"],
        })
        assert attach.ok, attach

    status = _mcp(home, "journal.bundle.status", {
        "thesis_id": thesis.data["id"],
        "stale_source_days": 14,
    })

    assert isinstance(status, SuccessEnvelope)
    checks = {item["step"]: item for item in status.data["checklist"]}
    source_check = checks["source_attached"]
    assert source_check["status"] == "weak"
    assert set(source_check["record_ids"]["sources"]) == {stale_source.data["id"], fresh_source.data["id"]}
    assert source_check["record_ids"]["weak_source_ids"] == [stale_source.data["id"]]


def test_journal_bundle_status_metadata_lookup_escapes_like_wildcards(home):
    db = open_database(db_path(home))
    try:
        conn = db.connection
        now = "2026-05-20T14:00:00.000Z"
        conn.execute(
            "INSERT INTO sources (id, kind, title, metadata_json, created_at, actor_id) VALUES (?, 'note', ?, '{}', ?, 'agent:default')",
            ("src_%", "Wildcard id source", now),
        )
        conn.execute(
            "INSERT INTO venues (id, name, kind, metadata_json, created_at, actor_id) VALUES ('v_like', 'PM', 'prediction_market', '{}', ?, 'agent:default')",
            (now,),
        )
        conn.execute(
            "INSERT INTO instruments (id, venue_id, title, asset_class, metadata_json, created_at, actor_id) VALUES (?, 'v_like', ?, 'prediction_market', ?, ?, 'agent:default')",
            ("i_literal", "Literal wildcard ref", json.dumps({"raw_source_id": "src_%"}), now),
        )
        conn.execute(
            "INSERT INTO instruments (id, venue_id, title, asset_class, metadata_json, created_at, actor_id) VALUES (?, 'v_like', ?, 'prediction_market', ?, ?, 'agent:default')",
            ("i_overmatch", "Should not match", json.dumps({"raw_source_id": "src_AX"}), now),
        )
    finally:
        db.close()

    status = _mcp(home, "journal.bundle.status", {"source_id": "src_%"})

    assert isinstance(status, SuccessEnvelope)
    assert "i_literal" in status.data["relevant_ids"]["instrument"]
    assert "i_overmatch" not in status.data["relevant_ids"]["instrument"]
