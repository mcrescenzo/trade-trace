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


def _seed_risk_context(home) -> str:
    conn = sqlite3.connect(db_path(home))
    try:
        conn.execute(
            "INSERT INTO risk_policy_versions(id, policy_key, version, policy_hash, limits_json, rules_json, source, provenance_json, effective_from, created_at, actor_id) "
            "VALUES ('rpv_approval_lifecycle', 'approval-ledger-test', 'v1', 'hash-approval-ledger-test', '{}', '[]', 'test', '{}', '2026-05-28T00:00:00.000Z', '2026-05-28T00:00:00.000Z', 'agent:test')",
        )
        conn.execute(
            "INSERT INTO risk_check_receipts(id, receipt_hash, policy_version_id, status, outcome, intended_action, market_id, instrument_id, exposure_input_ids_json, evidence_input_ids_json, input_provenance_json, as_of, created_at, actor_id) "
            "VALUES ('rcr_approval_lifecycle', 'receipt-hash-approval-ledger-test', 'rpv_approval_lifecycle', 'missing_data', 'missing_data', 'pretrade_review', 'm_pm_1', 'i_1', '[]', '[\"s_1\"]', '{}', '2026-05-28T00:00:00.000Z', '2026-05-28T00:00:00.000Z', 'agent:test')",
        )
        conn.commit()
    finally:
        conn.close()
    return "rcr_approval_lifecycle"


def _record_and_replay(home, args):
    first = _call("approval.record", args)
    assert first.ok, first
    replay = _call("approval.record", args)
    assert replay.ok, replay
    assert replay.data["id"] == first.data["id"]
    assert replay.meta.idempotent_replay is True
    return first


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


def test_denial_and_modification_lifecycle_records_link_and_list(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    risk_receipt_id = _seed_risk_context(home)

    denial_args = _approval_args(home, intent_id, semantic_key="approval-denial", record_type="denial", decision="denied")
    denial_args.update({"risk_check_receipt_id": risk_receipt_id, "reason": "Risk check denied this proposed shape."})
    denial = _record_and_replay(home, denial_args)
    assert denial.data["record_type"] == "denial"
    assert denial.data["decision"] == "denied"
    assert denial.data["pretrade_intent_id"] == intent_id
    assert denial.data["risk_check_receipt_id"] == risk_receipt_id

    modification_args = _approval_args(home, intent_id, semantic_key="approval-modification", record_type="modification", decision="modified")
    modification_args.update({
        "risk_check_receipt_id": risk_receipt_id,
        "modifications": {"limit_price": "0.38", "quantity": "7"},
        "reason": "Supervisor accepted a smaller, lower-price review packet.",
    })
    modification = _record_and_replay(home, modification_args)
    assert modification.data["record_type"] == "modification"
    assert modification.data["decision"] == "modified"
    assert modification.data["modifications"] == {"limit_price": "0.38", "quantity": "7"}
    assert modification.data["pretrade_intent_id"] == intent_id
    assert modification.data["risk_check_receipt_id"] == risk_receipt_id

    listed = _call("approval.list", {"home": str(home), "pretrade_intent_id": intent_id, "risk_check_receipt_id": risk_receipt_id})
    assert listed.ok, listed
    listed_by_type = {record["record_type"]: record for record in listed.data["records"]}
    assert listed_by_type["denial"]["id"] == denial.data["id"]
    assert listed_by_type["modification"]["id"] == modification.data["id"]
    assert all(record["pretrade_intent_id"] == intent_id for record in listed.data["records"])
    assert all(record["risk_check_receipt_id"] == risk_receipt_id for record in listed.data["records"])


def test_expiry_and_revocation_lifecycle_records_are_append_only_links(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    risk_receipt_id = _seed_risk_context(home)

    expiry_args = _approval_args(home, intent_id, semantic_key="approval-expiry", record_type="expiry", decision="expired")
    expiry_args.update({"risk_check_receipt_id": risk_receipt_id, "expires_at": "2026-05-28T00:30:00.000Z"})
    expiry = _record_and_replay(home, expiry_args)
    assert expiry.data["record_type"] == "expiry"
    assert expiry.data["decision"] == "expired"
    assert expiry.data["expires_at"] == "2026-05-28T00:30:00.000Z"
    assert expiry.data["pretrade_intent_id"] == intent_id
    assert expiry.data["risk_check_receipt_id"] == risk_receipt_id

    revocation_args = _approval_args(home, intent_id, semantic_key="approval-revocation", record_type="revocation", decision="revoked")
    revocation_args.update({
        "risk_check_receipt_id": risk_receipt_id,
        "revoked_at": "2026-05-28T00:45:00.000Z",
        "revocation_reason": "New information invalidated the local review evidence.",
    })
    revocation = _record_and_replay(home, revocation_args)
    assert revocation.data["record_type"] == "revocation"
    assert revocation.data["decision"] == "revoked"
    assert revocation.data["revoked_at"] == "2026-05-28T00:45:00.000Z"
    assert revocation.data["revocation_reason"] == "New information invalidated the local review evidence."
    assert revocation.data["pretrade_intent_id"] == intent_id
    assert revocation.data["risk_check_receipt_id"] == risk_receipt_id

    listed = _call("approval.list", {"home": str(home), "pretrade_intent_id": intent_id, "risk_check_receipt_id": risk_receipt_id})
    assert listed.ok, listed
    assert {record["record_type"] for record in listed.data["records"]} == {"expiry", "revocation"}


def test_missing_data_waiver_lifecycle_records_caveats_and_links(tmp_path):
    home = tmp_path / "home"
    intent_id = _seed_refs(home)
    risk_receipt_id = _seed_risk_context(home)

    args = _approval_args(home, intent_id, semantic_key="waiver-missing-data", record_type="missing_data_waiver", decision="waived")
    args.update({
        "risk_check_receipt_id": risk_receipt_id,
        "caveats": [{"code": "missing_or_stale_inputs", "message": "Volume history was unavailable for this local review."}],
        "reason": "Human supervisor accepted the explicit missing-data caveat.",
    })
    waiver = _record_and_replay(home, args)
    assert waiver.data["record_type"] == "missing_data_waiver"
    assert waiver.data["decision"] == "waived"
    assert waiver.data["waiver_class"] == "missing_data"
    assert waiver.data["caveats"] == [{"code": "missing_or_stale_inputs", "message": "Volume history was unavailable for this local review."}]
    assert waiver.data["pretrade_intent_id"] == intent_id
    assert waiver.data["risk_check_receipt_id"] == risk_receipt_id

    listed = _call("approval.list", {"home": str(home), "record_type": "missing_data_waiver", "risk_check_receipt_id": risk_receipt_id})
    assert listed.ok, listed
    assert listed.data["count"] == 1
    assert listed.data["records"][0]["pretrade_intent_id"] == intent_id


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
