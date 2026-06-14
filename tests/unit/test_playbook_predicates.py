from __future__ import annotations

import json
import sqlite3

import pytest

from trade_trace.playbook_predicates import (
    ALLOWED_PREDICATE_FAMILIES,
    PREDICATE_STATUSES,
    PredicateValidationError,
    evaluate_predicate,
    predicate_from_rule_meta,
    validate_predicate,
)
from trade_trace.storage.database import open_database
from trade_trace.storage.paths import db_path

NOW = "2026-01-01T00:00:00Z"


@pytest.fixture
def conn(initialized_home):
    db = open_database(db_path(initialized_home))
    try:
        _seed(db.connection)
        yield db.connection
    finally:
        db.close()


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO venues(id, name, kind, created_at, actor_id) VALUES ('ven-1', 'Manual', 'manual', ?, 'test')", (NOW,))
    conn.execute(
        "INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id) VALUES ('ins-1', 'ven-1', 'Instrument', 'event_market', ?, 'test')",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO strategies(id, name, slug, created_at, updated_at, actor_id) VALUES ('strat-1', 'Strategy', 'strategy', ?, ?, 'test')",
        (NOW, NOW),
    )
    conn.execute(
        "INSERT INTO theses(id, instrument_id, side, body, created_at, actor_id) VALUES ('ths-1', 'ins-1', 'yes', 'body', ?, 'test')",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO forecasts(id, thesis_id, kind, resolution_rule_text, created_at, actor_id) VALUES ('fc-1', 'ths-1', 'binary', 'Resolves by recorded outcome.', ?, 'test')",
        (NOW,),
    )
    # The playbook_version referenced by dec-1 must exist before the
    # decision is inserted (decisions.playbook_version_id is FK-enforced
    # at insert time by migration 030 /
    # trg_decisions_playbook_version_id_exists).
    conn.execute(
        "INSERT INTO playbooks(id, name, created_at, actor_id) VALUES ('pb-1', 'Playbook', ?, 'test')",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO memory_nodes(id, node_type, body, valid_from, created_at, actor_id) VALUES ('refl-pbv', 'reflection', 'lineage', ?, ?, 'test')",
        (NOW, NOW),
    )
    conn.execute(
        "INSERT INTO playbook_versions(id, playbook_id, version, provenance_reflection_node_id, created_at, actor_id) VALUES ('pbv-1', 'pb-1', 1, 'refl-pbv', ?, 'test')",
        (NOW,),
    )
    conn.execute(
        """
        INSERT INTO decisions(
            id, instrument_id, thesis_id, forecast_id, type, side, quantity, price,
            reason, playbook_version_id, review_by, strategy_id, created_at, actor_id
        ) VALUES (
            'dec-1', 'ins-1', 'ths-1', 'fc-1', 'paper_enter', 'yes', 1.0, 0.42,
            'reason', 'pbv-1', '2026-01-02T00:00:00Z', 'strat-1', ?, 'test'
        )
        """,
        (NOW,),
    )
    conn.execute(
        """
        INSERT INTO decisions(id, instrument_id, type, created_at, actor_id)
        VALUES ('dec-missing', 'ins-1', 'watch', ?, 'test')
        """,
        (NOW,),
    )
    conn.execute(
        "INSERT INTO sources(id, kind, title, created_at, actor_id) VALUES ('src-1', 'note', 'one', ?, 'test')",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO sources(id, kind, title, created_at, actor_id) VALUES ('src-2', 'note', 'two', ?, 'test')",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, edge_type, created_at, actor_id) VALUES ('edge-1', 'source', 'src-1', 'decision', 'dec-1', 'supports', ?, 'test')",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, edge_type, created_at, actor_id) VALUES ('edge-2', 'source', 'src-2', 'decision', 'dec-1', 'contradicts', ?, 'test')",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, edge_type, created_at, actor_id) VALUES ('edge-old-direction', 'decision', 'dec-1', 'source', 'src-2', 'supports', ?, 'test')",
        (NOW,),
    )
    meta = json.dumps({"predicate": {"family": "field_exists", "table": "decisions", "field": "forecast_id"}})
    conn.execute(
        "INSERT INTO memory_nodes(id, node_type, title, body, meta_json, valid_from, created_at, actor_id) VALUES ('rule-1', 'playbook_rule', 'r', 'prose is advisory only', ?, ?, ?, 'test')",
        (meta, NOW, NOW),
    )
    conn.execute(
        "INSERT INTO memory_nodes(id, node_type, title, body, meta_json, valid_from, created_at, actor_id) VALUES ('rule-prose', 'playbook_rule', 'r', 'Require a forecast', '{}', ?, ?, 'test')",
        (NOW, NOW),
    )


def test_closed_constants_are_exact_contract():
    assert set(PREDICATE_STATUSES) == {"pass", "fail", "not_computable", "ambiguous", "not_applicable"}
    assert "field_exists" in ALLOWED_PREDICATE_FAMILIES
    assert "expression" not in ALLOWED_PREDICATE_FAMILIES


