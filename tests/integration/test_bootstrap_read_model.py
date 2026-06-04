from __future__ import annotations

import json
import sqlite3

import pytest

from tests.integration._bootstrap_helpers import (
    conn_for as _conn,
)
from tests.integration._bootstrap_helpers import (
    counts as _counts,
)
from tests.integration._bootstrap_helpers import (
    seed_base as _seed_base,
)
from trade_trace.reports.bootstrap import compose_bootstrap_packet


def _seed_fresh_session_recovery(conn: sqlite3.Connection) -> None:
    _seed_base(conn)
    conn.execute("INSERT INTO sources(id, kind, title, created_at, actor_id) VALUES (?,?,?,?,?)", ("src-1", "note", "fixture source", "2026-01-01T00:00:00Z", "test"))
    for kind, target_id in (("decision", "d-watch"), ("forecast", "fc"), ("thesis", "th")):
        conn.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, edge_type, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"edge-src-{kind}-{target_id}", "source", "src-1", kind, target_id, "supports", "{}", "2026-01-01T00:04:00Z", "test"),
        )
    conn.execute(
        "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, edge_type, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?,?)",
        ("edge-strat-fc", "strategy", "strat-a", "forecast", "fc", "about", "{}", "2026-01-01T00:04:00Z", "test"),
    )
    conn.execute(
        "INSERT INTO instruments (id, venue_id, title, asset_class, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)",
        ("inst-review", "ven", "Review instrument", "equity", "{}", "2026-01-01T00:00:00Z", "test"),
    )
    conn.execute(
        "INSERT INTO theses (id, instrument_id, side, body, strategy_id, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?)",
        ("th-review", "inst-review", "long", "review body", "strat-a", "{}", "2026-01-01T00:01:00Z", "test"),
    )
    conn.execute(
        "INSERT INTO decisions (id, instrument_id, thesis_id, type, reason, strategy_id, run_id, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("d-stale", "inst", "th", "watch", "old watch", "strat-a", "run-a", "{}", "2025-01-01T00:00:00Z", "test"),
    )
    conn.execute(
        "INSERT INTO decisions (id, instrument_id, thesis_id, type, reason, strategy_id, run_id, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("d-review", "inst-review", "th-review", "review", "post outcome review", "strat-a", "run-a", "{}", "2026-01-02T00:00:00Z", "test"),
    )
    conn.execute(
        "INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, status, source, confidence, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("out-review", "inst-review", "2026-01-03T00:00:00Z", "resolved", "resolved_final", "caller", 1.0, "{}", "2026-01-03T00:00:00Z", "test"),
    )
    conn.execute(
        "INSERT INTO memory_nodes(id, node_type, title, body, confidence_base, decay_rate_per_day, importance, valid_from, created_at, actor_id, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("mem-prov", "reflection", "playbook provenance", "prov", 0.7, 0.001, 5, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "test", "run-a"),
    )
    conn.execute("INSERT INTO playbooks(id, name, status, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?)", ("pb-1", "Fixture playbook", "active", "{}", "2026-01-01T00:00:00Z", "test"))
    conn.execute(
        "INSERT INTO playbook_versions(id, playbook_id, version, provenance_reflection_node_id, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)",
        ("pbv-1", "pb-1", 1, "mem-prov", "{}", "2026-01-01T00:00:00Z", "test"),
    )
    conn.execute(
        "INSERT INTO decisions (id, instrument_id, thesis_id, type, reason, playbook_version_id, strategy_id, run_id, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("d-playbook", "inst", "th", "hold", "playbook-scoped hold", "pbv-1", "strat-a", "run-a", "{}", "2026-01-04T00:00:00Z", "test"),
    )
    for row in (
        ("mem-useful", "observation", "Useful context", "Useful context body", 0.9, None, 8, "2025-12-01T00:00:00Z", None, None, "2026-01-02T00:00:00Z"),
        ("mem-stale", "playbook_rule", "Stale context", "Stale context body", 0.6, 0.01, 4, "2025-01-01T00:00:00Z", "2025-12-31T00:00:00Z", "mem-useful", "2025-01-01T00:00:00Z"),
    ):
        conn.execute(
            "INSERT INTO memory_nodes(id, node_type, title, body, confidence_base, decay_rate_per_day, importance, valid_from, valid_to, invalidated_by, created_at, actor_id, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (*row, "test", "run-a"),
        )
    conn.execute(
        "INSERT INTO memory_recall_events(recall_id, query, strategies_used, node_ids_returned, context_json, limit_k, as_of, created_at, actor_id, agent_id, model_id, environment, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("recall-bootstrap", "bootstrap recovery", json.dumps(["bm25"]), json.dumps(["mem-useful", "mem-stale"]), json.dumps({"strategy_id": "strat-a", "instrument_id": "inst"}), 2, "2026-01-10T00:00:00Z", "2026-01-10T00:00:00Z", "test", "agent-a", "model-a", "test", "run-a"),
    )
    for edge_id, source_kind, source_id, target_kind, target_id, edge_type in (
        ("edge-useful-used", "decision", "d-watch", "memory_node", "mem-useful", "supports"),
        ("edge-stale-contradicted", "decision", "d-watch", "memory_node", "mem-stale", "contradicts"),
        ("edge-mem-useful-source", "memory_node", "mem-useful", "source", "src-1", "derived_from"),
        ("edge-mem-stale-source", "memory_node", "mem-stale", "source", "src-1", "derived_from"),
    ):
        conn.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, edge_type, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (edge_id, source_kind, source_id, target_kind, target_id, edge_type, "{}", "2026-01-10T00:00:00Z", "test"),
        )


