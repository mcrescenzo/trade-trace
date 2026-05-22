"""Rule-engine creep and auto-policy safety tests (trade-trace-p9m0.6).

The closed-set playbook predicate evaluator and the policy-candidate
quarantine metadata are deliberately narrow. This module pins the hard
boundaries — every test here must fail if the implementation drifts
toward:

- arbitrary predicate execution (code, sql, expressions, prompts, regex,
  cron, lambdas, eval/exec, prose-as-policy);
- LLM-prose rule interpretation (a playbook_rule body that lacks an
  explicit predicate object must never be treated as `pass`/`fail`);
- single-reflection auto-promotion (writing a reflection with
  `policy_candidate.status = promoted_to_playbook` must not create or
  modify any `playbook_versions`/`memory_nodes` of type
  `playbook_rule`).

A separate test pins the architectural boundary docs so the policy
intent is discoverable in `docs/architecture/memory-layer.md`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.playbook_predicates import (
    PredicateValidationError,
    evaluate_predicate,
    predicate_from_rule_meta,
    validate_predicate,
)
from trade_trace.storage.database import open_database
from trade_trace.storage.paths import db_path

NOW = "2026-01-01T00:00:00Z"
ROOT = Path(__file__).resolve().parents[2]


# -- 1. Arbitrary predicate execution must be rejected -------------


@pytest.mark.parametrize(
    "payload",
    [
        {"family": "python", "code": "lambda d: d.get('price', 0) > 0.5"},
        {"family": "expression", "expression": "decision.price > 0"},
        {"family": "sql", "sql": "SELECT 1 FROM decisions WHERE id = ?"},
        {"family": "regex", "pattern": ".*"},
        {"family": "prompt", "prompt": "Decide whether the trade was good."},
        {"family": "shell", "command": "echo hi"},
        {"family": "field_exists", "table": "decisions", "field": "id", "code": "..."},
        {"family": "field_equals", "table": "decisions", "field": "type", "value": "skip", "sql": "..."},
        {"family": "field_equals", "table": "decisions", "field": "type", "value": "skip", "expression": "decision.type == 'skip'"},
        {"family": "field_equals", "table": "decisions", "field": "type", "value": "skip", "prompt": "..."},
    ],
)
def test_arbitrary_executable_predicate_payloads_are_rejected(payload):
    """Every shape that smells like an executable rule engine must raise
    PredicateValidationError at validation time (well before any
    sqlite3.execute). Drift here would silently re-introduce a rule
    engine."""
    with pytest.raises(PredicateValidationError):
        validate_predicate(payload)


@pytest.mark.parametrize("forbidden_key", ["code", "sql", "expression", "prompt"])
def test_forbidden_keys_on_supported_family_are_still_rejected(forbidden_key):
    """Adding `code` (or sql/expression/prompt) to a known-good
    `field_exists` predicate must remain a hard validation error. A future
    "just one little eval" leak should fail here."""
    payload = {"family": "field_exists", "table": "decisions", "field": "type", forbidden_key: "..."}
    with pytest.raises(PredicateValidationError):
        validate_predicate(payload)


def test_predicate_family_set_is_exactly_seven():
    """If the closed family set grows quietly, this test breaks so the
    surface change must be reviewed instead of merged inadvertently."""
    from trade_trace.playbook_predicates import ALLOWED_PREDICATE_FAMILIES

    assert ALLOWED_PREDICATE_FAMILIES == (
        "field_exists",
        "field_equals",
        "decision_type_in",
        "link_exists",
        "source_count_at_least",
        "timestamp_present",
        "forecast_resolution_rule_present",
    )


# -- 2. LLM-prose rule interpretation is NOT allowed -------------------


@pytest.fixture
def conn_with_prose_rule(initialized_home):
    db = open_database(db_path(initialized_home))
    try:
        c = db.connection
        c.execute(
            "INSERT INTO venues(id, name, kind, created_at, actor_id) VALUES ('ven-1', 'PM', 'prediction_market', ?, 'test')",
            (NOW,),
        )
        c.execute(
            "INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id) "
            "VALUES ('ins-1', 'ven-1', 'I', 'prediction_market', ?, 'test')",
            (NOW,),
        )
        c.execute(
            "INSERT INTO decisions(id, instrument_id, type, reason, created_at, actor_id) "
            "VALUES ('dec-1', 'ins-1', 'skip', 'r', ?, 'test')",
            (NOW,),
        )
        prose_meta = json.dumps({"playbook_version_id": "pbv-1", "rule_meta": {
            "trigger_kind": "manual", "applicable_decision_types": ["skip"],
        }})
        c.execute(
            "INSERT INTO memory_nodes(id, node_type, title, body, meta_json, valid_from, created_at, actor_id) "
            "VALUES (?, 'playbook_rule', 'r', ?, ?, ?, ?, 'test')",
            (
                "rule-prose-only",
                "If liquidity is thin near resolution, skip the trade.",
                prose_meta,
                NOW, NOW,
            ),
        )
        c.commit()
        yield c
    finally:
        db.close()


def test_prose_only_rule_never_evaluates_as_pass_or_fail(conn_with_prose_rule):
    """A playbook_rule whose body is pure prose and whose meta_json carries
    no `predicate` object must not be interpreted by any LLM-prose path.
    The evaluator yields `not_computable`, never `pass`/`fail`."""
    result = evaluate_predicate(
        conn_with_prose_rule,
        decision_id="dec-1",
        rule_node_id="rule-prose-only",
    )
    assert result.status == "not_computable", result
    assert result.status not in ("pass", "fail"), result


@pytest.mark.parametrize(
    "prose_only_meta",
    [
        '{"rule_meta": {"trigger_kind": "manual"}}',
        '{"some_other_field": "value"}',
        "{}",
        '{"intent": "block-thin-liquidity"}',
    ],
)
def test_prose_meta_without_predicate_is_validation_error_for_strict_caller(prose_only_meta):
    """The strict validator must reject the metadata. Evaluator-by-rule-id
    converts the same condition to `not_computable`, but the validator
    surface is the one the agent uses to write rule metadata; it should
    refuse to silently interpret prose."""
    with pytest.raises(PredicateValidationError):
        predicate_from_rule_meta(prose_only_meta)


# -- 3. Single-reflection auto-promotion is NOT allowed ---------------


def _seed_decision(home):
    venue = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "title": "creep-test", "asset_class": "prediction_market",
    }).data["id"]
    return _mcp(home, "decision.add", {
        "instrument_id": inst, "type": "skip", "reason": "creep seed",
    }).data["id"]


def _count_playbook_artifacts(home) -> dict[str, int]:
    db = open_database(db_path(home))
    try:
        c = db.connection
        playbooks = c.execute("SELECT COUNT(*) FROM playbooks").fetchone()[0]
        versions = c.execute("SELECT COUNT(*) FROM playbook_versions").fetchone()[0]
        rules = c.execute(
            "SELECT COUNT(*) FROM memory_nodes WHERE node_type = 'playbook_rule'"
        ).fetchone()[0]
        return {"playbooks": playbooks, "versions": versions, "rules": rules}
    finally:
        db.close()


def _reflect_with_status(home, decision_id, status, **extra):
    candidate = {
        "status": status,
        "candidate_statement": "single reflection — do not auto-promote",
        "scope": {"strategy_id": "strat-creep"},
        "evidence": {
            "reflection_ids": [],
            "support_case_count": 1,
            "contradiction_case_count": 0,
            "caveats": ["single_reflection_not_policy"],
        },
    }
    candidate.update(extra)
    return _mcp(home, "memory.reflect", {
        "target_kind": "decision",
        "target_id": decision_id,
        "body": "Single-reflection creep test.",
        "meta_json": {"policy_candidate": candidate},
        "idempotency_key": f"creep-{status}",
    })


def test_single_reflection_with_candidate_status_does_not_create_playbook(home):
    """Writing a reflection with `status='candidate_policy'` must not
    create or mutate any playbook rows, even with rich scope/evidence."""
    decision_id = _seed_decision(home)
    before = _count_playbook_artifacts(home)
    env = _reflect_with_status(home, decision_id, "candidate_policy")
    assert env.ok, env
    assert _count_playbook_artifacts(home) == before


def test_single_reflection_with_promoted_status_does_not_auto_write_playbook(home):
    """Even setting `status='promoted_to_playbook'` (which requires citing
    an externally-written `playbook_version_id`) must not itself create a
    playbook_versions row or a playbook_rule memory_node."""
    decision_id = _seed_decision(home)
    before = _count_playbook_artifacts(home)
    env = _reflect_with_status(
        home, decision_id, "promoted_to_playbook",
        playbook_version_id="pbv-already-written-separately",
    )
    assert env.ok, env
    assert _count_playbook_artifacts(home) == before


def test_promoted_metadata_without_explicit_playbook_version_id_is_rejected(home):
    decision_id = _seed_decision(home)
    env = _reflect_with_status(home, decision_id, "promoted_to_playbook")
    assert env.ok is False, env
    err = env.error.model_dump(mode="json")
    assert err["code"] == "VALIDATION_ERROR"
    assert "playbook_version_id" in err["details"]["field"]


def test_memory_link_between_reflections_does_not_promote_to_playbook(home):
    """Linking two reflections via memory.link must not synthesize a
    playbook rule. This guards against an 'enough reflections agreed →
    auto-rule' creep pattern."""
    decision_id = _seed_decision(home)
    before = _count_playbook_artifacts(home)

    first = _reflect_with_status(home, decision_id, "candidate_policy")
    second = _reflect_with_status(home, decision_id, "needs_more_evidence")
    assert first.ok and second.ok, (first, second)

    link_env = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": second.data["id"],
        "target_kind": "memory_node", "target_id": first.data["id"],
        "edge_type": "supports",
        "idempotency_key": "creep-link-1",
    })
    assert link_env.ok, link_env
    assert _count_playbook_artifacts(home) == before


