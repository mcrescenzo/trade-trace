from __future__ import annotations

import sqlite3

from trade_trace.core import dispatch
from trade_trace.storage.paths import db_path


def _call(tool: str, args: dict, *, actor_id: str = "agent:approval"):
    return dispatch(tool, args, actor_id=actor_id)


def _seed_refs(home):
    _call("journal.init", {"home": str(home)}, actor_id="agent:init")
    conn = sqlite3.connect(db_path(home))
    try:
        conn.execute("INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) VALUES ('v_1', 'Polymarket', 'prediction_market', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.execute("INSERT INTO instruments(id, venue_id, external_id, symbol, title, asset_class, metadata_json, created_at, actor_id) VALUES ('i_1', 'v_1', 'abc-yes', 'PM-ABC-YES', 'PM ABC YES', 'prediction_market', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.execute("INSERT INTO markets(id, source, external_id, title, question, state, mechanism, bound_via, venue_metadata_json, metadata_json, created_at, actor_id) VALUES ('m_pm_1', 'polymarket', 'abc', 'ABC?', 'ABC?', 'open', 'clob', 'manual', '{}', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.execute("INSERT INTO sources(id, kind, ref, title, note, stance, freshness_at, uri, summary, metadata_json, created_at, actor_id) VALUES ('s_1', 'url', 'https://example.invalid/evidence', 'Evidence', 'Caller supplied evidence.', 'supports', '2026-05-27T00:00:00.000Z', 'https://example.invalid/evidence', 'Caller supplied evidence.', '{}', '2026-05-28T00:00:00.000Z', 'agent:test')")
        conn.commit()
    finally:
        conn.close()
    env = _call("pretrade_intent.record", {
        "home": str(home), "semantic_key": "intent-approval-test", "market_id": "m_pm_1", "instrument_id": "i_1",
        "proposed_shape": {"side": "yes", "limit_price": "0.42", "quantity": "10"},
        "risk_budget": {"max_loss": "4.20"}, "evidence_refs": [{"kind": "source", "id": "s_1"}], "source_ids": ["s_1"],
        "as_of": "2026-05-28T00:00:00.000Z", "idempotency_key": "intent-approval-test",
    })
    assert env.ok, env
    return env.data["id"]


def _approval_args(home, intent_id, *, semantic_key="approval-1", record_type="approval", decision="approved"):
    return {
        "home": str(home), "semantic_key": semantic_key, "record_type": record_type, "decision": decision,
        "pretrade_intent_id": intent_id, "market_id": "m_pm_1", "instrument_id": "i_1",
        "actor_mode": "human", "decision_actor_id": "human:supervisor", "decision_at": "2026-05-28T00:01:00.000Z",
        "scope": {"side": "yes", "max_quantity": "10"}, "limits": {"max_loss": "4.20"}, "expires_at": "2026-05-28T01:00:00.000Z",
        "policy_version": "risk-policy.v1", "environment_label": "paper-review", "account_label": "acct-label", "idempotency_key": semantic_key,
        "provenance_json": {"test": True},
    }


def test_approval_record_links_idempotent_and_reports(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    first = _call("approval.record", _approval_args(home, intent_id))
    assert first.ok, first
    assert first.data["record_kind"] == "local_approval_waiver_autonomy_audit"
    assert first.data["pretrade_intent_id"] == intent_id
    assert first.data["scope"]["max_quantity"] == "10"

    replay = _call("approval.record", _approval_args(home, intent_id))
    assert replay.ok, replay
    assert replay.data["id"] == first.data["id"]
    assert replay.meta.idempotent_replay is True

    report = _call("approval.report", {"home": str(home), "pretrade_intent_id": intent_id})
    assert report.ok, report
    assert report.data["groups"][0]["proposed"]["proposed_shape"]["side"] == "yes"
    assert "Externally imported execution activity unavailable/not imported" in report.data["groups"][0]["caveats"][0]


def test_waivers_and_hard_block_attempt_visibility(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    warning = _approval_args(home, intent_id, semantic_key="waiver-warning", record_type="warning_waiver", decision="waived")
    env = _call("approval.record", warning)
    assert env.ok, env
    assert env.data["waiver_class"] == "warning"

    hard = _approval_args(home, intent_id, semantic_key="hard-block", record_type="hard_block_override_attempt", decision="attempted")
    hard_env = _call("approval.record", hard)
    assert hard_env.ok, hard_env
    assert hard_env.data["violation_visible"] is True
    assert any(c["code"] == "hard_block_override_attempt_violation" for c in hard_env.data["caveats"])

    asserted = _approval_args(home, intent_id, semantic_key="hard-block-asserted", record_type="hard_block_override_attempt", decision="attempted")
    asserted["hard_block_policy_permitted"] = True
    asserted_env = _call("approval.record", asserted)
    assert asserted_env.ok, asserted_env
    assert asserted_env.data["hard_block_policy_permitted"] is True
    assert asserted_env.data["violation_visible"] is True
    assert asserted_env.data["policy_evidence"]["caller_asserted_policy_permits_hard_block_override"] is True
    assert any(c["code"] == "hard_block_override_attempt_violation" for c in asserted_env.data["caveats"])
    assert any(
        c["code"] == "hard_block_policy_assertion_unverified"
        and "audit evidence only" in c["message"]
        and "not locally verified" in c["message"]
        for c in asserted_env.data["caveats"]
    )


def test_approval_append_only_trigger_and_conflict(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    env = _call("approval.record", _approval_args(home, intent_id))
    assert env.ok, env
    changed = _approval_args(home, intent_id)
    changed["idempotency_key"] = "approval-1-different"
    changed["limits"] = {"max_loss": "5.00"}
    conflict = _call("approval.record", changed)
    assert not conflict.ok
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"

    conn = sqlite3.connect(db_path(home))
    try:
        try:
            conn.execute("UPDATE approval_waiver_records SET decision = 'revoked' WHERE id = ?", (env.data["id"],))
        except sqlite3.DatabaseError as exc:
            assert "append-only invariant" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("append-only update unexpectedly succeeded")
    finally:
        conn.close()


def test_approval_rejects_secret_in_scope(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    args = _approval_args(home, intent_id, semantic_key="bad-secret")
    args["scope"] = {"private_key": "not stored"}
    bad = _call("approval.record", args)
    assert not bad.ok
    assert bad.error.code == "VALIDATION_ERROR"
    assert bad.error.details["field"] == "scope"