def test_field_exists_pass_and_missing_field_not_computable(conn):
    pred = {"family": "field_exists", "table": "decisions", "field": "forecast_id"}
    assert evaluate_predicate(conn, decision_id="dec-1", predicate=pred).status == "pass"
    result = evaluate_predicate(conn, decision_id="dec-missing", predicate=pred)
    assert result.status == "not_computable"


def test_field_equals_fail_and_decision_type_in_pass(conn):
    assert evaluate_predicate(
        conn, decision_id="dec-1", predicate={"family": "field_equals", "table": "decisions", "field": "side", "value": "no"}
    ).status == "fail"
    assert evaluate_predicate(
        conn, decision_id="dec-1", predicate={"family": "decision_type_in", "values": ["paper_enter", "watch"]}
    ).status == "pass"


def test_scope_mismatch_is_not_applicable(conn):
    result = evaluate_predicate(
        conn,
        decision_id="dec-1",
        predicate={"family": "timestamp_present", "field": "review_by", "scope": {"decision_types": ["watch"]}},
    )
    assert result.status == "not_applicable"


def test_link_exists_source_count_and_forecast_resolution(conn):
    source_link = evaluate_predicate(conn, decision_id="dec-1", predicate={"family": "link_exists", "target_kind": "source", "edge_type": "supports"})
    assert source_link.status == "pass"
    assert source_link.record_refs == [{"table": "edges", "id": "edge-1", "target_kind": "source", "target_id": "src-1"}]
    source_count = evaluate_predicate(conn, decision_id="dec-1", predicate={"family": "source_count_at_least", "minimum": 2})
    assert source_count.status == "fail"
    assert source_count.source_refs == [{"source_id": "src-1", "edge_id": "edge-1"}]
    contradicts_count = evaluate_predicate(conn, decision_id="dec-1", predicate={"family": "source_count_at_least", "edge_type": "contradicts", "minimum": 1})
    assert contradicts_count.status == "pass"
    assert contradicts_count.source_refs == [{"source_id": "src-2", "edge_id": "edge-2"}]
    assert evaluate_predicate(conn, decision_id="dec-1", predicate={"family": "forecast_resolution_rule_present"}).status == "pass"
    assert evaluate_predicate(conn, decision_id="dec-missing", predicate={"family": "forecast_resolution_rule_present"}).status == "not_computable"


def test_link_exists_for_non_source_target_keeps_decision_to_target_semantics(conn):
    conn.execute(
        "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, edge_type, created_at, actor_id) VALUES ('edge-forecast', 'decision', 'dec-1', 'forecast', 'fc-1', 'about', ?, 'test')",
        (NOW,),
    )
    result = evaluate_predicate(conn, decision_id="dec-1", predicate={"family": "link_exists", "target_kind": "forecast", "edge_type": "about"})
    assert result.status == "pass"
    assert result.record_refs == [{"table": "edges", "id": "edge-forecast", "target_kind": "forecast", "target_id": "fc-1"}]


def test_evaluate_rule_node_metadata_and_missing_prose_metadata(conn):
    assert evaluate_predicate(conn, decision_id="dec-1", rule_node_id="rule-1").status == "pass"
    result = evaluate_predicate(conn, decision_id="dec-1", rule_node_id="rule-prose")
    assert result.status == "not_computable"
    assert "no predicate" in result.caveats[0]


@pytest.mark.parametrize("meta_json", ["[]", '"string"', "123", "null"])
def test_non_object_json_rule_metadata_is_validation_error(meta_json):
    with pytest.raises(PredicateValidationError, match="meta_json must be an object"):
        predicate_from_rule_meta(meta_json)


@pytest.mark.parametrize("rule_node_id, meta_json", [("rule-list", "[]"), ("rule-null", "null")])
def test_evaluate_rule_node_with_non_object_json_metadata_is_not_computable(conn, rule_node_id, meta_json):
    conn.execute(
        "INSERT INTO memory_nodes(id, node_type, title, body, meta_json, valid_from, created_at, actor_id) VALUES (?, 'playbook_rule', 'r', 'prose is advisory only', ?, ?, ?, 'test')",
        (rule_node_id, meta_json, NOW, NOW),
    )

    result = evaluate_predicate(conn, decision_id="dec-1", rule_node_id=rule_node_id)

    assert result.status == "not_computable"
    assert "meta_json must be an object" in result.caveats[0]


def test_malformed_and_unsupported_metadata_are_rejected_or_ambiguous(conn):
    with pytest.raises(PredicateValidationError):
        predicate_from_rule_meta("{not-json")
    with pytest.raises(PredicateValidationError):
        validate_predicate({"family": "python", "code": "lambda decision: True"})
    result = evaluate_predicate(conn, decision_id="dec-1", predicate={"family": "expression", "expression": "price > 0"})
    assert result.status == "ambiguous"
    assert "unsupported predicate family" in result.caveats[0]