def test_bootstrap_packet_is_deterministic_source_backed_and_read_only(home):
    with _conn(home) as conn:
        _seed_base(conn)
        before = _counts(conn)
        args = {
            "as_of": "2026-01-20T00:00:00Z",
            "raw_filter": {"run_id": "run-a", "strategy_ids": ["strat-a"]},
            "budgets": {"default_max_items_per_section": 5, "default_max_chars_per_section": 8000},
        }
        packet = compose_bootstrap_packet(conn, **args)
        again = compose_bootstrap_packet(conn, **args)
        after = _counts(conn)

    assert packet == again
    assert after == before
    assert packet["kind"] == "agent.bootstrap"
    assert packet["contract_version"] == "bootstrap.v0"
    assert packet["metadata"]["side_effects"] == []
    assert packet["metadata"]["packet_id"].startswith("bootstrap:")
    assert packet["obligations"]
    assert all(item["source_refs"] for item in packet["obligations"])
    assert {"kind": "report", "id": "report.work_queue"} in packet["obligations"][0]["evidence_refs"]
    assert packet["hard_constraints"]["no_market_data_fetch"] is True
    assert packet["hard_constraints"]["no_trade_execution"] is True
    serialized = json.dumps(packet).lower()
    for forbidden in ("buy now", "sell now", "best trade", "profit ranking", "alpha ranking", "fetch_market_data", "place_order"):
        assert forbidden not in serialized
    for required in ("no_market_data_fetch", "no_financial_advice", "caller_supplied_data_only"):
        assert required in serialized


