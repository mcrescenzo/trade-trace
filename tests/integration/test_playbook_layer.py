"""M4 playbook layer per bead trade-trace-fbq.

Covers:
- playbook.create + name-uniqueness VALIDATION_ERROR.
- playbook.show + list_versions: append-only versioned history.
- playbook.propose_version requires a reflection node; rejects non-reflection node_type.
- decision.record_adherence per status (4 statuses) with FK validation.
- report.playbook_adherence aggregates by playbook_version_id.
- Adherence filter by status, strategy_id, time range.
- Playbook semantics advisory: no auto-rejection of decisions.
- Orthogonality: decision can carry strategy_id and/or playbook_version_id independently.
- Provenance chain: reflection_node_id → playbook_versions.provenance_reflection_node_id → decision_playbook_rules.playbook_version_id → adherence statuses.
- Event emission per status: playbook_rule.followed / playbook_rule.overridden; playbook.proposed_version on version creation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(initialized_home):
    """Alias to the shared `initialized_home` fixture in
    `tests/conftest.py` (trade-trace-qs5v / SIMP-008)."""

    return initialized_home


def _mcp(home: Path, tool: str, args: dict | None = None):
    payload = {"home": str(home), **(args or {})}
    return mcp_call(tool, payload, actor_id="agent:default")


def _seed_decision(home: Path, *, idem_suffix: str = "0",
                   strategy_id: str | None = None) -> str:
    venue = _mcp(home, "venue.add", {
        "name": f"V-{idem_suffix}", "kind": "prediction_market",
        "idempotency_key": f"00000000-0000-4000-8000-pb-v-{idem_suffix}",
    }).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market",
        "title": f"X-{idem_suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-pb-i-{idem_suffix}",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes",
        "body": f"thesis-{idem_suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-pb-t-{idem_suffix}",
    }).data["id"]
    args = {
        "type": "actual_enter", "instrument_id": inst,
        "thesis_id": thesis, "side": "yes",
        "quantity": 1, "price": 0.5,
        "idempotency_key": f"00000000-0000-4000-8000-pb-d-{idem_suffix}",
    }
    if strategy_id is not None:
        args["strategy_id"] = strategy_id
    return _mcp(home, "decision.add", args).data["id"]


def _seed_reflection(home: Path, *, idem_suffix: str = "ref0") -> str:
    """Write a standalone reflection node (target=outcome would be safer
    but the orphan invariant is enforced by memory.reflect; for the
    playbook provenance we just need a reflection-type node)."""

    # Use memory.retain to skip the about-edge requirement; this is a
    # fixture shortcut for testing the playbook provenance path
    # without requiring a real outcome chain.
    return _mcp(home, "memory.retain", {
        "node_type": "reflection",
        "body": f"Reflection that motivates version update {idem_suffix}",
        "idempotency_key": f"00000000-0000-4000-8000-pb-r-{idem_suffix}",
    }).data["id"]


def _seed_rule_node(home: Path, *, idem_suffix: str = "rule0") -> str:
    return _mcp(home, "memory.retain", {
        "node_type": "playbook_rule",
        "body": f"Rule: do not enter when spread > 8% (idem {idem_suffix})",
        "idempotency_key": f"00000000-0000-4000-8000-pb-rl-{idem_suffix}",
    }).data["id"]


# -- registration -----------------------------------------------


def test_playbook_tools_registered():
    names = default_registry().names()
    for tool in (
        "playbook.create", "playbook.list", "playbook.show",
        "playbook.list_versions", "playbook.propose_version",
        "playbook.adherence", "decision.record_adherence",
        "report.playbook_adherence",
    ):
        assert tool in names


# -- playbook.create ----------------------------------------------


def test_playbook_create_happy_path(home):
    env = _mcp(home, "playbook.create", {
        "name": "Risk Management",
        "description": "Spread + liquidity guardrails.",
        "idempotency_key": "00000000-0000-4000-8000-pb-create-1",
    })
    assert env.ok, env
    assert env.data["name"] == "Risk Management"
    assert env.meta.event_id is not None


def test_playbook_create_duplicate_name_rejected(home):
    base = {
        "name": "Shared", "idempotency_key": "00000000-0000-4000-8000-pb-dup1",
    }
    first = _mcp(home, "playbook.create", base)
    assert first.ok
    second = _mcp(home, "playbook.create", {
        **base, "idempotency_key": "00000000-0000-4000-8000-pb-dup2",
    })
    assert second.ok is False
    assert second.error.code.value == "VALIDATION_ERROR"
    assert second.error.details["field"] == "name"


# -- playbook.propose_version ------------------------------------


def test_propose_version_requires_reflection_node(home):
    pb = _mcp(home, "playbook.create", {
        "name": "PB-Ref", "idempotency_key": "00000000-0000-4000-8000-pb-ref01",
    }).data["id"]
    ref = _seed_reflection(home, idem_suffix="propose1")
    env = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb,
        "provenance_reflection_node_id": ref,
        "description": "v1",
        "idempotency_key": "00000000-0000-4000-8000-pb-pv-1",
    })
    assert env.ok, env
    assert env.data["version"] == 1
    assert env.data["provenance_reflection_node_id"] == ref


def test_propose_version_rejects_non_reflection_node(home):
    pb = _mcp(home, "playbook.create", {
        "name": "PB-BadRef", "idempotency_key": "00000000-0000-4000-8000-pb-br-1",
    }).data["id"]
    # Use a playbook_rule node instead of a reflection.
    rule = _seed_rule_node(home, idem_suffix="badref")
    env = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb,
        "provenance_reflection_node_id": rule,
        "idempotency_key": "00000000-0000-4000-8000-pb-br-2",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "provenance_reflection_node_id"


def test_propose_version_rejects_rules_json_without_creating_bare_version(home):
    pb = _mcp(home, "playbook.create", {
        "name": "PB-RulesJson", "idempotency_key": "00000000-0000-4000-8000-pb-rj-1",
    }).data["id"]
    ref = _seed_reflection(home, idem_suffix="rulesjson")

    env = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb,
        "provenance_reflection_node_id": ref,
        "rules_json": [{"body": "Always verify liquidity before entry."}],
        "idempotency_key": "00000000-0000-4000-8000-pb-rj-2",
    })

    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "rules_json"
    assert env.error.details["unknown_fields"] == ["rules_json"]

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    db = open_database(db_path(home), create_parent=False)
    try:
        count = db.connection.execute(
            "SELECT COUNT(*) FROM playbook_versions WHERE playbook_id = ?",
            (pb,),
        ).fetchone()[0]
    finally:
        db.close()
    assert count == 0


def test_propose_version_rejects_unsupported_extra_fields(home):
    env = _mcp(home, "playbook.propose_version", {
        "playbook_id": "pbk_unused",
        "provenance_reflection_node_id": "mem_unused",
        "unsupported_extra": True,
        "idempotency_key": "00000000-0000-4000-8000-pb-extra",
    })

    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "unsupported_extra"
    assert env.error.details["unknown_fields"] == ["unsupported_extra"]


def test_propose_version_allows_cli_confirm_transport_controls(home):
    pb = _mcp(home, "playbook.create", {
        "name": "PB-Confirm", "idempotency_key": "00000000-0000-4000-8000-pb-cf-1",
    }).data["id"]
    ref = _seed_reflection(home, idem_suffix="confirm")

    env = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb,
        "provenance_reflection_node_id": ref,
        "confirm": True,
        "_confirm": True,
        "idempotency_key": "00000000-0000-4000-8000-pb-cf-2",
    })

    assert env.ok, env
    assert env.data["playbook_id"] == pb
    assert env.data["provenance_reflection_node_id"] == ref


def test_propose_version_increments_and_links_parent(home):
    pb = _mcp(home, "playbook.create", {
        "name": "PB-Chain", "idempotency_key": "00000000-0000-4000-8000-pb-ch-01",
    }).data["id"]
    ref1 = _seed_reflection(home, idem_suffix="chain1")
    v1 = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb, "provenance_reflection_node_id": ref1,
        "idempotency_key": "00000000-0000-4000-8000-pb-ch-v1",
    }).data
    ref2 = _seed_reflection(home, idem_suffix="chain2")
    v2 = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb, "provenance_reflection_node_id": ref2,
        "idempotency_key": "00000000-0000-4000-8000-pb-ch-v2",
    }).data
    assert v2["version"] == 2
    assert v2["parent_version_id"] == v1["id"]


def test_show_returns_version_history(home):
    pb = _mcp(home, "playbook.create", {
        "name": "PB-Show", "idempotency_key": "00000000-0000-4000-8000-pb-sh-01",
    }).data["id"]
    ref = _seed_reflection(home, idem_suffix="show1")
    _mcp(home, "playbook.propose_version", {
        "playbook_id": pb, "provenance_reflection_node_id": ref,
        "description": "first",
        "idempotency_key": "00000000-0000-4000-8000-pb-sh-v1",
    })
    env = _mcp(home, "playbook.show", {"playbook_id": pb})
    assert env.ok
    assert len(env.data["versions"]) == 1
    assert env.data["versions"][0]["description"] == "first"


def test_show_not_found(home):
    env = _mcp(home, "playbook.show", {"playbook_id": "pbk_nope"})
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"


# -- decision.record_adherence ----------------------------------


@pytest.fixture
def adherence_setup(home):
    """One playbook, one version, one rule, one decision — enough to
    exercise every adherence status."""

    pb = _mcp(home, "playbook.create", {
        "name": "PB-Adh", "idempotency_key": "00000000-0000-4000-8000-pb-adh-1",
    }).data["id"]
    ref = _seed_reflection(home, idem_suffix="adh1")
    pv = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb, "provenance_reflection_node_id": ref,
        "idempotency_key": "00000000-0000-4000-8000-pb-adh-v1",
    }).data["id"]
    rule = _seed_rule_node(home, idem_suffix="adh1")
    decision = _seed_decision(home, idem_suffix="adh1")
    return {
        "playbook_id": pb, "version_id": pv, "rule_id": rule,
        "decision_id": decision, "reflection_id": ref,
    }


@pytest.mark.parametrize(
    "status,expected_event",
    [
        ("considered", "playbook_rule.followed"),
        ("followed", "playbook_rule.followed"),
        ("overridden", "playbook_rule.overridden"),
        ("not_applicable", "playbook_rule.followed"),
    ],
)
def test_record_adherence_per_status_emits_correct_event(
    home, adherence_setup, status, expected_event,
):
    env = _mcp(home, "decision.record_adherence", {
        "decision_id": adherence_setup["decision_id"],
        "playbook_version_id": adherence_setup["version_id"],
        "rule_node_id": adherence_setup["rule_id"],
        "status": status,
        "idempotency_key": f"00000000-0000-4000-8000-pb-adh-{status[:6]}",
    })
    assert env.ok, env
    assert env.data["status"] == status

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT 1 FROM events WHERE event_type = ? AND subject_id = ?",
            (expected_event, env.data["id"]),
        ).fetchone()
    finally:
        db.close()
    assert row is not None, (
        f"event {expected_event!r} not found for status {status!r}"
    )


def test_record_adherence_rejects_non_playbook_rule_node(home, adherence_setup):
    """rule_node_id must reference a memory_node with node_type='playbook_rule'."""

    non_rule = _seed_reflection(home, idem_suffix="bad-rule")
    env = _mcp(home, "decision.record_adherence", {
        "decision_id": adherence_setup["decision_id"],
        "playbook_version_id": adherence_setup["version_id"],
        "rule_node_id": non_rule,
        "status": "considered",
        "idempotency_key": "00000000-0000-4000-8000-pb-adh-bad1",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "rule_node_id"


def test_record_adherence_unknown_status_rejected(home, adherence_setup):
    env = _mcp(home, "decision.record_adherence", {
        "decision_id": adherence_setup["decision_id"],
        "playbook_version_id": adherence_setup["version_id"],
        "rule_node_id": adherence_setup["rule_id"],
        "status": "considered_maybe",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "status"


# -- report.playbook_adherence ----------------------------------


def test_report_playbook_adherence_aggregates_by_version(home, adherence_setup):
    """Per acceptance: adherence is normalized per
    (decision, playbook_version, rule_node) triple — one status per
    triple. To exercise three distinct statuses we use three rules."""

    statuses = ["considered", "followed", "overridden"]
    rule_ids = [
        _seed_rule_node(home, idem_suffix=f"agg-{status}")
        for status in statuses
    ]
    for i, (status, rule) in enumerate(zip(statuses, rule_ids, strict=True)):
        env = _mcp(home, "decision.record_adherence", {
            "decision_id": adherence_setup["decision_id"],
            "playbook_version_id": adherence_setup["version_id"],
            "rule_node_id": rule,
            "status": status,
            "idempotency_key": f"00000000-0000-4000-8000-pb-rep-{i:03d}",
        })
        assert env.ok, env
    env = _mcp(home, "report.playbook_adherence", {})
    assert env.ok
    assert len(env.data["groups"]) == 1
    group = env.data["groups"][0]
    assert group["metrics"]["considered"] == 1
    assert group["metrics"]["followed"] == 1
    assert group["metrics"]["overridden"] == 1
    assert group["metrics"]["total_adherence_rows"] == 3
    assert group["metrics"]["decision_count"] == 1
    assert group["sample_size"] == 1
    assert env.data["summary"]["sample_size"] == 1
    assert env.data["summary"]["metrics"]["total_adherence_rows"] == 3


def test_report_playbook_adherence_filter_by_playbook(home, adherence_setup):
    # Add a second playbook with its own adherence row.
    pb2 = _mcp(home, "playbook.create", {
        "name": "PB-Adh-2", "idempotency_key": "00000000-0000-4000-8000-pb-rep-pb2",
    }).data["id"]
    ref2 = _seed_reflection(home, idem_suffix="rep2")
    pv2 = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb2, "provenance_reflection_node_id": ref2,
        "idempotency_key": "00000000-0000-4000-8000-pb-rep-v2",
    }).data["id"]
    rule2 = _seed_rule_node(home, idem_suffix="rep2")
    _mcp(home, "decision.record_adherence", {
        "decision_id": adherence_setup["decision_id"],
        "playbook_version_id": pv2,
        "rule_node_id": rule2,
        "status": "followed",
        "idempotency_key": "00000000-0000-4000-8000-pb-rep-pa2",
    })
    _mcp(home, "decision.record_adherence", {
        "decision_id": adherence_setup["decision_id"],
        "playbook_version_id": adherence_setup["version_id"],
        "rule_node_id": adherence_setup["rule_id"],
        "status": "followed",
        "idempotency_key": "00000000-0000-4000-8000-pb-rep-pa1",
    })
    # Scope to pb2: only one group expected.
    env = _mcp(home, "report.playbook_adherence", {"playbook_id": pb2})
    assert env.ok
    assert len(env.data["groups"]) == 1
    assert env.data["groups"][0]["key"] == pv2


def test_report_playbook_adherence_filter_by_strategy(home):
    """Decisions carry strategy_id; the report filters by it."""

    strat = _mcp(home, "strategy.create", {
        "name": "PB-Strat", "slug": "pb-strat",
        "idempotency_key": "00000000-0000-4000-8000-pb-strat-1",
    }).data["id"]
    pb = _mcp(home, "playbook.create", {
        "name": "PB-FStrat",
        "idempotency_key": "00000000-0000-4000-8000-pb-fst-pb1",
    }).data["id"]
    ref = _seed_reflection(home, idem_suffix="fstrat")
    pv = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb, "provenance_reflection_node_id": ref,
        "idempotency_key": "00000000-0000-4000-8000-pb-fst-v1",
    }).data["id"]
    rule = _seed_rule_node(home, idem_suffix="fstrat")
    # Decision on the strategy.
    d_strat = _seed_decision(home, idem_suffix="fstr1", strategy_id=strat)
    # Decision off the strategy.
    d_off = _seed_decision(home, idem_suffix="fstr2")
    for d, key in ((d_strat, "fstrat-on"), (d_off, "fstrat-off")):
        _mcp(home, "decision.record_adherence", {
            "decision_id": d, "playbook_version_id": pv,
            "rule_node_id": rule, "status": "followed",
            "idempotency_key": f"00000000-0000-4000-8000-pb-{key}",
        })
    env = _mcp(home, "report.playbook_adherence", {"strategy_id": strat})
    assert env.ok
    group = env.data["groups"][0]
    assert group["metrics"]["total_adherence_rows"] == 1
    assert d_strat in group["record_ids"]["decisions"]
    assert d_off not in group["record_ids"]["decisions"]


def test_playbook_adherence_wrapper_scopes_to_one_playbook(home, adherence_setup):
    _mcp(home, "decision.record_adherence", {
        "decision_id": adherence_setup["decision_id"],
        "playbook_version_id": adherence_setup["version_id"],
        "rule_node_id": adherence_setup["rule_id"],
        "status": "followed",
        "idempotency_key": "00000000-0000-4000-8000-pb-wrap-001",
    })
    env = _mcp(home, "playbook.adherence", {
        "playbook_id": adherence_setup["playbook_id"],
    })
    assert env.ok
    assert env.data["summary"]["metrics"]["playbook_id_filter"] == \
        adherence_setup["playbook_id"]


# -- orthogonal axes: strategy_id and playbook_version_id independent --


def test_decision_with_strategy_and_no_playbook_is_valid(home):
    strat = _mcp(home, "strategy.create", {
        "name": "Orth-S", "slug": "orth-s",
        "idempotency_key": "00000000-0000-4000-8000-pb-orth-s1",
    }).data["id"]
    dec = _seed_decision(home, idem_suffix="orth-s", strategy_id=strat)
    assert dec.startswith("dec_")


def test_decision_with_playbook_and_no_strategy_is_valid(home, adherence_setup):
    # adherence_setup created a decision without strategy_id; the
    # record_adherence call binds it to a playbook version.
    env = _mcp(home, "decision.record_adherence", {
        "decision_id": adherence_setup["decision_id"],
        "playbook_version_id": adherence_setup["version_id"],
        "rule_node_id": adherence_setup["rule_id"],
        "status": "followed",
        "idempotency_key": "00000000-0000-4000-8000-pb-orth-p1",
    })
    assert env.ok


# -- advisory-only semantics --------------------------------------


def test_overridden_adherence_does_not_block_decision(home, adherence_setup):
    """A decision is recorded; then an adherence row marks the rule
    'overridden'. The decision must still read back normally — no
    code path retroactively rejects it."""

    _mcp(home, "decision.record_adherence", {
        "decision_id": adherence_setup["decision_id"],
        "playbook_version_id": adherence_setup["version_id"],
        "rule_node_id": adherence_setup["rule_id"],
        "status": "overridden",
        "reason": "spread caught my eye but the edge was clear",
        "idempotency_key": "00000000-0000-4000-8000-pb-adv-1",
    })
    # Decision still queryable via the events log.
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT 1 FROM decisions WHERE id = ?",
            (adherence_setup["decision_id"],),
        ).fetchone()
    finally:
        db.close()
    assert row is not None


# -- provenance chain: reflection → version → adherence ---------


def test_provenance_chain_traceable(home):
    """A single reflection_node_id traces through
    playbook_versions.provenance_reflection_node_id and the resulting
    adherence row on a later decision."""

    pb = _mcp(home, "playbook.create", {
        "name": "PB-Prov", "idempotency_key": "00000000-0000-4000-8000-pb-prov-1",
    }).data["id"]
    ref = _seed_reflection(home, idem_suffix="prov1")
    pv = _mcp(home, "playbook.propose_version", {
        "playbook_id": pb, "provenance_reflection_node_id": ref,
        "idempotency_key": "00000000-0000-4000-8000-pb-prov-v1",
    }).data["id"]
    rule = _seed_rule_node(home, idem_suffix="prov")
    decision = _seed_decision(home, idem_suffix="prov")
    adh = _mcp(home, "decision.record_adherence", {
        "decision_id": decision, "playbook_version_id": pv,
        "rule_node_id": rule, "status": "followed",
        "idempotency_key": "00000000-0000-4000-8000-pb-prov-a1",
    }).data["id"]
    # Query the chain.
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT pv.provenance_reflection_node_id "
            "FROM decision_playbook_rules dpr "
            "JOIN playbook_versions pv "
            "  ON pv.id = dpr.playbook_version_id "
            "WHERE dpr.id = ?",
            (adh,),
        ).fetchone()
    finally:
        db.close()
    assert row[0] == ref


# -- event-type registry --------------------------------------


def test_playbook_event_types_registered_in_semantic_keys():
    from trade_trace.events.semantic_keys import SEMANTIC_KEYS
    for event_type in (
        "playbook.created", "playbook.proposed_version",
        "playbook_rule.followed", "playbook_rule.overridden",
    ):
        assert event_type in SEMANTIC_KEYS, (
            f"missing event_type {event_type!r} in SEMANTIC_KEYS"
        )