# -- 4. Hard-boundary docs exist --------------------------------------


def test_memory_layer_doc_states_hard_boundary_against_rule_engine_and_auto_promotion():
    """The architectural doc must explicitly call out the boundaries this
    test module enforces. If the doc loses the language, the tests must
    fail so the boundary stays load-bearing."""
    doc = (ROOT / "docs" / "architecture" / "memory-layer.md").read_text(encoding="utf-8")
    assert "never creates, updates, or deletes playbook versions/rules" in doc, (
        "memory-layer.md must explicitly state that policy_candidate metadata "
        "never mutates playbook rows."
    )
    assert "rule body/prose is never parsed as executable logic" in doc, (
        "memory-layer.md must explicitly forbid prose-as-policy interpretation."
    )
    # Pin the closed family list so the docs and code can't drift apart.
    for family in (
        "field_exists",
        "field_equals",
        "decision_type_in",
        "link_exists",
        "source_count_at_least",
        "timestamp_present",
        "forecast_resolution_rule_present",
    ):
        assert family in doc, f"memory-layer.md must name {family!r} in the closed predicate set"


def test_memory_layer_doc_does_not_introduce_executable_rule_language():
    """A sweep that catches future drift toward 'execute this rule' or
    'evaluate prose' language in the architecture doc."""
    doc = (ROOT / "docs" / "architecture" / "memory-layer.md").read_text(encoding="utf-8").lower()
    forbidden_patterns = [
        r"\beval(uate)?s? prose\b",
        r"\binterpret(s|ed)? prose\b",
        r"\bcode-based rule\b",
        r"\bsql-based rule\b",
        r"\barbitrary expression\b",
        r"\blambda rule\b",
        r"\bauto-promote\b",
    ]
    for pattern in forbidden_patterns:
        assert re.search(pattern, doc) is None, (
            f"memory-layer.md contains a phrase matching {pattern!r}; that "
            "would imply support for an executable rule engine or "
            "automatic single-reflection promotion."
        )