def test_bootstrap_fresh_session_recovers_prior_process_memory_and_strategy_context(home):
    with _conn(home) as conn:
        _seed_fresh_session_recovery(conn)
        before = _counts(conn)
        packet = compose_bootstrap_packet(
            conn,
            as_of="2026-01-20T00:00:00Z",
            raw_filter={"strategy_ids": ["strat-a"]},
            budgets={"default_max_items_per_section": 20, "default_max_chars_per_section": 12000},
        )
        after = _counts(conn)

    assert after == before
    assert packet["metadata"]["side_effects"] == []
    assert packet["hard_constraints"] == {
        "no_financial_advice": True,
        "no_market_data_fetch": True,
        "no_broker_or_exchange_fetch": True,
        "no_trade_execution": True,
        "no_order_preparation": True,
        "no_scheduler_or_alert_creation": True,
        "caller_supplied_data_only": True,
        "local_read_synthesis_only": True,
    }

    obligations_by_kind = {item["kind"]: item for item in packet["obligations"]}
    assert {"resolve_due_forecast", "review_due_watch", "review_stale_record", "record_reflection", "record_playbook_adherence"} <= set(obligations_by_kind)
    for kind, expected_ref in {
        "resolve_due_forecast": {"kind": "forecast", "id": "fc"},
        "review_due_watch": {"kind": "decision", "id": "d-watch"},
        "review_stale_record": {"kind": "decision", "id": "d-stale"},
        "record_reflection": {"kind": "decision", "id": "d-review"},
        "record_playbook_adherence": {"kind": "decision", "id": "d-playbook"},
    }.items():
        item = obligations_by_kind[kind]
        assert expected_ref in item["source_refs"]
        assert {"kind": "report", "id": "report.work_queue"} in item["evidence_refs"]
        assert {"no_fetch_performed", "not_trade_advice"} <= set(item["caveat_codes"])

    active = packet["active_ideas"]
    assert any({"kind": "forecast", "id": "fc"} in item["source_refs"] for item in active["unresolved_forecasts"])
    assert any({"kind": "decision", "id": "d-stale"} in item["source_refs"] for item in active["non_actions_and_reviews"])
    assert any({"kind": "decision", "id": "d-review"} in item["source_refs"] for item in active["recently_resolved_needing_learning"])

    memory = packet["memory_context"]
    assert memory["included"] is True
    nodes = {node["node_id"]: node for node in memory["memory_nodes"]}
    assert {"mem-useful", "mem-stale"} <= set(nodes)
    assert nodes["mem-useful"]["source_refs"] == [{"target_kind": "source", "target_id": "src-1", "edge_type": "derived_from"}]
    assert "STALE_OR_INVALIDATED_MEMORY" in nodes["mem-stale"]["caveat_codes"]
    assert "STALE_AS_OF_RECEIPT" in nodes["mem-stale"]["caveat_codes"]
    assert "memory_body_omitted" in memory["memory_caveats"]
    diagnostics = {item["node_id"]: item for item in memory["memory_diagnostics"]}
    assert diagnostics["mem-useful"]["used"] is True
    assert diagnostics["mem-stale"]["stale"] is True

    strategy = packet["strategy_context"]
    strat = strategy["active_strategies"][0]
    assert strat["strategy_id"] == "strat-a"
    assert strat["source_refs"] == [{"kind": "strategy", "id": "strat-a"}]
    assert {"low_n_decisions", "policy_candidates_unsupported_local_surface"} <= set(strat["caveat_codes"])
    assert "source_quality_checks_limited_to_thesis_source_refs" in strategy["strategy_caveats"]

    serialized = json.dumps(packet).lower()
    for forbidden in ("buy now", "sell now", "best trade", "profit ranking", "alpha ranking", "fetch_market_data", "place_order", "execute_order"):
        assert forbidden not in serialized
    for caveat in ("no_financial_advice", "no_market_data_fetch", "no_trade_execution", "no_order_preparation", "no_scheduler_or_alert_creation"):
        assert caveat in serialized


def test_bootstrap_include_memory_body_returns_actual_body_not_title(home):
    """trade-trace-s7x9: include_memory_body used to return the node title
    because the recall-receipts query never selected the body column.
    The fixture's mem-useful has title='Useful context' and body='Useful
    context body' — distinct strings so a regression catches the swap."""
    with _conn(home) as conn:
        _seed_fresh_session_recovery(conn)
        packet = compose_bootstrap_packet(
            conn,
            as_of="2026-01-20T00:00:00Z",
            raw_filter={"strategy_ids": ["strat-a"]},
            budgets={
                "default_max_items_per_section": 20,
                "default_max_chars_per_section": 12000,
                "include_memory_body": True,
            },
        )

    memory = packet["memory_context"]
    assert "memory_body_omitted" not in memory["memory_caveats"], memory["memory_caveats"]
    nodes = {node["node_id"]: node for node in memory["memory_nodes"]}
    useful = nodes["mem-useful"]
    assert useful["summary"] == "Useful context"
    assert useful["body"] == "Useful context body", useful
    assert useful["body"] != useful["summary"], useful


def test_bootstrap_budgets_truncation_and_not_requested_sections_are_explicit(home):
    with _conn(home) as conn:
        _seed_base(conn)
        packet = compose_bootstrap_packet(
            conn,
            as_of="2026-01-20T00:00:00Z",
            raw_filter={"strategy_ids": ["strat-a"]},
            sections=["current_scope", "obligations", "caveats"],
            budgets={"sections": {"obligations": {"max_items": 0, "max_chars": 8000}}},
        )
    assert packet["obligations"] == []
    assert packet["truncation"]["sections"]["obligations"]["is_partial"] is True
    assert packet["omitted_counts"]["obligations"]["max_items"] >= 1
    assert packet["omitted_counts"]["memory_context"]["section_not_requested"] == 1
    assert packet["memory_context"]["included"] is False


