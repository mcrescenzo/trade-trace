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
