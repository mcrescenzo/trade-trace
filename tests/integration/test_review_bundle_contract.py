"""`review.bundle` per bead trade-trace-yai + reports.md §5.

The bundle ships beyond the M1 contract stub: it now actually selects
decisions matching the supported ReportFilter subset, walks to related
theses/forecasts/outcomes/positions/sources/reflections/playbook
versions, applies the §5.3 redaction rules, and returns a deterministic
canonical-JSON bundle whose `bundle_hash` (sha-256 over `data` minus
the hash field) stays stable across runs.

These tests pin the contract:
- registration + schema introspection
- empty-DB behavior
- hash stability across identical inputs
- hash sensitivity to new records
- §5.3 redaction: sensitive omitted, redacted stripped
- supported-filter rejection contract (bead d4k/ke1)
- bounded selection (max_records)
- CLI/MCP parity
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.cli import main as cli_main
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path
from trade_trace.tools.review_bundle import (
    CONTRACT_VERSION,
    ReviewBundleInput,
    ReviewBundleOutput,
)


def _seed_decision(home: Path, *, actor_id: str = "agent:default") -> dict:
    venue = _mcp(home, "venue.add", {
        "name": "PM", "kind": "prediction_market",
    })
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"], "title": "T",
        "asset_class": "prediction_market",
    })
    decision = mcp_call("decision.add", {
        "home": str(home), "instrument_id": instrument.data["id"],
        "type": "skip", "reason": "no edge today",
    }, actor_id=actor_id)
    assert decision.ok
    return {
        "venue_id": venue.data["id"],
        "instrument_id": instrument.data["id"],
        "decision_id": decision.data["id"],
    }


# -- registration + schemas --------------------------------------------


def test_review_bundle_registered():
    assert "review.bundle" in default_registry().names()


def test_review_bundle_input_schema_introspectable():
    schema = ReviewBundleInput.model_json_schema()
    assert "filter" in schema["properties"]
    assert schema["properties"]["max_records"]["maximum"] == 200


def test_review_bundle_output_schema_carries_bundle_hash_and_contract_version():
    schema = ReviewBundleOutput.model_json_schema()
    assert "bundle_hash" in schema["properties"]
    assert "contract_version" in schema["properties"]
    assert "selected" in schema["properties"]
    assert "caveats" in schema["properties"]


# -- empty DB ----------------------------------------------------------


def test_empty_db_returns_zero_records_with_stable_hash(home):
    env = _mcp(home, "review.bundle", {})
    assert env.ok, env
    data = env.data
    assert data["selected"]["decisions"] == []
    assert data["sources"] == []
    assert data["reflections"] == []
    assert data["playbook_versions"] == []
    assert data["bundle_hash"].startswith("sha256:")
    assert data["contract_version"] == CONTRACT_VERSION


# -- hash stability ----------------------------------------------------


def test_hash_stable_across_identical_calls(home):
    _seed_decision(home)
    env_a = _mcp(home, "review.bundle", {"max_records": 5})
    env_b = _mcp(home, "review.bundle", {"max_records": 5})
    assert env_a.ok and env_b.ok
    assert env_a.data["bundle_hash"] == env_b.data["bundle_hash"]


def test_hash_changes_when_db_state_changes(home):
    _seed_decision(home)
    env_before = _mcp(home, "review.bundle", {"max_records": 5})
    _seed_decision(home)
    env_after = _mcp(home, "review.bundle", {"max_records": 5})
    assert env_before.ok and env_after.ok
    assert env_before.data["bundle_hash"] != env_after.data["bundle_hash"]


def test_hash_changes_when_max_records_excludes_a_decision(home):
    _seed_decision(home)
    _seed_decision(home)
    env_full = _mcp(home, "review.bundle", {"max_records": 5})
    env_capped = _mcp(home, "review.bundle", {"max_records": 1})
    assert env_full.data["bundle_hash"] != env_capped.data["bundle_hash"]
    assert len(env_full.data["selected"]["decisions"]) == 2
    assert len(env_capped.data["selected"]["decisions"]) == 1


# -- §5.3 redaction ----------------------------------------------------


def _seed_source_with_redaction(home: Path, *, redaction_status: str,
                                decision_id: str) -> str:
    """Insert a source directly with the given redaction_status and
    attach it to the decision via the standard source.attach_to_decision
    edge. Direct insert is the only path; the M1 source.add tool doesn't
    expose redaction_status as an input."""

    db = open_database(db_path(home), create_parent=False)
    try:
        src_id = f"src_{redaction_status}"
        db.connection.execute(
            "INSERT INTO sources(id, kind, title, note, excerpt, "
            "extracted_text, summary, redaction_status, created_at, "
            "actor_id) VALUES (?, 'note', ?, ?, ?, ?, ?, ?, ?, "
            "'agent:default')",
            (src_id, f"title-{redaction_status}",
             f"note-{redaction_status}",
             f"excerpt-{redaction_status}",
             f"extracted-{redaction_status}",
             f"summary-{redaction_status}",
             redaction_status,
             "2026-05-19T12:00:00Z"),
        )
        db.connection.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, "
            "target_id, edge_type, created_at, actor_id) VALUES "
            "(?, 'source', ?, 'decision', ?, 'about', ?, 'agent:default')",
            (f"edg_{redaction_status}", src_id, decision_id,
             "2026-05-19T12:00:00Z"),
        )
        db.connection.commit()
    finally:
        db.close()
    return src_id


def test_sensitive_source_omitted_with_caveat(home):
    seeded = _seed_decision(home)
    _seed_source_with_redaction(home, redaction_status="sensitive",
                                decision_id=seeded["decision_id"])
    env = _mcp(home, "review.bundle", {})
    assert env.ok, env
    src_ids = [s["id"] for s in env.data["sources"]]
    assert "src_sensitive" not in src_ids
    assert any("sensitive" in c for c in env.data["caveats"])


def test_redacted_source_strips_content_but_keeps_metadata(home):
    seeded = _seed_decision(home)
    _seed_source_with_redaction(home, redaction_status="redacted",
                                decision_id=seeded["decision_id"])
    env = _mcp(home, "review.bundle", {})
    assert env.ok, env
    sources = {s["id"]: s for s in env.data["sources"]}
    assert "src_redacted" in sources
    src = sources["src_redacted"]
    # Content-bearing columns are dropped.
    for field in ("note", "excerpt", "extracted_text", "summary"):
        assert src[field] is None, f"{field} should be stripped"
    # Metadata stays.
    assert src["title"] == "title-redacted"
    assert src["kind"] == "note"
    assert src["redaction_status"] == "redacted"
    assert any("redacted" in c for c in env.data["caveats"])


def test_none_redaction_source_passes_through(home):
    seeded = _seed_decision(home)
    _seed_source_with_redaction(home, redaction_status="none",
                                decision_id=seeded["decision_id"])
    env = _mcp(home, "review.bundle", {})
    sources = {s["id"]: s for s in env.data["sources"]}
    assert sources["src_none"]["note"] == "note-none"
    assert sources["src_none"]["excerpt"] == "excerpt-none"


# -- supported-filter contract (d4k/ke1) -------------------------------


def test_unsupported_filter_field_rejected(home):
    env = _mcp(home, "review.bundle", {
        "filter": {"decision": {"decision_type": ["actual_enter"]}},
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    details = env.error.details
    assert details["field"] == "filter"
    assert "decision.decision_type" in details["unsupported_filter_paths"]
    assert details["report"] == "review.bundle"
    assert set(details["supported_filter_paths"]) == {
        "actors.actor_id",
        "instrument.venue_id",
        "strategy.strategy_id",
        "time_window.decision_at_gte",
        "time_window.decision_at_lt",
    }


def test_supported_actor_filter_narrows_decisions(home):
    seeded_a = _seed_decision(home, actor_id="agent:A")
    seeded_b = _seed_decision(home, actor_id="agent:B")
    env = _mcp(home, "review.bundle", {
        "filter": {"actors": {"actor_id": ["agent:A"]}},
    })
    assert env.ok, env
    ids = [d["id"] for d in env.data["selected"]["decisions"]]
    assert seeded_a["decision_id"] in ids
    assert seeded_b["decision_id"] not in ids


# -- include flags ----------------------------------------------------


def test_include_sources_false_drops_sources(home):
    seeded = _seed_decision(home)
    _seed_source_with_redaction(home, redaction_status="none",
                                decision_id=seeded["decision_id"])
    env = _mcp(home, "review.bundle", {"include_sources": False})
    assert env.ok
    assert env.data["sources"] == []


# -- CLI/MCP parity ---------------------------------------------------


def test_cli_review_bundle_parity_with_mcp(home):
    """CLI and MCP return the same bundle_hash for the same inputs."""

    _seed_decision(home)

    mcp_env = _mcp(home, "review.bundle", {}).model_dump(
        mode="json", exclude_none=True,
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "--actor-id", "agent:default",
            "--request-id", "rid",
            "review", "bundle",
            "--home", str(home),
            "--filter-json", "{}",
        ])
    cli_env = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert rc == 0, cli_env
    assert mcp_env["ok"] is True
    assert cli_env["ok"] is True
    assert mcp_env["data"]["bundle_hash"] == cli_env["data"]["bundle_hash"]