def test_apply_budget_section_emptied_by_char_cap_reports_max_chars_not_stale_max_items():
    """axloop AX-038: a multi-bucket section (e.g. active_ideas) is first
    trimmed per-bucket to max_items, then — if the trimmed result still
    exceeds max_chars — the whole section is discarded by the char guard.
    The truncation reason must then be 'max_chars' (the cause of the empty
    section), NOT a stale 'max_items': returned_count:0 under a >0 max_items
    budget is self-contradictory and tells a consumer 'some rows omitted'
    when in fact every row was dropped by the char cap."""
    from trade_trace.reports.bootstrap import _apply_budget

    section = {
        "current_exposure": [],
        "watches": [],
        # 15 > max_items(10) so per-bucket trimming fires (reason starts 'max_items'),
        # and the trimmed-to-10 blob is far larger than max_chars(100) so the
        # char guard then empties the whole section.
        "unresolved_forecasts": [{"id": f"fc{i}", "blob": "x" * 40} for i in range(15)],
        "non_actions_and_reviews": [],
        "recently_resolved_needing_learning": [],
    }
    out, trunc, omitted = _apply_budget("active_ideas", section, {"max_items": 10, "max_chars": 100})

    assert out == {}  # _empty_section('active_ideas')
    assert trunc["returned_count"] == 0
    assert trunc["reason"] == "max_chars"  # the fix: not the stale 'max_items'
    assert trunc["is_partial"] is True
    assert omitted["max_chars"] == 1
    assert omitted["max_items"] >= 1  # per-bucket trimming is still recorded


def test_bootstrap_rejects_unsupported_filters_and_sections(home):
    with _conn(home) as conn:
        _seed_base(conn)
        with pytest.raises(ValueError, match="unsupported bootstrap filter"):
            compose_bootstrap_packet(conn, as_of="2026-01-20T00:00:00Z", raw_filter={"venue_id": "ven"})
        with pytest.raises(ValueError, match="unsupported bootstrap section"):
            compose_bootstrap_packet(conn, as_of="2026-01-20T00:00:00Z", sections=["network_fetches"])


def test_bootstrap_rejects_multi_strategy_filter_instead_of_silently_narrowing(home):
    with _conn(home) as conn:
        _seed_base(conn)
        with pytest.raises(ValueError, match="strategy_ids supports exactly one"):
            compose_bootstrap_packet(
                conn,
                as_of="2026-01-20T00:00:00Z",
                raw_filter={"strategy_ids": ["strat-a", "strat-b"]},
            )


def test_bootstrap_max_chars_total_is_hard_bound_with_global_pruning(home):
    with _conn(home) as conn:
        _seed_base(conn)
        packet = compose_bootstrap_packet(
            conn,
            as_of="2026-01-20T00:00:00Z",
            raw_filter={"strategy_ids": ["strat-a"]},
            budgets={"max_chars_total": 6000},
        )

    assert len(json.dumps(packet, sort_keys=True, separators=(",", ":"))) <= 6000
    assert packet["truncation"]["is_partial"] is True
    assert packet["omitted_counts"]["packet"]["max_total_chars"] == 1
    assert "max_total_chars" in packet["caveats"]["truncation_caveats"]


def test_bootstrap_rejects_impossible_max_chars_total(home):
    with _conn(home) as conn:
        _seed_base(conn)
        with pytest.raises(ValueError, match="cannot fit within max_chars_total"):
            compose_bootstrap_packet(conn, as_of="2026-01-20T00:00:00Z", budgets={"max_chars_total": 100})


@pytest.mark.parametrize(
    "raw_filter",
    [
        {"tags": ["urgent"]},
        {"symbols": ["ABC"]},
        {"actor_id": "actor-a"},
        {"agent_id": "agent-a"},
        {"model_id": "model-a"},
        {"environment": "test"},
        {"since": "2026-01-01T00:00:00Z"},
        {"until": "2026-02-01T00:00:00Z"},
    ],
)
def test_bootstrap_rejects_filters_not_supported_by_all_composed_reports(home, raw_filter):
    with _conn(home) as conn:
        _seed_base(conn)
        with pytest.raises(ValueError, match="unsupported bootstrap filter.*composed read model"):
            compose_bootstrap_packet(conn, as_of="2026-01-20T00:00:00Z", raw_filter=raw_filter)


@pytest.mark.parametrize(
    ("budgets", "match"),
    [
        ({"default_max_items_per_section": -1}, "non-negative"),
        ({"default_max_chars_per_section": 0}, "positive"),
        ({"max_chars_total": -1}, "positive"),
        ({"sections": {"obligations": {"max_items": -1}}}, "non-negative"),
        ({"sections": {"obligations": {"max_chars": 0}}}, "positive"),
        ({"sections": {"unknown": {"max_items": 1}}}, "unsupported bootstrap budget section"),
    ],
)
def test_bootstrap_rejects_invalid_budgets(home, budgets, match):
    with _conn(home) as conn:
        _seed_base(conn)
        with pytest.raises(ValueError, match=match):
            compose_bootstrap_packet(conn, as_of="2026-01-20T00:00:00Z", budgets=budgets)
