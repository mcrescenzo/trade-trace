from __future__ import annotations

import json

import pytest

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _seed_decision(home):
    venue_env = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    assert venue_env.ok, venue_env
    venue = venue_env.data["id"]
    instrument_env = _mcp(home, "instrument.add", {
        "venue_id": venue,
        "title": "Policy lifecycle test instrument",
        "asset_class": "prediction_market",
    })
    assert instrument_env.ok, instrument_env
    instrument = instrument_env.data["id"]
    decision_env = _mcp(home, "decision.add", {
        "instrument_id": instrument,
        "type": "skip",
        "reason": "policy lifecycle seed",
    })
    assert decision_env.ok, decision_env
    return decision_env.data["id"]


def _policy_meta(status: str, **overrides):
    candidate = {
        "status": status,
        "candidate_statement": "Process-only candidate: require scoped review before changing rules.",
        "scope": {
            "strategy_id": "strat_policy_lifecycle",
            "playbook_id": "pb_policy_lifecycle",
            "agent": {"agent_id": ["agent-test"], "model_id": ["model-test"]},
        },
        "evidence": {
            "reflection_ids": [],
            "support_case_count": 1,
            "contradiction_case_count": 0,
            "caveats": ["single_reflection_not_policy"],
        },
    }
    candidate.update(overrides)
    return {"policy_candidate": candidate}


def _reflect(home, decision_id, meta_json):
    return _mcp(home, "memory.reflect", {
        "target_kind": "decision",
        "target_id": decision_id,
        "body": "Reflection with policy-candidate lifecycle metadata.",
        "meta_json": meta_json,
        "idempotency_key": f"policy-{meta_json['policy_candidate']['status']}-{len(json.dumps(meta_json, sort_keys=True))}",
    })


@pytest.mark.parametrize("status", [
    "raw_reflection",
    "candidate_policy",
    "quarantined",
    "needs_more_evidence",
    "rejected",
    "promoted_to_playbook",
    "superseded",
])
def test_policy_candidate_lifecycle_statuses_are_valid_and_persisted(home, status):
    decision_id = _seed_decision(home)
    if status == "raw_reflection":
        meta = {"policy_candidate": {"status": status}}
    elif status == "rejected":
        meta = _policy_meta(status, rejection_reason="Contradictory cases make this too broad.")
    elif status == "promoted_to_playbook":
        meta = _policy_meta(status, playbook_version_id="pbv_explicit_external_write")
    elif status == "superseded":
        meta = _policy_meta(status, superseded_by="mem_successor_reflection")
    else:
        meta = _policy_meta(status)

    env = _reflect(home, decision_id, meta)
    assert env.ok, env

    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT meta_json FROM memory_nodes WHERE id = ?", (env.data["id"],)
        ).fetchone()
    finally:
        db.close()
    assert json.loads(row[0])["policy_candidate"]["status"] == status


def test_policy_candidate_rejects_invalid_status(home):
    decision_id = _seed_decision(home)
    env = _reflect(home, decision_id, _policy_meta("eligible_for_promotion"))
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "meta_json.policy_candidate.status"


@pytest.mark.parametrize("strategy_scope", [
    {"strategy_id": ""},
    {"strategy_id": "   "},
    {"strategy_id": None},
    {"strategy_ids": []},
    {"strategy_ids": [""]},
    {"strategy_ids": ["strat_policy_lifecycle", ""]},
    {"strategy_ids": None},
    {"strategy_scope": ""},
    {"strategy_scope": "   "},
    {"strategy_scope": None},
    {"playbook_id": "pb_policy_lifecycle"},
])
def test_policy_candidate_requires_meaningful_strategy_scope(home, strategy_scope):
    decision_id = _seed_decision(home)
    meta = _policy_meta("candidate_policy")
    meta["policy_candidate"]["scope"] = strategy_scope
    env = _reflect(home, decision_id, meta)
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["reason"] == "missing_strategy_scope"


@pytest.mark.parametrize("strategy_scope", [
    {"strategy_id": "strat_policy_lifecycle"},
    {"strategy_ids": ["strat_policy_lifecycle"]},
    {"strategy_ids": ["strat_policy_lifecycle", "strat_policy_secondary"]},
    {"strategy_scope": "global_candidate"},
    {"strategy_scope": "none"},
    {"strategy_id": "", "strategy_scope": "global_candidate"},
])
def test_policy_candidate_accepts_meaningful_strategy_scope(home, strategy_scope):
    decision_id = _seed_decision(home)
    meta = _policy_meta("candidate_policy")
    meta["policy_candidate"]["scope"] = strategy_scope
    env = _reflect(home, decision_id, meta)
    assert env.ok, env


def test_policy_candidate_requires_evidence_for_candidate_and_promotion(home):
    decision_id = _seed_decision(home)
    for status in ("candidate_policy", "promoted_to_playbook"):
        meta = _policy_meta(status, playbook_version_id="pbv_for_promotion")
        del meta["policy_candidate"]["evidence"]
        env = _reflect(home, decision_id, meta)
        assert env.ok is False
        assert env.error.code.value == "VALIDATION_ERROR"
        assert env.error.details["field"] == "meta_json.policy_candidate.evidence"


def test_rejected_and_superseded_require_audit_fields(home):
    decision_id = _seed_decision(home)
    rejected = _reflect(home, decision_id, _policy_meta("rejected"))
    assert rejected.ok is False
    assert rejected.error.details["field"] == "meta_json.policy_candidate.rejection_reason"

    superseded = _reflect(home, decision_id, _policy_meta("superseded"))
    assert superseded.ok is False
    assert superseded.error.details["field"] == "meta_json.policy_candidate.superseded_by"


def test_promoted_metadata_does_not_auto_mutate_playbook(home):
    decision_id = _seed_decision(home)
    before = _count_playbook_versions(home)
    env = _reflect(
        home,
        decision_id,
        _policy_meta("promoted_to_playbook", playbook_version_id="pbv_separate_explicit_write"),
    )
    assert env.ok, env
    assert _count_playbook_versions(home) == before


def _count_playbook_versions(home) -> int:
    db = open_database(db_path(home), create_parent=False)
    try:
        return db.connection.execute("SELECT COUNT(*) FROM playbook_versions").fetchone()[0]
    finally:
        db.close()
