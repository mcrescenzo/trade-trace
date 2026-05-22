from __future__ import annotations

import json
import sqlite3

import pytest

from trade_trace.reports.bootstrap import compose_bootstrap_packet
from trade_trace.storage.paths import db_path


def _conn(home):
    return sqlite3.connect(db_path(home))


def _seed_base(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO venues VALUES (?,?,?,?,?,?)", ("ven", "Venue", "manual", "{}", "2026-01-01T00:00:00Z", "test"))
    conn.execute(
        "INSERT INTO instruments (id, venue_id, title, asset_class, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)",
        ("inst", "ven", "Instrument", "equity", "{}", "2026-01-01T00:00:00Z", "test"),
    )
    conn.execute("INSERT INTO strategies(id, name, slug, status, created_at, updated_at, actor_id) VALUES (?,?,?,?,?,?,?)", ("strat-a", "Strategy A", "strat-a", "active", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "test"))
    conn.execute(
        "INSERT INTO theses (id, instrument_id, side, body, strategy_id, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?)",
        ("th", "inst", "long", "body", "strat-a", "{}", "2026-01-01T00:01:00Z", "test"),
    )
    conn.execute(
        """
        INSERT INTO forecasts (id, thesis_id, kind, resolution_at, yes_label, resolution_rule_text,
                               scoring_support, scoring_state, metadata_json, created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        ("fc", "th", "binary", "2026-01-10T00:00:00Z", "yes", "caller supplies outcome", "supported", "pending", "{}", "2026-01-01T00:02:00Z", "test"),
    )
    conn.execute("INSERT INTO forecast_outcomes(id, forecast_id, outcome_label, probability) VALUES (?,?,?,?)", ("fo-yes", "fc", "yes", 0.6))
    conn.execute("INSERT INTO forecast_outcomes(id, forecast_id, outcome_label, probability) VALUES (?,?,?,?)", ("fo-no", "fc", "no", 0.4))
    conn.execute(
        """
        INSERT INTO decisions (id, instrument_id, thesis_id, forecast_id, type, reason,
                               review_by, strategy_id, run_id, metadata_json, created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        ("d-watch", "inst", "th", "fc", "watch", "because", "2026-01-05T00:00:00Z", "strat-a", "run-a", json.dumps({}), "2026-01-01T00:03:00Z", "test"),
    )


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in ("decisions", "forecasts", "edges", "memory_nodes", "memory_recall_events")}


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
