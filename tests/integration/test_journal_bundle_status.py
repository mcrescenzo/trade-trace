from __future__ import annotations

import json
from pathlib import Path

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.contracts.envelope import ErrorEnvelope, SuccessEnvelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call, mcp_tool_specs
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


def test_journal_bundle_plan_registered_cli_and_mcp_self_describing(capsys):
    from trade_trace.cli import main as cli_main

    reg = default_registry().get("journal.bundle.plan")
    assert reg.is_write is False
    assert reg.json_schema is not None
    assert reg.json_schema["required"] == ["arc_type"]
    assert reg.json_schema["properties"]["arc_type"]["enum"] == ["watch", "skip", "paper_enter"]

    rc = cli_main(["journal", "bundle", "plan", "--help"])
    out = capsys.readouterr()
    assert rc == 0
    assert "--arc-type" in out.out + out.err

    specs = [spec for spec in mcp_tool_specs(include_legacy=True) if spec["name"] == "journal.bundle.plan"]
    assert len(specs) == 1
    assert specs[0]["input_schema"]["properties"]["arc_type"]["enum"] == ["watch", "skip", "paper_enter"]


def test_journal_bundle_plan_watch_uses_target_id_attach_guidance():
    plan = mcp_call("journal.bundle.plan", {"arc_type": "watch", "idempotency_key_prefix": "pfx"}, actor_id="agent:default")
    assert plan.ok, plan
    assert isinstance(plan, SuccessEnvelope)
    data = plan.data
    assert data["arc_type"] == "watch"
    assert data["plan_state"] == "plan_only"
    assert data["no_advice_boundary"] == {"external_fetch_performed": False, "trade_execution_performed": False, "advice_generated": False}
    calls = {step["tool"]: step for step in data["ordered_calls"]}
    assert {"instrument_id", "captured_at"}.issubset(calls["snapshot.add"]["args_template"])
    assert {"kind", "stance", "uri"}.issubset(calls["source.add"]["args_template"])
    assert {"instrument_id", "side", "body"}.issubset(calls["thesis.add"]["args_template"])
    assert {"thesis_id", "kind", "yes_label", "outcomes"}.issubset(calls["forecast.add"]["args_template"])
    assert {"target_kind", "target_id", "body"}.issubset(calls["memory.reflect"]["args_template"])
    for stale_field in ("as_of", "payload_json", "statement", "prompt", "response"):
        for step in calls.values():
            assert stale_field not in step["args_template"]
    for tool in ("source.attach_to_thesis", "source.attach_to_forecast", "source.attach_to_decision"):
        args = calls[tool]["args_template"]
        assert "target_id" in args
        assert "thesis_id" not in args
        assert "forecast_id" not in args
        assert "decision_id" not in args
    decision_step = calls["decision.add"]
    assert "review_by" in decision_step["args_template"]
    assert "review_by" not in decision_step["purpose"]
    status_args = calls["journal.bundle.status"]["args_template"]
    assert "memory.reflect or memory.retain" in status_args["memory_node_id"]
    assert "memory_node.add" not in status_args["memory_node_id"]
    assert data["ordered_calls"][-1]["tool"] == "journal.bundle.status"
    assert data["final_check"]["tool"] == "journal.bundle.status"


def test_journal_bundle_plan_skip_with_existing_ids_carries_forward_and_avoids_trade_fields():
    args = {
        "arc_type": "skip",
        "venue_id": "ven_existing",
        "instrument_id": "inst_existing",
        "snapshot_id": "snap_existing",
        "source_id": "src_existing",
        "thesis_id": "th_existing",
        "forecast_id": "fc_existing",
        "decision_id": "dec_existing",
        "memory_node_id": "mem_existing",
    }
    plan = mcp_call("journal.bundle.plan", args, actor_id="agent:default")
    assert plan.ok, plan
    assert isinstance(plan, SuccessEnvelope)
    data = plan.data
    assert data["carry_forward_ids"] == {k: v for k, v in args.items() if k.endswith("_id")}
    calls = {step["tool"]: step for step in data["ordered_calls"]}
    assert calls["instrument.add"]["args_template"]["venue_id"] == "ven_existing"
    assert calls["instrument.add"]["skip_when"] == "instrument_id supplied"
    assert calls["decision.add"]["skip_when"] == "decision_id supplied"
    decision_args = calls["decision.add"]["args_template"]
    assert decision_args["type"] == "skip"
    assert decision_args["instrument_id"] == "inst_existing"
    assert "reason" in decision_args
    assert "quantity" not in decision_args
    assert "price" not in decision_args
    assert "review_by" not in decision_args
    assert data["final_check"]["args"]["decision_id"] == "dec_existing"



