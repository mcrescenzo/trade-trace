from __future__ import annotations

import sqlite3

from trade_trace.core import dispatch
from trade_trace.storage.paths import db_path


def _call(tool: str, args: dict, *, actor_id: str = "agent:intent"):
    return dispatch(tool, args, actor_id=actor_id)


def _base(home):
    return {
        "home": str(home),
        "semantic_key": "pm:market:abc:yes:2026-05-28T00:00Z",
        "market_id": "m_pm_1",
        "instrument_id": "i_1",
        "proposed_shape": {"venue_family": "polymarket", "side": "yes", "limit_price": "0.42", "quantity": "10", "time_in_force": "caller_supplied"},
        "risk_budget": {"max_loss": "4.20", "unit": "USDC"},
        "evidence_refs": [{"kind": "source", "id": "s_1"}],
        "source_ids": ["s_1"],
        "as_of": "2026-05-28T00:00:00.000Z",
        "idempotency_key": "intent-key-1",
        "provenance_json": {"caller": "test"},
    }


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


def test_pretrade_intent_record_read_and_list_idempotent(tmp_path):
    home = tmp_path / "home"
    _seed_refs(home)
    first = _call("pretrade_intent.record", _base(home))
    assert first.ok, first
    data = first.data
    assert data["record_kind"] == "proposed_local_pretrade_intent"
    assert data["non_executing"] is True
    assert data["market_id"] == "m_pm_1"
    assert data["source_ids"] == ["s_1"]

    replay = _call("pretrade_intent.record", _base(home))
    assert replay.ok, replay
    assert replay.data["id"] == data["id"]
    assert replay.data["material_hash"] == data["material_hash"]
    assert replay.meta.idempotent_replay is True

    got = _call("pretrade_intent.get", {"home": str(home), "id": data["id"]})
    assert got.ok
    assert got.data["semantic_key"] == data["semantic_key"]

    listed = _call("pretrade_intent.list", {"home": str(home), "market_id": "m_pm_1"})
    assert listed.ok
    assert listed.data["count"] == 1
    assert listed.data["records"][0]["id"] == data["id"]


def test_pretrade_intent_semantic_conflict(tmp_path):
    home = tmp_path / "home"
    _seed_refs(home)
    assert _call("pretrade_intent.record", _base(home)).ok
    changed = _base(home)
    changed["idempotency_key"] = "intent-key-2"
    changed["proposed_shape"] = {**changed["proposed_shape"], "limit_price": "0.43"}
    conflict = _call("pretrade_intent.record", changed)
    assert not conflict.ok
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"


def test_pretrade_intent_missing_and_stale_evidence_caveats(tmp_path):
    home = tmp_path / "home"
    _seed_refs(home)
    args = _base(home)
    args["semantic_key"] = "missing-evidence"
    args["idempotency_key"] = "missing-evidence"
    args["evidence_refs"] = []
    args["source_ids"] = []
    args["evidence_stale"] = True
    env = _call("pretrade_intent.record", args)
    assert env.ok, env
    codes = {c["code"] for c in env.data["caveats"]}
    assert {"missing_evidence_refs", "stale_evidence"} <= codes


def test_pretrade_intent_rejects_missing_reference(tmp_path):
    home = tmp_path / "home"
    _seed_refs(home)
    args = _base(home)
    args["source_ids"] = ["missing-source"]
    bad = _call("pretrade_intent.record", args)
    assert not bad.ok
    assert bad.error.code == "VALIDATION_ERROR"
    assert bad.error.details["missing_refs"][0]["table"] == "sources"


def test_pretrade_intent_rejects_credential_key_in_proposed_shape(tmp_path):
    home = tmp_path / "home"
    _seed_refs(home)
    args = _base(home)
    args["semantic_key"] = "credential-proposed-shape"
    args["idempotency_key"] = "credential-proposed-shape"
    args["proposed_shape"] = {**args["proposed_shape"], "private_key": "not-for-journal"}

    bad = _call("pretrade_intent.record", args)

    assert not bad.ok
    assert bad.error.code == "VALIDATION_ERROR"
    assert bad.error.details["field"] == "proposed_shape"
    assert bad.error.details["credential_key"] == "private_key"


def test_pretrade_intent_rejects_nested_secret_pattern_in_evidence_refs(tmp_path):
    home = tmp_path / "home"
    _seed_refs(home)
    args = _base(home)
    args["semantic_key"] = "secret-evidence-ref"
    args["idempotency_key"] = "secret-evidence-ref"
    secret = "s" + "k" + "-" + "a" * 20
    args["evidence_refs"] = [
        {"kind": "source", "id": "s_1", "nested": {"note": f"token {secret}"}}
    ]

    bad = _call("pretrade_intent.record", args)

    assert not bad.ok
    assert bad.error.code == "VALIDATION_ERROR"
    assert bad.error.details["field"] == "evidence_refs"
    assert "pattern_kind" in bad.error.details


# ---------------------------------------------------------------------------
# Section-9 lifecycle fixtures (autonomous-trader-substrate.md §9; bead
# trade-trace-2g47): an intent is derived as "awaiting check" until it links an
# immutable risk_check_receipts row, then "with check" surfacing the receipt's
# verdict status. No mutable status column — the lifecycle view is derived from
# the append-only risk.check_record receipt the intent points at.
# ---------------------------------------------------------------------------


