"""Coach integration of override outcomes per bead trade-trace-722.

When `decision_playbook_rules.status='overridden'`, the coach packet's
`override_outcomes` panel surfaces the count + sample_decision_ids and
whether subsequent outcomes exist on those decisions' instruments.

The panel stays descriptive (no trade advice) per the forbidden-phrases
gate baked into _assert_no_trade_advice.
"""

from __future__ import annotations

from pathlib import Path

from tests._mcp_helpers import mcp_default as _mcp


def _seed_decision_with_override(home: Path, *, suffix: str,
                                  with_outcome: bool = False) -> dict:
    """Walk venue → instrument → thesis → decision → playbook → version
    → rule → record_adherence(overridden) and optionally add a
    subsequent outcome row."""

    venue = _mcp(home, "venue.add", {
        "name": f"V-{suffix}", "kind": "prediction_market",
        "idempotency_key": f"00000000-0000-4000-8000-co-v-{suffix}",
    }).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market",
        "title": f"X-{suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-co-i-{suffix}",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "t",
        "idempotency_key": f"00000000-0000-4000-8000-co-t-{suffix}",
    }).data["id"]
    decision = _mcp(home, "decision.add", {
        "type": "actual_enter", "instrument_id": inst,
        "thesis_id": thesis, "side": "yes",
        "quantity": 1, "price": 0.5,
        "idempotency_key": f"00000000-0000-4000-8000-co-d-{suffix}",
    }).data["id"]
    pb = _mcp(home, "playbook.upsert", {
        "name": f"PB-Co-{suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-co-pb-{suffix}",
    }).data["id"]
    ref = _mcp(home, "memory.retain", {
        "node_type": "reflection",
        "body": f"reflection-{suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-co-rf-{suffix}",
    }).data["id"]
    pv = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb, "provenance_reflection_node_id": ref,
        "idempotency_key": f"00000000-0000-4000-8000-co-pv-{suffix}",
    }).data["id"]
    rule = _mcp(home, "memory.retain", {
        "node_type": "playbook_rule", "body": f"rule-{suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-co-rl-{suffix}",
    }).data["id"]
    _mcp(home, "playbook.record_adherence", {
        "decision_id": decision, "playbook_version_id": pv,
        "rule_node_id": rule, "status": "overridden",
        "reason": "edge clear despite rule",
        "idempotency_key": f"00000000-0000-4000-8000-co-ad-{suffix}",
    })
    if with_outcome:
        _mcp(home, "resolution.add", {
            "instrument_id": inst,
            "resolved_at": "2099-01-01T00:00:00Z",
            "outcome_label": "yes", "status": "resolved_final",
            "idempotency_key": f"00000000-0000-4000-8000-co-oc-{suffix}",
        })
    return {"decision_id": decision, "instrument_id": inst}


# -- 1. override_outcomes count + sample_decision_ids -----------


def test_coach_override_outcomes_counts_overridden_rows(home):
    seed_a = _seed_decision_with_override(home, suffix="a")
    seed_b = _seed_decision_with_override(home, suffix="b")
    env = _mcp(home, "report.coach", {})
    assert env.ok
    panel = env.data["override_outcomes"]
    assert panel["overridden_count"] == 2
    ids = panel["sample_decision_ids"]
    assert seed_a["decision_id"] in ids
    assert seed_b["decision_id"] in ids


def test_coach_override_outcomes_zero_on_clean_db(home):
    env = _mcp(home, "report.coach", {})
    assert env.ok
    panel = env.data["override_outcomes"]
    assert panel["overridden_count"] == 0
    assert panel["with_subsequent_outcome"] == 0
    assert panel["sample_decision_ids"] == []


def test_coach_override_outcomes_tracks_subsequent_outcomes(home):
    """Two overridden decisions; one has a subsequent outcome row. The
    panel reports the split."""

    _seed_decision_with_override(home, suffix="oc-with", with_outcome=True)
    _seed_decision_with_override(home, suffix="oc-without", with_outcome=False)
    env = _mcp(home, "report.coach", {})
    panel = env.data["override_outcomes"]
    assert panel["overridden_count"] == 2
    assert panel["with_subsequent_outcome"] == 1
    assert panel["without_subsequent_outcome"] == 1


