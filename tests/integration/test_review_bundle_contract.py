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
from tests.integration.test_recall_receipts import _seed as _seed_recall_receipts
from trade_trace.cli import main as cli_main
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path
from trade_trace.tools.review_bundle import (
    CONTRACT_VERSION,
    ReviewBundleInput,
    ReviewBundleOutput,
    _bundle_hash,
    _json_value_has_exact_token,
    _report_summaries,
)


def _seed_decision(
    home: Path, *, actor_id: str = "agent:default", extra_args: dict | None = None,
) -> dict:
    db = open_database(db_path(home), create_parent=False)
    try:
        suffix = db.connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] + 1
    finally:
        db.close()
    venue = _mcp(home, "venue.add", {
        "name": f"PM {suffix}", "kind": "prediction_market",
    })
    instrument = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"], "title": f"T {suffix}",
        "asset_class": "prediction_market",
    })
    decision_args = {
        "home": str(home), "instrument_id": instrument.data["id"],
        "type": "skip", "reason": f"no edge today {suffix}",
    }
    if extra_args:
        decision_args.update(extra_args)
    decision = mcp_call("decision.add", decision_args, actor_id=actor_id)
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
    assert "recall_receipts" in schema["properties"]


def test_report_summaries_logs_calibration_fallback(monkeypatch, home):
    import trade_trace.tools.review_bundle as review_bundle

    warnings: list[tuple[str, dict[str, str] | None]] = []

    class FakeLogger:
        def warning(self, message: str, *, extra: dict[str, str] | None = None) -> None:
            warnings.append((message, extra))

    def raise_calibration(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(review_bundle, "report_calibration", raise_calibration)
    monkeypatch.setattr(review_bundle, "get_logger", lambda _name: FakeLogger())

    db = open_database(db_path(home), create_parent=False)
    try:
        summaries, calibration = _report_summaries(db.connection, filter_view={})
    finally:
        db.close()

    assert calibration == {"sample_size": 0, "sample_warning": None}
    assert summaries["calibration"] == calibration
    assert warnings == [
        (
            "calibration report failed inside review bundle",
            {"error": "boom"},
        )
    ]


# -- empty DB ----------------------------------------------------------


def test_empty_db_returns_zero_records_with_stable_hash(home):
    env = _mcp(home, "review.bundle", {})
    assert env.ok, env
    data = env.data
    assert data["selected"]["decisions"] == []
    assert data["sources"] == []
    assert data["reflections"] == []
    assert data["playbook_versions"] == []
    assert data["recall_receipts"]["status"] == "omitted"
    assert data["recall_receipts"]["omissions"] == ["omitted_no_selected_consumers"]
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


def test_bundle_hash_uses_canonical_key_order_not_insertion_order(home):
    """Pin the decomposition-sensitive hash contract: top-level output
    keys have a stable presentation order, while the digest is computed
    from canonical JSON (`sort_keys=True`) and excludes `bundle_hash`.
    """

    _seed_decision(home)
    env = _mcp(home, "review.bundle", {"max_records": 5})
    assert env.ok, env

    expected_top_level_order = [
        "filter",
        "selected",
        "sources",
        "reflections",
        "playbook_versions",
        "report_summaries",
        "recall_receipts",
        "autonomous_lifecycle",
        "redaction_profile",
        "redaction_summary",
        "caveats",
        "suggested_prompts",
        "contract_version",
        "bundle_hash",
    ]
    assert list(env.data.keys()) == expected_top_level_order

    body_without_hash = {
        key: env.data[key]
        for key in reversed(expected_top_level_order)
        if key != "bundle_hash"
    }
    assert _bundle_hash(body_without_hash) == env.data["bundle_hash"]


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
    assert sources["src_none"]["note"] == "[REDACTED]"
    assert sources["src_none"]["excerpt"] == "[REDACTED]"


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


# -- recall receipts ---------------------------------------------------


def test_review_bundle_omits_recall_receipts_explicitly_when_absent(home):
    _seed_decision(home)
    env = _mcp(home, "review.bundle", {})
    assert env.ok, env
    receipt_block = env.data["recall_receipts"]
    assert receipt_block["status"] == "omitted"
    assert receipt_block["omissions"] == ["no_recall_receipts"]
    assert receipt_block["blocks"] == []
    assert receipt_block["truncated"] is False


def test_review_bundle_carries_decision_recall_receipt_caveats(home):
    db = open_database(db_path(home), create_parent=False)
    try:
        _seed_recall_receipts(db.connection)
        db.connection.execute(
            "INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "e-stale-decision",
                "decision",
                "dec",
                "memory_node",
                "mem-stale",
                "violates",
                None,
                "{}",
                "2026-01-01T00:07:00Z",
                "actor",
            ),
        )
        db.connection.commit()
    finally:
        db.close()

    env = _mcp(home, "review.bundle", {})
    assert env.ok, env
    receipt_block = env.data["recall_receipts"]
    assert receipt_block["status"] == "included"
    assert receipt_block["receipt_refs"] == [
        {"receipt_id": "recall_receipt:recall-1", "recall_id": "recall-1"}
    ]
    assert receipt_block["truncated"] is False
    assert "STALE_OR_INVALIDATED_MEMORY" in receipt_block["caveat_codes"]
    assert "HARMFUL_DOWNSTREAM" in receipt_block["caveat_codes"]
    assert receipt_block["blocks"][0]["consumer"] == {"kind": "decision", "id": "dec"}
    item_caveats = {
        item["node_id"]: item for item in receipt_block["blocks"][0]["item_caveats"]
    }
    assert "STALE_OR_INVALIDATED_MEMORY" in item_caveats["mem-stale"]["caveat_codes"]
    assert item_caveats["mem-stale"]["status"] == "cited_or_used"