def test_journal_bundle_plan_paper_enter_guides_required_fields_without_broker_execution():
    plan = mcp_call("journal.bundle.plan", {"arc_type": "paper_enter", "idempotency_key_prefix": "paper"}, actor_id="agent:default")
    assert plan.ok, plan
    assert isinstance(plan, SuccessEnvelope)
    data = plan.data
    assert data["arc_type"] == "paper_enter"
    calls = {step["tool"]: step for step in data["ordered_calls"]}
    decision_step = calls["decision.add"]
    decision_args = decision_step["args_template"]
    assert decision_args["type"] == "paper_enter"
    assert {"side", "quantity", "price", "thesis_id", "forecast_id", "snapshot_id"}.issubset(decision_args)
    assert "review_by" not in decision_args
    assert "no broker execution" in decision_step["purpose"]
    assert "position event/projection outputs" in decision_step["purpose"]
    assert "source.add" in calls
    assert "forecast.add" in calls
    assert data["no_advice_boundary"]["trade_execution_performed"] is False


def test_journal_bundle_status_mcp_spec_omits_private_auth_fragments():
    specs = [spec for spec in mcp_tool_specs(include_legacy=True) if spec["name"] == "journal.bundle.status"]
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


def test_journal_bundle_status_recovers_idea_capture_provenance_from_downstream_decision_metadata(home):
    capture = _mcp(home, "idea.capture", {
        "thought": "Promote this draft into a normal market journal arc.",
        "title": "Decision provenance draft",
        "captured_at": "2026-05-20T15:00:00Z",
        "idempotency_key": "00000000-0000-4000-8000-5px100000001",
    })
    assert isinstance(capture, SuccessEnvelope)
    venue = _mcp(home, "venue.add", {
        "name": "Manual PM downstream",
        "kind": "prediction_market",
        "idempotency_key": "00000000-0000-4000-8000-5px100000002",
    })
    assert isinstance(venue, SuccessEnvelope)
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"],
        "title": "Decision provenance market",
        "asset_class": "prediction_market",
        "idempotency_key": "00000000-0000-4000-8000-5px100000003",
    })
    assert isinstance(instrument, SuccessEnvelope)
    snapshot = _mcp(home, "snapshot.add", {
        "instrument_id": instrument.data["id"],
        "captured_at": "2026-05-20T15:05:00Z",
        "idempotency_key": "00000000-0000-4000-8000-5px100000004",
    })
    assert isinstance(snapshot, SuccessEnvelope)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": instrument.data["id"],
        "side": "yes",
        "body": "Promoted thesis.",
        "idempotency_key": "00000000-0000-4000-8000-5px100000005",
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
        "idempotency_key": "00000000-0000-4000-8000-5px100000006",
    })
    assert isinstance(forecast, SuccessEnvelope)
    decision = _mcp(home, "decision.add", {
        "type": "skip",
        "instrument_id": instrument.data["id"],
        "thesis_id": thesis.data["id"],
        "forecast_id": forecast.data["id"],
        "snapshot_id": snapshot.data["id"],
        "reason": "Regression test only; no advice.",
        "metadata_json": {
            "idea_capture_provenance": {
                "source_id": capture.data["source_id"],
                "memory_node_id": capture.data["memory_node_id"],
            },
        },
        "idempotency_key": "00000000-0000-4000-8000-5px100000007",
    })
    assert isinstance(decision, SuccessEnvelope)

    status = _mcp(home, "journal.bundle.status", {"decision_id": decision.data["id"]})

    assert isinstance(status, SuccessEnvelope)
    data = status.data
    assert capture.data["source_id"] in data["relevant_ids"]["source"]
    assert capture.data["memory_node_id"] in data["relevant_ids"]["memory_node"]
    records = data["idea_capture_provenance"]["records"]
    assert data["idea_capture_provenance"]["present"] is True
    assert {record["kind"]: record for record in records} == {
        "source": {"kind": "source", "id": capture.data["source_id"], "draft_state": "needs_enrichment"},
        "memory_node": {"kind": "memory_node", "id": capture.data["memory_node_id"], "draft_state": "needs_enrichment"},
    }
    assert data["no_advice_boundary"] == {
        "external_fetch_performed": False,
        "trade_execution_performed": False,
        "advice_generated": False,
    }


