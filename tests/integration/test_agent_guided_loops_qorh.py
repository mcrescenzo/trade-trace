"""Deterministic dogfood evals for help/schema/error-guided agent loops.

These tests model a fresh agent that has no private transcript context and
progresses only from live CLI help, tool.schema contracts, and typed error
recovery payloads.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.cli import main as cli_main
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path
from trade_trace.tools.decision_matrix import allowed_decision_types


def _cli_json(capsys, argv: list[str]) -> tuple[int, dict]:
    rc = cli_main(argv)
    out = capsys.readouterr()
    assert out.out.strip(), out
    return rc, json.loads(out.out.strip().splitlines()[-1])


def _init_env_home(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("TRADE_TRACE_HOME", str(home))
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok, init
    return home


def test_fresh_agent_capture_bundle_decision_loop_uses_help_schema_and_error_recovery(
    tmp_path, monkeypatch, capsys,
):
    """Multi-step loop: help/schema -> idea.capture -> bundle.status ->
    decision.add negative path -> corrected skip payload.
    """

    home = _init_env_home(monkeypatch, tmp_path)

    rc = cli_main(["idea", "capture", "--help"])
    help_text = capsys.readouterr().out
    assert rc == 0
    assert "Tool: idea.capture" in help_text
    assert "--thought <string>  required" in help_text
    assert "--idempotency-key <string>  required" in help_text

    rc, schema_env = _cli_json(capsys, ["tool", "schema", "--tool", "idea.capture"])
    assert rc == 0
    assert schema_env["ok"] is True
    assert schema_env["data"]["json_schema"]["required"] == ["thought", "idempotency_key"]

    rc, capture = _cli_json(capsys, [
        "idea", "capture",
        "--thought", "Manually supplied CPI dislocation note; enrich before any decision.",
        "--title", "CPI dislocation draft",
        "--idempotency-key", "00000000-0000-4000-8000-qorh00000001",
    ])
    assert rc == 0
    assert capture["ok"] is True
    assert capture["data"]["capture_state"] == "draft_needs_enrichment"
    assert capture["data"]["no_advice_boundary"]["advice_generated"] is False
    assert any("thesis.add" in action for action in capture["data"]["next_actions"])

    venue = _mcp(home, "venue.add", {
        "name": "Manual PM", "kind": "prediction_market",
        "idempotency_key": "00000000-0000-4000-8000-qorh00000002",
    })
    assert venue.ok, venue
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"],
        "title": "CPI event market",
        "asset_class": "prediction_market",
        "metadata_json": {"raw_source_id": capture["data"]["source_id"]},
        "idempotency_key": "00000000-0000-4000-8000-qorh00000003",
    })
    assert instrument.ok, instrument

    rc, bundle = _cli_json(capsys, [
        "journal", "bundle", "status", "--source-id", capture["data"]["source_id"],
    ])
    assert rc == 0
    assert bundle["ok"] is True
    assert bundle["data"]["status"] == "needs_enrichment"
    next_tools = [call["tool"] for call in bundle["data"]["next_calls"]]
    assert "decision.add" in next_tools
    decision_call = next(call for call in bundle["data"]["next_calls"] if call["tool"] == "decision.add")
    assert decision_call["carry_forward_ids"]["instrument_ids"] == [instrument.data["id"]]

    rc, decision_schema = _cli_json(capsys, ["tool", "schema", "--tool", "decision.add"])
    assert rc == 0
    matrix = decision_schema["data"]["json_schema"]["x-decision-matrix"]
    assert matrix["skip"]["required"] == ["instrument_id", "reason"]
    assert "quantity" in matrix["skip"]["forbidden"]

    rc, bad_skip = _cli_json(capsys, [
        "--dry-run", "decision", "add",
        "--type", "skip",
        "--instrument-id", instrument.data["id"],
        "--reason", "No edge after fees.",
        "--quantity", "10",
        "--idempotency-key", "00000000-0000-4000-8000-qorh00000004",
    ])
    assert rc == 2
    assert bad_skip["ok"] is False
    assert bad_skip["error"]["code"] == "VALIDATION_ERROR"
    assert bad_skip["error"]["details"]["violation"] == "forbidden_present"
    corrected = bad_skip["error"]["details"]["corrected_payload_hint"]
    assert "quantity" not in corrected

    rc, fixed_skip = _cli_json(capsys, [
        "decision", "add",
        "--type", corrected["type"],
        "--instrument-id", corrected["instrument_id"],
        "--reason", corrected["reason"],
        "--idempotency-key", "00000000-0000-4000-8000-qorh00000005",
    ])
    assert rc == 0
    assert fixed_skip["ok"] is True
    assert fixed_skip["data"]["type"] == "skip"


def test_decision_memory_reflect_loop_rejects_unknown_enum_and_stale_docs_then_recovers(
    tmp_path, monkeypatch, capsys,
):
    """Multi-step loop: decision.add enum error -> schema-guided skip ->
    memory.reflect stale-doc negative path -> schema-guided sugar recovery.
    """

    home = _init_env_home(monkeypatch, tmp_path)
    venue = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    assert venue.ok, venue
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"], "title": "Event", "asset_class": "prediction_market",
    })
    assert instrument.ok, instrument

    rc, unknown = _cli_json(capsys, [
        "--dry-run", "decision", "add",
        "--type", "mystery",
        "--instrument-id", instrument.data["id"],
        "--idempotency-key", "00000000-0000-4000-8000-qorh00000006",
    ])
    assert rc == 2
    details = unknown["error"]["details"]
    assert details["field"] == "type"
    assert details["allowed_decision_types"] == allowed_decision_types()
    assert "Choose one" in details["recovery"]

    rc, decision = _cli_json(capsys, [
        "decision", "add",
        "--type", "skip",
        "--instrument-id", instrument.data["id"],
        "--reason", "Schema listed skip as valid non-entry decision.",
        "--idempotency-key", "00000000-0000-4000-8000-qorh00000007",
    ])
    assert rc == 0
    decision_id = decision["data"]["id"]

    rc = cli_main(["memory", "reflect", "--help"])
    help_text = capsys.readouterr().out
    assert rc == 0
    assert "Tool: memory.reflect" in help_text
    assert "--target <object>" in help_text
    assert "--insight <string>" in help_text

    rc, reflect_schema = _cli_json(capsys, ["tool", "schema", "--tool", "memory.reflect"])
    assert rc == 0
    props = reflect_schema["data"]["json_schema"]["properties"]
    assert "target" in props and "insight" in props
    assert "derived_from" not in props  # stale/deferred docs examples must not be advertised.

    stale_docs = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": decision_id},
        "insight": "This stale-doc edge shortcut should be rejected.",
        "derived_from": [{"kind": "source", "id": "src_missing"}],
    })
    assert stale_docs.ok is False
    assert stale_docs.error.code.value == "UNSUPPORTED_CAPABILITY"
    assert stale_docs.error.details["field"] == "derived_from"

    reflection = _mcp(home, "memory.reflect", {
        "target": {"kind": "decision", "id": decision_id},
        "insight": "The schema-guided skip preserved discipline when edge was absent.",
        "strength_tags": ["skip-discipline"],
        "idempotency_key": "00000000-0000-4000-8000-qorh00000008",
    })
    assert reflection.ok, reflection

    db = open_database(db_path(home), create_parent=False)
    try:
        edge = db.connection.execute(
            "SELECT target_kind, target_id, edge_type FROM edges WHERE source_id = ?",
            (reflection.data["id"],),
        ).fetchone()
    finally:
        db.close()
    assert edge == ("decision", decision_id, "about")


def test_low_sample_reports_and_playbook_adherence_expose_caveats_not_skill_claims(home):
    """Low-N report caveats stay explicit while process next-actions remain
    inspectable for an agent dogfood loop.
    """

    seed = mcp_call("journal.fixture_seed", {"home": str(home), "target": "mvp-eval"})
    assert seed.ok, seed

    coach = _mcp(home, "report.coach", {})
    assert coach.ok, coach
    low_n = coach.data["low_sample_context"]
    assert low_n["scored_forecast_count"] < low_n["min_sample"]
    assert "Insufficient calibration sample" in low_n["statistical_caveat"]
    assert any(action["category"] == "calibration_data" for action in coach.data["next_actions"])

    adherence = _mcp(home, "report.playbook_adherence", {})
    assert adherence.ok, adherence
    serialized = json.dumps(adherence.data, sort_keys=True).lower()
    assert "playbook" in serialized
    assert not any(phrase in serialized for phrase in ("proven skill", "statistically significant"))