def test_review_bundle_can_omit_recall_receipts_by_flag(home):
    _seed_decision(home)
    env = _mcp(home, "review.bundle", {"include_recall_receipts": False})
    assert env.ok, env
    assert env.data["recall_receipts"]["status"] == "omitted"
    assert env.data["recall_receipts"]["omissions"] == ["omitted_by_input_flag"]


# -- autonomous lifecycle ---------------------------------------------


def test_review_bundle_includes_autonomous_lifecycle_and_default_redacts(home):
    seeded = _seed_decision(home, extra_args={"run_id": "run-1"})
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            "INSERT INTO pretrade_intents(id, semantic_key, material_hash, instrument_id, "
            "decision_id, proposed_shape_json, as_of, created_at, actor_id) "
            "VALUES ('intent-1','sk-intent','hash-intent',?,?,?,?,?,?)",
            (
                seeded["instrument_id"], seeded["decision_id"],
                '{"condition_id":"condition_public_123","strategy_id":"strat-secret"}',
                "2026-05-20T00:00:00Z", "2026-05-20T00:00:01Z", "actor",
            ),
        )
        db.connection.execute(
            "INSERT INTO external_execution_receipts(id, schema_version, semantic_key, "
            "material_hash, lifecycle_state, external_event_type, pretrade_intent_id, "
            "instrument_id, external_order_ref, source_system, as_of, imported_at, "
            "artifact_hash, redacted_artifact_ref, actor_id) VALUES "
            "('ext-1','v1','sk-ext','hash-ext','filled','fill','intent-1',?,"
            "'order-private','importer','2026-05-20T00:00:02Z',"
            "'2026-05-20T00:00:03Z','artifact-hash','raw/ref/private','actor')",
            (seeded["instrument_id"],),
        )
        db.connection.execute(
            "INSERT INTO account_snapshots(id, schema_version, semantic_key, material_hash, "
            "source_system, source_run_id, confidence_label, staleness_status, account_label, captured_at, "
            "as_of, imported_at, artifact_hash, redacted_artifact_ref, actor_id) VALUES "
            "('acct-1','v1','sk-acct','hash-acct','importer','run-1','high','fresh',"
            "'acct-private','2026-05-20T00:00:00Z','2026-05-20T00:00:00Z',"
            "'2026-05-20T00:00:01Z','artifact','raw/acct','actor')",
        )
        db.connection.commit()
    finally:
        db.close()

    env = _mcp(home, "review.bundle", {})
    assert env.ok, env
    lifecycle = env.data["autonomous_lifecycle"]
    assert lifecycle["scope"]["decision_ids"] == [seeded["decision_id"]]
    assert lifecycle["record_counts"]["pretrade_intents"] == 1
    assert lifecycle["record_counts"]["external_execution_receipts"] == 1
    assert lifecycle["record_counts"]["account_snapshots"] == 1
    assert "not trading advice" in lifecycle["notice"]
    assert '"strategy_id":"[REDACTED]"' in lifecycle["records"]["pretrade_intents"][0]["proposed_shape_json"]
    assert lifecycle["records"]["external_execution_receipts"][0]["external_order_ref"] == "[REDACTED]"
    assert lifecycle["records"]["external_execution_receipts"][0]["redacted_artifact_ref"] == "[REDACTED]"
    assert lifecycle["records"]["account_snapshots"][0]["account_label"] == "[REDACTED]"
    assert "condition_public_123" in lifecycle["records"]["pretrade_intents"][0]["proposed_shape_json"]
    assert env.data["redaction_profile"] == "audit_export"
    assert env.data["redaction_summary"]["profile_replacements"] >= 4
    assert "profile labels" in env.data["redaction_summary"]["profile_scope"]


