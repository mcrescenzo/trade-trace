"""report.rule_lineage — walk playbook_rule/playbook_version -> reflection ->
trades in one read-only query path (bead trade-trace-a5dy).

These tests pin the lineage CHAIN and the EXPLICIT-GAP behavior, not prose. The
load-bearing properties are:

* anchoring at EITHER a playbook_rule node or a playbook_version id resolves the
  same chain, bridging version<->rule through decision_playbook_rules (rule-node
  provenance edges are not auto-written today);
* each hop carries contributing record_ids;
* missing links are declared in `gaps` / `gap_codes`, never silently dropped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.core import default_registry


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    assert _mcp(h, "journal.init", {}).ok
    return h


def _seed_decision(home: Path, *, suffix: str) -> str:
    venue = _mcp(home, "venue.add", {
        "name": f"V-{suffix}", "kind": "prediction_market",
        "idempotency_key": f"00000000-0000-4000-8000-rl-v-{suffix}",
    }).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market",
        "title": f"X-{suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-rl-i-{suffix}",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": f"thesis-{suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-rl-t-{suffix}",
    }).data["id"]
    return _mcp(home, "decision.add", {
        "type": "actual_enter", "instrument_id": inst, "thesis_id": thesis,
        "side": "yes", "quantity": 1, "price": 0.5,
        "idempotency_key": f"00000000-0000-4000-8000-rl-d-{suffix}",
    }).data["id"]


def _seed_reflection_about_decision(home: Path, decision_id: str, *, suffix: str) -> str:
    """Reflection node with an `about` edge to a decision (downstream link)."""
    return _mcp(home, "memory.reflect", {
        "target_kind": "decision", "target_id": decision_id,
        "body": f"The trade that taught the rule ({suffix}).",
        "idempotency_key": f"00000000-0000-4000-8000-rl-ref-{suffix}",
    }).data["id"]


def _seed_rule_node(home: Path, *, suffix: str) -> str:
    return _mcp(home, "memory.retain", {
        "node_type": "playbook_rule",
        "body": f"Rule: do not enter when spread > 8% ({suffix}).",
        "idempotency_key": f"00000000-0000-4000-8000-rl-rule-{suffix}",
    }).data["id"]


def _seed_version(home: Path, playbook_id: str, reflection_id: str, *, suffix: str) -> str:
    return _mcp(home, "playbook.propose_version", {
        "playbook_id": playbook_id,
        "provenance_reflection_node_id": reflection_id,
        "description": "v1",
        "idempotency_key": f"00000000-0000-4000-8000-rl-pv-{suffix}",
    }).data["id"]


def _seed_full_lineage(home: Path, *, suffix: str) -> dict[str, str]:
    """Seed a complete rule -> version -> reflection -> trade chain."""
    decision = _seed_decision(home, suffix=suffix)
    reflection = _seed_reflection_about_decision(home, decision, suffix=suffix)
    # Consumer-use edge: the decision USED the reflection (consumer->memory).
    _mcp(home, "memory.link", {
        "source_kind": "decision", "source_id": decision,
        "target_kind": "memory_node", "target_id": reflection,
        "edge_type": "supports",
        "idempotency_key": f"00000000-0000-4000-8000-rl-use-{suffix}",
    })
    playbook = _mcp(home, "playbook.upsert", {
        "name": f"PB-{suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-rl-pb-{suffix}",
    }).data["id"]
    version = _seed_version(home, playbook, reflection, suffix=suffix)
    rule = _seed_rule_node(home, suffix=suffix)
    _mcp(home, "decision.record_adherence", {
        "decision_id": decision, "playbook_version_id": version,
        "rule_node_id": rule, "status": "followed",
        "idempotency_key": f"00000000-0000-4000-8000-rl-adh-{suffix}",
    })
    return {
        "decision": decision, "reflection": reflection,
        "playbook": playbook, "version": version, "rule": rule,
    }


def _data(home: Path, args: dict) -> dict:
    env = _mcp(home, "report.rule_lineage", args)
    assert env.ok, env
    return env.model_dump(mode="json", exclude_none=True)["data"]


# -- registration --------------------------------------------------


def test_rule_lineage_registered_and_public():
    reg = default_registry()
    assert "report.rule_lineage" in reg.public_names()
    schema = reg.get("report.rule_lineage").json_schema
    assert set(schema["properties"]) == {"rule_node_id", "playbook_version_id"}


# -- anchoring at a version ----------------------------------------


def test_anchor_at_version_walks_full_chain(home):
    ids = _seed_full_lineage(home, suffix="va")
    data = _data(home, {"playbook_version_id": ids["version"]})

    assert data["summary"]["anchor"]["kind"] == "playbook_version"
    assert data["summary"]["metrics"]["version_count"] == 1
    assert data["summary"]["metrics"]["reflection_count"] == 1
    # No gaps: every hop is populated.
    assert data["summary"]["gap_codes"] == []

    chain = data["chains"][0]
    assert chain["playbook_version_id"] == ids["version"]
    assert chain["reflection"]["node_id"] == ids["reflection"]
    # Downstream `about` edge to the decision (the trade that taught it).
    about_targets = {e["target_id"] for e in chain["downstream_edges"]["about"]}
    assert ids["decision"] in about_targets
    # Consumer-use edge: the decision used the reflection.
    use = chain["consumer_use_edges"]
    assert any(
        e["source_kind"] == "decision" and e["source_id"] == ids["decision"]
        for e in use
    )
    # Adherence row present for this version + rule.
    assert [r["rule_node_id"] for r in chain["adherence_rows"]] == [ids["rule"]]
    assert chain["adherence_rows"][0]["status"] == "followed"
    # Record ids at each hop.
    rec = chain["record_ids"]
    assert rec["playbook_versions"] == [ids["version"]]
    assert rec["reflection_nodes"] == [ids["reflection"]]
    assert ids["decision"] in rec["decisions"]
    assert rec["rule_nodes"] == [ids["rule"]]
    assert len(rec["adherence"]) == 1


# -- anchoring at a rule node --------------------------------------


def test_anchor_at_rule_bridges_to_version(home):
    ids = _seed_full_lineage(home, suffix="ra")
    data = _data(home, {"rule_node_id": ids["rule"]})

    assert data["summary"]["anchor"]["kind"] == "playbook_rule"
    assert data["summary"]["anchor"]["rule_node_id"] == ids["rule"]
    # Bridged to the version via decision_playbook_rules.
    assert data["summary"]["anchor"]["version_ids"] == [ids["version"]]
    assert data["summary"]["metrics"]["version_count"] == 1

    chain = data["chains"][0]
    assert chain["playbook_version_id"] == ids["version"]
    assert chain["reflection"]["node_id"] == ids["reflection"]
    # When anchored at a rule, adherence rows are filtered to that rule.
    assert [r["rule_node_id"] for r in chain["adherence_rows"]] == [ids["rule"]]


# -- explicit gaps -------------------------------------------------


def test_rule_with_no_adherence_declares_bridge_gap(home):
    # A playbook_rule node that was never recorded on any version.
    rule = _seed_rule_node(home, suffix="orphan")
    data = _data(home, {"rule_node_id": rule})

    assert data["chains"] == []
    assert data["summary"]["metrics"]["version_count"] == 0
    assert "rule_not_linked_to_any_version" in data["summary"]["gap_codes"]
    assert "RULE_LINEAGE_HAS_GAPS" in data["summary"]["caveat_codes"]
    assert "NO_RULE_LINEAGE_FOUND" in data["summary"]["caveat_codes"]
    # The bridge gap is also surfaced as an anchor-level gap.
    assert any(
        g["code"] == "rule_not_linked_to_any_version"
        for g in data["anchor_gaps"]
    )


def test_version_with_unused_reflection_declares_downstream_gaps(home):
    # Version whose provenance reflection has no downstream/consumer edges and
    # no adherence rows: three explicit gaps, no silent empties.
    reflection = _mcp(home, "memory.retain", {
        "node_type": "reflection", "body": "Reflection with no links.",
        "idempotency_key": "00000000-0000-4000-8000-rl-lonely-ref",
    }).data["id"]
    playbook = _mcp(home, "playbook.upsert", {
        "name": "PB-lonely",
        "idempotency_key": "00000000-0000-4000-8000-rl-lonely-pb",
    }).data["id"]
    version = _seed_version(home, playbook, reflection, suffix="lonely")

    data = _data(home, {"playbook_version_id": version})
    chain = data["chains"][0]
    gap_codes = {g["code"] for g in chain["gaps"]}
    assert "reflection_has_no_downstream_edges" in gap_codes
    assert "reflection_not_used_downstream" in gap_codes
    assert "no_adherence_rows" in gap_codes
    # The reflection itself still resolved (no provenance gap).
    assert "provenance_reflection_missing" not in gap_codes
    assert chain["reflection"]["node_id"] == reflection


# -- input validation ----------------------------------------------


def test_requires_exactly_one_anchor(home):
    both = _mcp(home, "report.rule_lineage", {
        "rule_node_id": "mem-x", "playbook_version_id": "pv-x",
    })
    assert both.ok is False
    assert both.error.code.value == "VALIDATION_ERROR"

    neither = _mcp(home, "report.rule_lineage", {})
    assert neither.ok is False
    assert neither.error.code.value == "VALIDATION_ERROR"


def test_unknown_anchor_is_not_found(home):
    missing_version = _mcp(home, "report.rule_lineage", {
        "playbook_version_id": "pv_does_not_exist",
    })
    assert missing_version.ok is False
    assert missing_version.error.code.value == "NOT_FOUND"

    missing_rule = _mcp(home, "report.rule_lineage", {
        "rule_node_id": "mem_does_not_exist",
    })
    assert missing_rule.ok is False
    assert missing_rule.error.code.value == "NOT_FOUND"


def test_non_rule_node_rejected(home):
    # An observation node anchored as a rule must be rejected (not NOT_FOUND).
    obs = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "not a rule",
        "idempotency_key": "00000000-0000-4000-8000-rl-obs",
    }).data["id"]
    env = _mcp(home, "report.rule_lineage", {"rule_node_id": obs})
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
