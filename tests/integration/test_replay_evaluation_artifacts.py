from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from tests.integration.test_replay_case_bundle import _bundle, _init_home, _seed_case
from trade_trace.core import dispatch
from trade_trace.storage.paths import db_path
from trade_trace.tools._helpers import CLOCK_OVERRIDE


def _ok(env):
    assert env.ok is True, env
    return env.data


def _init(home):
    _ok(dispatch("journal.init", {"home": str(home)}, actor_id="agent:tester"))


def _artifact_args(home, **overrides):
    args = {
        "home": str(home),
        "semantic_key": "eval:strategy-a:v1:dataset-a",
        "artifact_type": "historical_simulation",
        "evidence_mode": "historical_simulation",
        "dataset_hash": "sha256:dataset-a",
        "strategy_id": "strat-a",
        "strategy_version": "v1",
        "parameters": {"lookback_days": 7},
        "assumptions": {"external_engine": "caller-supplied"},
        "fill_model": {"kind": "external_midpoint"},
        "slippage_model": {"kind": "caller_supplied_bps", "bps": 3},
        "result_summary": {"trades": 12, "sample_size": 12},
        "sample_size": 12,
        "source_links": [{"label": "external report", "uri": "file://redacted/eval.json"}],
        "provenance": {"tool": "external-evaluator", "version": "0.1"},
        "caveats": [{"code": "imported_result"}],
        "redaction_profile": "metadata_only",
        "redacted_artifact_ref": "artifact://redacted/eval-a",
        "as_of": "2026-01-10T00:00:00Z",
        "evaluated_at": "2026-01-10T01:00:00Z",
        "idempotency_key": "idem-eval-a",
    }
    args.update(overrides)
    return args


def test_replay_artifact_record_get_list_and_idempotent_replay(tmp_path):
    _init(tmp_path)
    first = _ok(dispatch("replay_artifact.record", _artifact_args(tmp_path), actor_id="agent:tester"))
    second = _ok(dispatch("replay_artifact.record", _artifact_args(tmp_path), actor_id="agent:tester"))
    assert second["id"] == first["id"]
    assert first["dataset_hash"] == "sha256:dataset-a"
    assert first["strategy_version"] == "v1"
    assert first["non_executing"] is True
    assert first["candidate_visible"] is False
    assert any(c.get("code") == "small_sample_size" for c in first["caveats"])

    got = _ok(dispatch("replay_artifact.get", {"home": str(tmp_path), "id": first["id"]}, actor_id="agent:tester"))
    assert got["material_hash"] == first["material_hash"]
    listed = _ok(dispatch("replay_artifact.list", {"home": str(tmp_path), "evidence_mode": "historical_simulation"}, actor_id="agent:tester"))
    assert listed["count"] == 1
    assert "not Trade Trace backtest" in listed["report_caveats"][0]


def test_replay_artifact_semantic_conflict_and_secret_rejection(tmp_path):
    _init(tmp_path)
    _ok(dispatch("replay_artifact.record", _artifact_args(tmp_path, idempotency_key="idem-one"), actor_id="agent:tester"))
    conflict = dispatch("replay_artifact.record", _artifact_args(tmp_path, dataset_hash="sha256:other", idempotency_key="idem-two"), actor_id="agent:tester")
    assert conflict.ok is False
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"

    secret = dispatch("replay_artifact.record", _artifact_args(tmp_path, semantic_key="eval:secret", dataset_hash="xoxb-abcdef", idempotency_key="idem-secret"), actor_id="agent:tester")
    assert secret.ok is False


def test_replay_artifact_material_hash_conflict_is_controlled(tmp_path):
    _init(tmp_path)
    first = _ok(dispatch("replay_artifact.record", _artifact_args(tmp_path, idempotency_key="idem-one"), actor_id="agent:tester"))
    conn = sqlite3.connect(db_path(tmp_path))
    try:
        conn.execute("DROP TRIGGER trg_replay_evaluation_artifacts_no_update")
        conn.execute(
            "UPDATE replay_evaluation_artifacts SET semantic_key = ? WHERE id = ?",
            ("eval:legacy-conflicting-semantic", first["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    conflict = dispatch("replay_artifact.record", _artifact_args(tmp_path, idempotency_key="idem-two"), actor_id="agent:tester")

    assert conflict.ok is False
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"
    assert conflict.error.details["code"] == "material_hash_conflict"
    assert conflict.error.details["existing_semantic_key"] == "eval:legacy-conflicting-semantic"


def test_replay_case_bundle_keeps_artifact_refs_evaluator_only(tmp_path):
    home = _init_home(tmp_path)
    strategy = _ok(dispatch("strategy.upsert", {"home": str(home), "slug": "strategy-a", "name": "Strategy A", "idempotency_key": "strategy-a"}, actor_id="agent:tester"))
    ids = _seed_case(home, thesis_overrides={"strategy_id": strategy["id"]})
    token = CLOCK_OVERRIDE.set(datetime(2026, 5, 19, 1, 0, 0, tzinfo=UTC))
    try:
        artifact = _ok(dispatch("replay_artifact.record", _artifact_args(home, strategy_id=strategy["id"], as_of="2026-05-19T00:00:00Z"), actor_id="agent:tester"))
    finally:
        CLOCK_OVERRIDE.reset(token)
    bundle = _bundle(home, case_selection={"source_refs": [{"kind": "decision", "id": ids["decision"]}]}, task={"include_evaluation_labels": True})["data"]
    candidate_text = json.dumps(bundle.get("cases", []))
    assert artifact["id"] not in candidate_text
    assert bundle["evaluation_labels"]["labels"][0]["replay_evaluation_artifact_refs"][0]["id"] == artifact["id"]
    assert bundle["leakage_protections"]["evaluation_labels_separated"] is True


def test_replay_case_bundle_withheld_labels_hide_artifact_refs_from_full_bundle(tmp_path):
    home = _init_home(tmp_path)
    strategy = _ok(dispatch("strategy.upsert", {"home": str(home), "slug": "strategy-a", "name": "Strategy A", "idempotency_key": "strategy-a"}, actor_id="agent:tester"))
    ids = _seed_case(home, thesis_overrides={"strategy_id": strategy["id"]})
    token = CLOCK_OVERRIDE.set(datetime(2026, 5, 19, 1, 0, 0, tzinfo=UTC))
    try:
        artifact = _ok(dispatch("replay_artifact.record", _artifact_args(home, strategy_id=strategy["id"], as_of="2026-05-19T00:00:00Z"), actor_id="agent:tester"))
    finally:
        CLOCK_OVERRIDE.reset(token)

    bundle = _bundle(home, case_selection={"source_refs": [{"kind": "decision", "id": ids["decision"]}]}, task={"include_evaluation_labels": False})["data"]

    assert bundle["evaluation_labels"]["status"] == "withheld"
    assert artifact["id"] not in json.dumps(bundle, sort_keys=True)
    assert artifact["redacted_artifact_ref"] not in json.dumps(bundle, sort_keys=True)
