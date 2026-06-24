"""Decision-tags-only MVP tests for report.process_analytics."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from tests.integration.test_report_tag_aggregates import _seed_tagged_decision_with_scored_forecast
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage.paths import db_path


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


def _decision(home: Path, *, title: str, tags: list[str], strategy_id: str | None = None) -> str:
    venue = _envelope(home, "venue.add", {"name": f"PM-{title}", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {"venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": title})
    thesis = _envelope(home, "thesis.add", {"instrument_id": inst["data"]["id"], "side": "yes", "body": title})
    args = {"instrument_id": inst["data"]["id"], "thesis_id": thesis["data"]["id"], "type": "paper_enter", "side": "yes", "quantity": 1, "price": 0.5, "tags": tags}
    dec = _envelope(home, "decision.add", args)
    decision_id = dec["data"]["id"]
    if strategy_id is not None:
        _set_decision_strategy_id(home, decision_id, strategy_id)
    return decision_id


def _set_decision_strategy_id(home: Path, decision_id: str, strategy_id: str) -> None:
    _force_update_decision(home, decision_id, "strategy_id", strategy_id)


def _set_decision_created_at(home: Path, decision_id: str, created_at: str) -> None:
    _force_update_decision(home, decision_id, "created_at", created_at)


def _force_update_decision(home: Path, decision_id: str, column: str, value: str) -> None:
    conn = sqlite3.connect(db_path(home))
    try:
        triggers = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'decisions' AND sql LIKE '%UPDATE%'"
        ).fetchall()
        for (name,) in triggers:
            conn.execute(f'DROP TRIGGER "{name}"')
        conn.execute(f"UPDATE decisions SET {column} = ? WHERE id = ?", (value, decision_id))
        conn.commit()
    finally:
        conn.close()


def test_process_analytics_registered():
    assert "report.process_analytics" in default_registry().names()


def test_tag_frequency_decision_only_with_contributing_ids_and_low_n(home):
    d1 = _decision(home, title="one", tags=["late-source", "liquidity-ignored"])
    d2 = _decision(home, title="two", tags=["late-source"])

    env = _envelope(home, "report.process_analytics", {"group_by": ["tag_frequency"], "min_sample": 10})

    assert env["meta"]["tool"] == "report.process_analytics"
    data = env["data"]
    assert data["contract_version"] == "1.0"
    assert data["supported_filter_paths"] == [
        "decision.tags_all", "decision.tags_any", "strategy.strategy_id",
        "time_window.decision_at_gte", "time_window.decision_at_lt",
    ]
    assert "LOW_SAMPLE_SIZE" in data["caveat_codes"]
    assert data["coverage"] == {"eligible_count": 2, "included_count": 2, "missing_count": 0, "coverage_pct": 100.0, "denominator_kind": "decisions"}
    groups = data["groups"]
    assert [g["key"] for g in groups] == ["late-source", "liquidity-ignored"]
    assert groups[0]["metrics"]["tag_count"] == 2
    assert groups[0]["metrics"]["support"] == 1.0
    assert groups[0]["record_ids"]["decisions"] == sorted([d1, d2])


def test_tag_pair_cooccurrence_deterministic_order_and_jaccard(home):
    d1 = _decision(home, title="one", tags=["zeta", "alpha"])
    d2 = _decision(home, title="two", tags=["zeta", "alpha"])
    _decision(home, title="three", tags=["zeta", "beta"])

    env = _envelope(home, "report.process_analytics", {"group_by": ["tag_pair_cooccurrence"], "min_sample": 1})

    groups = env["data"]["groups"]
    assert [g["key"] for g in groups] == ["alpha|zeta", "beta|zeta"]
    first = groups[0]
    assert first["dimensions"] == {"tag_a": "alpha", "tag_b": "zeta"}
    assert first["metrics"]["pair_count"] == 2
    assert first["metrics"]["jaccard"] == pytest.approx(2 / 3)
    assert first["record_ids"]["decisions"] == sorted([d1, d2])


def test_supported_and_unsupported_filters_are_clean(home):
    d1 = _decision(home, title="one", tags=["keep"])
    _decision(home, title="two", tags=["drop"])

    env = _envelope(home, "report.process_analytics", {"filter": {"decision": {"tags_any": ["keep"]}}})
    assert env["data"]["groups"][0]["record_ids"]["decisions"] == [d1]

    bad = mcp_call("report.process_analytics", {"home": str(home), "filter": {"actors": {"actor_id": ["agent:foo"]}}}).model_dump(mode="json")
    assert bad["ok"] is False
    assert bad["error"]["code"] == "VALIDATION_ERROR"
    assert bad["error"]["details"]["unsupported_filter_paths"] == ["actors.actor_id"]


def test_review_and_cost_requests_are_explicitly_unsupported(home):
    _decision(home, title="one", tags=["process"])

    env = _envelope(home, "report.process_analytics", {
        "dimensions": ["tag_frequency", "review_classification"],
        "features": ["coverage", "cost_family"],
        "metrics": ["decision_count", "review_count", "local_pnl_projection"],
        "include_costs": True,
    })

    unsupported = env["data"]["unsupported_features"]
    paths = {u["path"] for u in unsupported}
    assert "dimensions.review_classification" in paths
    assert "features.cost_family" in paths
    assert "metrics.local_pnl_projection" in paths
    assert all(u["applied"] is False for u in unsupported)
    assert env["data"]["groups"][0]["metrics"]["review_count"] == 0


def test_mistakes_strengths_compatibility_remains_brier_ranked_and_filter_rejecting(home):
    _seed_tagged_decision_with_scored_forecast(home, tag="bad-pattern", p_yes=0.1)
    _seed_tagged_decision_with_scored_forecast(home, tag="good-pattern", p_yes=0.9)
    mistakes = _envelope(home, "report.mistakes", {})
    strengths = _envelope(home, "report.strengths", {})
    assert [g["key"] for g in mistakes["data"]["groups"]] == ["bad-pattern", "good-pattern"]
    assert [g["key"] for g in strengths["data"]["groups"]] == ["good-pattern", "bad-pattern"]
    bad = mcp_call("report.mistakes", {"home": str(home), "filter": {"decision": {"tags_any": ["bad-pattern"]}}}).model_dump(mode="json")
    assert bad["ok"] is False
    assert bad["error"]["details"]["unsupported_filter_paths"] == ["decision.tags_any"]


def test_include_costs_keeps_default_metrics_applied_and_enumerates_cost_components(home):
    _decision(home, title="one", tags=["process"])

    env = _envelope(home, "report.process_analytics", {"include_costs": True})
    data = env["data"]

    assert data["applied_scope"]["metrics"] == ["decision_count", "tag_count", "support"]
    unsupported = data["unsupported_features"]
    assert not any(u["path"] in {"metrics.decision_count", "metrics.tag_count", "metrics.support"} for u in unsupported)
    assert {u["unsupported_feature"] for u in unsupported} == {
        "cost_family.fees_slippage",
        "cost_family.local_pnl_projection",
        "cost_family.opportunity_path_diagnostics",
        "cost_family.r_multiple",
    }


def test_include_costs_deduplicates_explicit_cost_metric(home):
    _decision(home, title="one", tags=["process"])

    env = _envelope(home, "report.process_analytics", {"include_costs": True, "metrics": ["decision_count", "local_pnl_projection"]})

    cost_paths = [u["path"] for u in env["data"]["unsupported_features"] if u["unsupported_feature"].startswith("cost_family.")]
    assert sorted(cost_paths) == [
        "metrics.fees_slippage",
        "metrics.local_pnl_projection",
        "metrics.opportunity_path_diagnostics",
        "metrics.r_multiple",
    ]


def test_strategy_time_window_and_tags_all_filters(home):
    keep = _decision(home, title="keep", tags=["alpha", "beta"], strategy_id="strat-a")
    old = _decision(home, title="old", tags=["alpha", "beta"], strategy_id="strat-a")
    _decision(home, title="wrong-strategy", tags=["alpha", "beta"], strategy_id="strat-b")
    _decision(home, title="missing-tag", tags=["alpha"], strategy_id="strat-a")
    _set_decision_created_at(home, keep, "2026-01-02T00:00:00Z")
    _set_decision_created_at(home, old, "2025-12-31T00:00:00Z")

    env = _envelope(home, "report.process_analytics", {"filter": {"strategy": {"strategy_id": "strat-a"}, "time_window": {"decision_at_gte": "2026-01-01T00:00:00Z", "decision_at_lt": "2026-01-03T00:00:00Z"}, "decision": {"tags_all": ["alpha", "beta"]}}, "min_sample": 1})

    assert env["data"]["summary"]["sample_size"] == 1
    assert {g["key"]: g["record_ids"]["decisions"] for g in env["data"]["groups"]} == {"alpha": [keep], "beta": [keep]}


def test_group_drilldown_filter_preserves_caller_scope(home):
    keep = _decision(home, title="keep", tags=["shared"], strategy_id="strat-a")
    _decision(home, title="outside-scope", tags=["shared"], strategy_id="strat-b")

    env = _envelope(home, "report.process_analytics", {
        "filter": {"strategy": {"strategy_id": "strat-a"}},
        "min_sample": 1,
    })
    shared = next(group for group in env["data"]["groups"] if group["key"] == "shared")
    assert shared["filter"] == {
        "strategy": {"strategy_id": "strat-a"},
        "decision": {"tags_all": ["shared"]},
    }

    drilldown = _envelope(home, "report.process_analytics", {
        "filter": shared["filter"],
        "min_sample": 1,
    })

    assert drilldown["data"]["summary"]["sample_size"] == 1
    assert drilldown["data"]["groups"][0]["record_ids"]["decisions"] == [keep]


def test_unknown_top_level_request_field_rejected(home):
    bad = mcp_call("report.process_analytics", {"home": str(home), "unexpected": True}).model_dump(mode="json")

    assert bad["ok"] is False
    assert bad["error"]["code"] == "VALIDATION_ERROR"


def test_group_and_record_id_truncation_uses_flags_and_cursor(home):
    for tag in ["alpha", "beta", "gamma"]:
        _decision(home, title=f"{tag}-1", tags=[tag])
        _decision(home, title=f"{tag}-2", tags=[tag])

    env = _envelope(home, "report.process_analytics", {"max_groups": 2, "max_record_ids_per_group": 1, "min_sample": 1})
    data = env["data"]

    assert data["truncated"] is True
    assert data["next_cursor"] is not None
    assert len(data["groups"]) == 2
    assert all(group["truncated"] is True for group in data["groups"])
    assert all(len(group["record_ids"]["decisions"]) == 1 for group in data["groups"])

    next_page = _envelope(home, "report.process_analytics", {
        "max_groups": 2,
        "max_record_ids_per_group": 1,
        "min_sample": 1,
        "cursor": data["next_cursor"],
    })["data"]

    assert next_page["truncated"] is False
    assert next_page["next_cursor"] is None
    assert [group["key"] for group in next_page["groups"]] == ["gamma"]


def test_unsupported_group_by_falls_back_to_tag_frequency_with_metadata(home):
    _decision(home, title="one", tags=["process"])

    env = _envelope(home, "report.process_analytics", {"group_by": ["review_classification"]})

    assert env["data"]["applied_scope"]["group_by"] == ["tag_frequency"]
    assert env["data"]["groups"][0]["key"] == "process"
    assert any(u["path"] == "group_by.review_classification" for u in env["data"]["unsupported_features"])