def test_coach_callout_surfaces_when_overrides_exist(home):
    _seed_decision_with_override(home, suffix="callout1")
    env = _mcp(home, "report.coach", {})
    assert env.ok
    callouts = " ".join(env.data["callouts"])
    assert "playbook override audit" in callouts
    # The callout must not contain any forbidden trade-advice phrase
    # (the gate inside _assert_no_trade_advice would have raised if it
    # did; this is belt-and-braces on the test side too).
    forbidden = {"buy", "sell", "profitable", "long", "short"}
    for phrase in forbidden:
        assert phrase not in callouts.lower().split(), (
            f"forbidden phrase {phrase!r} leaked into coach callout"
        )


# -- 2. additional rule_node_id FK validation ------------------


def test_record_adherence_rejects_observation_node_as_rule(home):
    """rule_node_id must reference a memory_node with
    node_type='playbook_rule'. An observation-type node is rejected."""

    # Build a full adherence prerequisite chain.
    venue = _mcp(home, "venue.add", {
        "name": "V-fk", "kind": "prediction_market",
        "idempotency_key": "00000000-0000-4000-8000-qc-fk-v01",
    }).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": "X",
        "idempotency_key": "00000000-0000-4000-8000-qc-fk-i01",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "t",
        "idempotency_key": "00000000-0000-4000-8000-qc-fk-t01",
    }).data["id"]
    decision = _mcp(home, "decision.add", {
        "type": "actual_enter", "instrument_id": inst,
        "thesis_id": thesis, "side": "yes",
        "quantity": 1, "price": 0.5,
        "idempotency_key": "00000000-0000-4000-8000-qc-fk-d01",
    }).data["id"]
    pb = _mcp(home, "playbook.upsert", {
        "name": "PB-FK", "idempotency_key": "00000000-0000-4000-8000-qc-fk-pb01",
    }).data["id"]
    ref = _mcp(home, "memory.retain", {
        "node_type": "reflection", "body": "r",
        "idempotency_key": "00000000-0000-4000-8000-qc-fk-r01",
    }).data["id"]
    pv = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb, "provenance_reflection_node_id": ref,
        "idempotency_key": "00000000-0000-4000-8000-qc-fk-pv01",
    }).data["id"]
    # Use an OBSERVATION node as the rule — must be rejected.
    observation = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "obs not rule",
        "idempotency_key": "00000000-0000-4000-8000-qc-fk-obs1",
    }).data["id"]
    env = _mcp(home, "playbook.record_adherence", {
        "decision_id": decision, "playbook_version_id": pv,
        "rule_node_id": observation, "status": "considered",
        "idempotency_key": "00000000-0000-4000-8000-qc-fk-ad1",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "rule_node_id"
    assert env.error.details["actual_node_type"] == "observation"


def test_record_adherence_rejects_missing_rule_node(home):
    """rule_node_id pointing at a non-existent memory_node id returns
    NOT_FOUND with entity_kind='memory_node'."""

    venue = _mcp(home, "venue.add", {
        "name": "V-nf", "kind": "prediction_market",
        "idempotency_key": "00000000-0000-4000-8000-qc-nf-v01",
    }).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": "X",
        "idempotency_key": "00000000-0000-4000-8000-qc-nf-i01",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "t",
        "idempotency_key": "00000000-0000-4000-8000-qc-nf-t01",
    }).data["id"]
    decision = _mcp(home, "decision.add", {
        "type": "actual_enter", "instrument_id": inst,
        "thesis_id": thesis, "side": "yes",
        "quantity": 1, "price": 0.5,
        "idempotency_key": "00000000-0000-4000-8000-qc-nf-d01",
    }).data["id"]
    pb = _mcp(home, "playbook.upsert", {
        "name": "PB-NF", "idempotency_key": "00000000-0000-4000-8000-qc-nf-pb01",
    }).data["id"]
    ref = _mcp(home, "memory.retain", {
        "node_type": "reflection", "body": "r",
        "idempotency_key": "00000000-0000-4000-8000-qc-nf-r01",
    }).data["id"]
    pv = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb, "provenance_reflection_node_id": ref,
        "idempotency_key": "00000000-0000-4000-8000-qc-nf-pv01",
    }).data["id"]
    env = _mcp(home, "playbook.record_adherence", {
        "decision_id": decision, "playbook_version_id": pv,
        "rule_node_id": "mem_does_not_exist", "status": "considered",
        "idempotency_key": "00000000-0000-4000-8000-qc-nf-ad1",
    })
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details["entity_kind"] == "memory_node"