def test_review_bundle_fetches_forecast_scores_by_forecast_id(home):
    seeded = _seed_decision(home)
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            "INSERT INTO theses(id, instrument_id, side, body, created_at, actor_id) "
            "VALUES ('th-score', ?, 'yes', 'body', '2026-05-20T00:00:00Z', 'actor')",
            (seeded["instrument_id"],),
        )
        db.connection.execute(
            "INSERT INTO forecasts(id, thesis_id, kind, yes_label, scoring_state, "
            "created_at, actor_id) VALUES "
            "('fc-score', 'th-score', 'binary', 'yes', 'scored', "
            "'2026-05-20T00:00:01Z', 'actor')",
        )
        db.connection.execute(
            "INSERT INTO forecast_scores(id, forecast_id, metric, score, scored_at, actor_id) "
            "VALUES ('score-row-not-forecast-id', 'fc-score', 'brier', 0.25, "
            "'2026-05-20T00:00:02Z', 'actor')",
        )
        db.connection.execute(
            "INSERT INTO decisions(id, instrument_id, thesis_id, forecast_id, type, reason, "
            "metadata_json, created_at, actor_id) VALUES "
            "('dec-score', ?, 'th-score', 'fc-score', 'skip', 'score decision', '{}', "
            "'2026-05-20T00:00:03Z', 'agent:score')",
            (seeded["instrument_id"],),
        )
        db.connection.commit()
    finally:
        db.close()

    env = _mcp(home, "review.bundle", {
        "filter": {"actors": {"actor_id": ["agent:score"]}},
    })
    assert env.ok, env
    assert [r["id"] for r in env.data["selected"]["forecast_scores"]] == [
        "score-row-not-forecast-id"
    ]