def test_journal_bundle_status_recognizes_complete_enough_paper_enter_without_reflection(home):
    venue = _mcp(home, "venue.add", {"name": "Paper PM", "kind": "prediction_market"})
    assert isinstance(venue, SuccessEnvelope)
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"],
        "title": "Paper entry market",
        "asset_class": "prediction_market",
    })
    assert isinstance(instrument, SuccessEnvelope)
    snapshot = _mcp(home, "snapshot.add", {
        "instrument_id": instrument.data["id"],
        "captured_at": "2026-05-20T15:05:00Z",
        "price": 0.52,
    })
    assert isinstance(snapshot, SuccessEnvelope)
    source = _mcp(home, "source.add", {"kind": "url", "uri": "https://example.invalid/paper-entry"})
    assert isinstance(source, SuccessEnvelope)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": instrument.data["id"],
        "side": "yes",
        "body": "Caller-authored paper entry thesis.",
    })
    assert isinstance(thesis, SuccessEnvelope)
    forecast = _mcp(home, "forecast.add", {
        "thesis_id": thesis.data["id"],
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.57},
            {"outcome_label": "no", "probability": 0.43},
        ],
    })
    assert isinstance(forecast, SuccessEnvelope)
    for tool, target_id in (
        ("source.attach_to_thesis", thesis.data["id"]),
        ("source.attach_to_forecast", forecast.data["id"]),
    ):
        attach = _mcp(home, tool, {"source_id": source.data["id"], "target_id": target_id})
        assert isinstance(attach, SuccessEnvelope)
    decision = _mcp(home, "decision.add", {
        "type": "paper_enter",
        "instrument_id": instrument.data["id"],
        "thesis_id": thesis.data["id"],
        "forecast_id": forecast.data["id"],
        "snapshot_id": snapshot.data["id"],
        "side": "yes",
        "quantity": 10,
        "price": 0.52,
        "reason": "Caller-selected paper journal entry; not broker execution.",
    })
    assert isinstance(decision, SuccessEnvelope)
    assert "position_id" in decision.data
    assert "position_event_id" in decision.data
    attach_decision = _mcp(home, "source.attach_to_decision", {"source_id": source.data["id"], "target_id": decision.data["id"]})
    assert isinstance(attach_decision, SuccessEnvelope)

    status = _mcp(home, "journal.bundle.status", {"decision_id": decision.data["id"]})

    assert isinstance(status, SuccessEnvelope)
    assert status.data["status"] == "complete_enough"
    checks = {item["step"]: item for item in status.data["checklist"]}
    assert checks["venue_recorded"]["status"] == "ok"
    assert checks["instrument_recorded"]["status"] == "ok"
    assert checks["snapshot_recorded"]["status"] == "ok"
    assert checks["source_attached"]["status"] == "ok"
    assert checks["thesis_recorded"]["status"] == "ok"
    assert checks["forecast_recorded"]["status"] == "ok"
    assert checks["decision_recorded"]["status"] == "ok"
    assert checks["reflection_attached"]["status"] == "ok"
    assert not [call for call in status.data["next_calls"] if call["for_step"] == "reflection_attached"]
    assert status.data["no_advice_boundary"]["trade_execution_performed"] is False