def _record_pass_receipt(home) -> str:
    """Run the public risk.evaluate -> risk.check_record loop and return the
    immutable receipt id an intent can link via risk_check_receipt_id."""

    policy = _call(
        "risk.policy_version_add",
        {
            "home": str(home),
            "policy_key": "pm-default",
            "version": "1",
            "rules_json": [],
            "source": "operator",
            "effective_from": "2026-05-28T00:00:00.000Z",
            "idempotency_key": "policy-1",
        },
        actor_id="agent:risk",
    )
    assert policy.ok, policy
    policy_version_id = policy.data["id"]

    receipt = _call(
        "risk.check_record",
        {
            "home": str(home),
            "policy_version_id": policy_version_id,
            "status": "pass",
            "outcome": "pass",
            "rule_results": [],
            "as_of": "2026-05-28T00:00:00.000Z",
            "market_id": "m_pm_1",
            "idempotency_key": "receipt-1",
        },
        actor_id="agent:risk",
    )
    assert receipt.ok, receipt
    return receipt.data["id"]


def test_pretrade_intent_awaiting_check_lifecycle(tmp_path):
    """§9 fixture: an intent with no linked receipt is derived as not-evaluated."""

    home = tmp_path / "home"
    _seed_refs(home)
    env = _call("pretrade_intent.record", _base(home))
    assert env.ok, env
    evaluation = env.data["evaluation"]
    assert evaluation == {"evaluated": False, "risk_check_receipt_id": None, "status": None}

    got = _call("pretrade_intent.get", {"home": str(home), "id": env.data["id"]})
    assert got.ok
    assert got.data["evaluation"]["evaluated"] is False

    listed = _call("pretrade_intent.list", {"home": str(home), "market_id": "m_pm_1"})
    assert listed.ok
    assert listed.data["records"][0]["evaluation"]["evaluated"] is False


def test_pretrade_intent_with_check_lifecycle(tmp_path):
    """§9 fixture: an intent linking a risk_check_receipt is derived as evaluated
    and surfaces the receipt's verdict status on get and list."""

    home = tmp_path / "home"
    _seed_refs(home)
    receipt_id = _record_pass_receipt(home)

    args = _base(home)
    args["semantic_key"] = "intent-with-check"
    args["idempotency_key"] = "intent-with-check"
    args["risk_check_receipt_id"] = receipt_id
    env = _call("pretrade_intent.record", args)
    assert env.ok, env
    assert env.data["risk_check_receipt_id"] == receipt_id
    assert env.data["evaluation"] == {
        "evaluated": True,
        "risk_check_receipt_id": receipt_id,
        "status": "pass",
    }

    got = _call("pretrade_intent.get", {"home": str(home), "id": env.data["id"]})
    assert got.ok
    assert got.data["evaluation"]["evaluated"] is True
    assert got.data["evaluation"]["status"] == "pass"

    listed = _call("pretrade_intent.list", {"home": str(home), "market_id": "m_pm_1"})
    assert listed.ok
    record = next(r for r in listed.data["records"] if r["id"] == env.data["id"])
    assert record["evaluation"]["status"] == "pass"


def test_pretrade_intent_record_rejects_unknown_risk_check_receipt(tmp_path):
    """The risk_check_receipt_id link is FK-validated, so an intent cannot claim
    to be evaluated against a receipt that does not exist."""

    home = tmp_path / "home"
    _seed_refs(home)
    args = _base(home)
    args["semantic_key"] = "intent-bad-receipt"
    args["idempotency_key"] = "intent-bad-receipt"
    args["risk_check_receipt_id"] = "rcr_missing"
    bad = _call("pretrade_intent.record", args)
    assert not bad.ok
    assert bad.error.code == "VALIDATION_ERROR"
    tables = {m["table"] for m in bad.error.details["missing_refs"]}
    assert "risk_check_receipts" in tables


def test_pretrade_intent_cluster_is_not_frozen():
    """Freeze-state regression (bead trade-trace-2g47).

    The pre-trade intent cluster was unfrozen into the public Phase-2 catalog.
    Pin that non-experimental state so a future accidental re-freeze (re-adding
    pretrade_intent.* to EXPERIMENTAL_AUTONOMOUS_OPS) is caught here.
    """

    from trade_trace.core import (
        EXPERIMENTAL_AUTONOMOUS_OPS,
        EXPERIMENTAL_FROZEN_TOOLS,
        build_registry,
    )

    reg = build_registry()
    public = set(reg.public_names())
    for name in ("pretrade_intent.record", "pretrade_intent.get", "pretrade_intent.list"):
        entry = reg.get(name)
        assert entry is not None, f"{name} should be registered"
        assert entry.catalog_visibility != "experimental", (
            f"{name} regressed to catalog_visibility=experimental; the pre-trade "
            "intent cluster was unfrozen in trade-trace-2g47"
        )
        assert name in public, f"{name} must appear in the default public catalog"
        assert name not in EXPERIMENTAL_AUTONOMOUS_OPS, (
            f"{name} was re-added to EXPERIMENTAL_AUTONOMOUS_OPS"
        )
        assert name not in EXPERIMENTAL_FROZEN_TOOLS, (
            f"{name} re-entered the frozen-tools union"
        )