def test_review_bundle_scopes_account_snapshots_and_reconciliation_records(home):
    selected = _seed_decision(
        home, actor_id="agent:selected", extra_args={"run_id": "run-selected"},
    )
    unrelated = _seed_decision(
        home, actor_id="agent:unrelated", extra_args={"run_id": "run-unrelated"},
    )
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            "INSERT INTO account_snapshots(id, schema_version, semantic_key, material_hash, "
            "source_system, source_run_id, confidence_label, staleness_status, account_label, "
            "captured_at, as_of, imported_at, artifact_hash, actor_id) VALUES "
            "('acct-related','v1','sk-ar','hash-ar','importer','run-selected','high','fresh',"
            "'acct-related','2026-05-20T00:00:00Z','2026-05-20T00:00:00Z',"
            "'2026-05-20T00:00:01Z','artifact-related','actor'),"
            "('acct-unrelated','v1','sk-au','hash-au','importer','run-unrelated','high','fresh',"
            "'acct-unrelated','2026-05-20T00:00:00Z','2026-05-20T00:00:00Z',"
            "'2026-05-20T00:00:01Z','artifact-unrelated','actor')",
        )
        db.connection.execute(
            "INSERT INTO reconciliation_records(id, schema_version, semantic_key, material_hash, "
            "as_of, source, diff_severity, resolution_status, contributing_ids_json, "
            "recorded_at, actor_id) VALUES "
            "('recon-related','v1','sk-rr','hash-rr','2026-05-20T00:00:00Z',"
            "'importer','info','unresolved',?, '2026-05-20T00:00:01Z','actor'),"
            "('recon-unrelated','v1','sk-ru','hash-ru','2026-05-20T00:00:00Z',"
            "'importer','info','unresolved',?, '2026-05-20T00:00:01Z','actor')",
            (
                json.dumps([selected["decision_id"]]),
                json.dumps([unrelated["decision_id"]]),
            ),
        )
        db.connection.commit()
    finally:
        db.close()

    env = _mcp(home, "review.bundle", {
        "filter": {"actors": {"actor_id": ["agent:selected"]}},
    })
    assert env.ok, env
    records = env.data["autonomous_lifecycle"]["records"]
    assert [r["id"] for r in records["account_snapshots"]] == ["acct-related"]
    assert [r["id"] for r in records["reconciliation_records"]] == ["recon-related"]


def test_review_bundle_json_scope_uses_exact_tokens_not_substrings(home):
    seeded = _seed_decision(home, actor_id="agent:selected")
    selected_id = seeded["decision_id"]
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            "INSERT INTO account_snapshots(id, schema_version, semantic_key, material_hash, "
            "source_system, confidence_label, staleness_status, captured_at, as_of, "
            "imported_at, artifact_hash, balances_json, actor_id) VALUES "
            "('acct-exact','v1','sk-ae','hash-ae','importer','high','fresh',"
            "'2026-05-20T00:00:00Z','2026-05-20T00:00:00Z',"
            "'2026-05-20T00:00:01Z','artifact-exact',?, 'actor'),"
            "('acct-substring','v1','sk-as','hash-as','importer','high','fresh',"
            "'2026-05-20T00:00:00Z','2026-05-20T00:00:00Z',"
            "'2026-05-20T00:00:01Z','artifact-substring',?, 'actor')",
            (
                json.dumps({"decision_id": selected_id}),
                json.dumps({"decision_id": f"{selected_id}0"}),
            ),
        )
        db.connection.execute(
            "INSERT INTO reconciliation_records(id, schema_version, semantic_key, material_hash, "
            "as_of, source, diff_severity, resolution_status, contributing_ids_json, "
            "recorded_at, actor_id) VALUES "
            "('recon-exact','v1','sk-re','hash-re','2026-05-20T00:00:00Z',"
            "'importer','info','unresolved',?, '2026-05-20T00:00:01Z','actor'),"
            "('recon-substring','v1','sk-rs','hash-rs','2026-05-20T00:00:00Z',"
            "'importer','info','unresolved',?, '2026-05-20T00:00:01Z','actor')",
            (json.dumps([selected_id]), json.dumps([f"{selected_id}0"])),
        )
        db.connection.commit()
    finally:
        db.close()

    env = _mcp(home, "review.bundle", {
        "filter": {"actors": {"actor_id": ["agent:selected"]}},
    })
    assert env.ok, env
    records = env.data["autonomous_lifecycle"]["records"]
    assert [r["id"] for r in records["account_snapshots"]] == ["acct-exact"]
    assert [r["id"] for r in records["reconciliation_records"]] == ["recon-exact"]


def test_review_bundle_json_token_predicate_treats_like_wildcards_literally():
    tokens = {"dec_1", "dec%2"}

    assert _json_value_has_exact_token({"ids": ["dec_1", {"id": "dec%2"}]}, tokens)
    assert not _json_value_has_exact_token({"ids": ["decA1", "decX2"]}, tokens)
    assert not _json_value_has_exact_token({"id": "prefix-dec_1-suffix"}, tokens)


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