def test_journal_bundle_status_paper_enter_does_not_waive_related_skip_requirements(home):
    venue = _mcp(home, "venue.add", {"name": "Mixed PM", "kind": "prediction_market"})
    assert isinstance(venue, SuccessEnvelope)
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"],
        "title": "Mixed paper and skip market",
        "asset_class": "prediction_market",
    })
    assert isinstance(instrument, SuccessEnvelope)
    snapshot = _mcp(home, "snapshot.add", {
        "instrument_id": instrument.data["id"],
        "captured_at": "2026-05-20T15:05:00Z",
        "price": 0.52,
    })
    assert isinstance(snapshot, SuccessEnvelope)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": instrument.data["id"],
        "side": "yes",
        "body": "Caller-authored mixed arc thesis.",
    })
    assert isinstance(thesis, SuccessEnvelope)
    forecast = _mcp(home, "forecast.add", {
        "thesis_id": thesis.data["id"],
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.57},
            {"outcome_label": "no", "probability": 0.43},
        ],
    })
    assert isinstance(forecast, SuccessEnvelope)
    paper_decision = _mcp(home, "decision.add", {
        "type": "paper_enter",
        "instrument_id": instrument.data["id"],
        "thesis_id": thesis.data["id"],
        "forecast_id": forecast.data["id"],
        "snapshot_id": snapshot.data["id"],
        "side": "yes",
        "quantity": 10,
        "price": 0.52,
        "reason": "Caller-selected paper journal entry; not broker execution.",
    })
    assert isinstance(paper_decision, SuccessEnvelope)
    skip_decision = _mcp(home, "decision.add", {
        "type": "skip",
        "instrument_id": instrument.data["id"],
        "thesis_id": thesis.data["id"],
        "forecast_id": forecast.data["id"],
        "snapshot_id": snapshot.data["id"],
        "reason": "Regression test only; no advice.",
    })
    assert isinstance(skip_decision, SuccessEnvelope)

    status = _mcp(home, "journal.bundle.status", {"decision_id": skip_decision.data["id"]})

    assert isinstance(status, SuccessEnvelope)
    checks = {item["step"]: item for item in status.data["checklist"]}
    assert checks["unresolved_forecasts"]["status"] == "weak"
    assert checks["reflection_attached"]["status"] == "missing"
    assert {paper_decision.data["id"], skip_decision.data["id"]}.issubset(checks["reflection_attached"]["record_ids"]["decisions"])


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
    assert "forecast.score" not in checks["unresolved_forecasts"]["next_call"]
    assert "outcome.add" in checks["unresolved_forecasts"]["next_call"]


def test_journal_bundle_status_playbook_adherence_guidance_uses_registered_tool(home):
    venue = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    assert isinstance(venue, SuccessEnvelope)
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"],
        "title": "Playbook-scoped watch",
        "asset_class": "prediction_market",
    })
    assert isinstance(instrument, SuccessEnvelope)
    decision = _mcp(home, "decision.add", {
        "type": "watch",
        "instrument_id": instrument.data["id"],
        "playbook_version_id": "pbv_missing_rows_fixture",
    })
    assert isinstance(decision, SuccessEnvelope)

    status = _mcp(home, "journal.bundle.status", {"decision_id": decision.data["id"]})

    assert isinstance(status, SuccessEnvelope)
    checks = {item["step"]: item for item in status.data["checklist"]}
    adherence = checks["playbook_adherence_rows"]
    assert adherence["status"] == "weak"
    assert adherence["record_ids"] == {"decisions": [decision.data["id"]]}
    assert "decision.record_adherence" in adherence["next_call"]
    assert "playbook.rule.record" not in adherence["next_call"]
    assert "decision.record_adherence" in default_registry().names()


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


def test_journal_bundle_status_current_time_pins_source_staleness_clock(home):
    """Per trade-trace-efmq: a caller-supplied current_time pins the
    14-day staleness cutoff so bundle.status is reproducible instead of
    flipping ok->weak as the wall clock advances past the source date."""

    venue = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"],
        "title": "Event for deterministic staleness",
        "asset_class": "prediction_market",
    })
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": instrument.data["id"], "side": "yes", "body": "Thesis.",
    })
    source = _mcp(home, "source.add", {
        "kind": "url", "uri": "https://example.com/pinned",
        "freshness_at": "2026-05-21T00:00:00.000Z",
    })
    attach = _mcp(home, "source.attach_to_thesis", {
        "source_id": source.data["id"], "target_id": thesis.data["id"],
    })
    assert attach.ok, attach

    # current_time 9 days after the source -> inside the 14-day window -> ok.
    fresh = _mcp(home, "journal.bundle.status", {
        "thesis_id": thesis.data["id"],
        "stale_source_days": 14,
        "current_time": "2026-05-30T00:00:00Z",
    })
    assert isinstance(fresh, SuccessEnvelope)
    fresh_check = {c["step"]: c for c in fresh.data["checklist"]}["source_attached"]
    assert fresh_check["status"] == "ok", fresh_check

    # Same bundle, current_time 40 days later -> past the cutoff -> weak.
    stale = _mcp(home, "journal.bundle.status", {
        "thesis_id": thesis.data["id"],
        "stale_source_days": 14,
        "current_time": "2026-06-30T00:00:00Z",
    })
    assert isinstance(stale, SuccessEnvelope)
    stale_check = {c["step"]: c for c in stale.data["checklist"]}["source_attached"]
    assert stale_check["status"] == "weak", stale_check
    assert stale_check["record_ids"]["weak_source_ids"] == [source.data["id"]]


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
