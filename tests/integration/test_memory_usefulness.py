from __future__ import annotations

import sqlite3

from tests.integration.test_recall_receipts import _seed
from trade_trace.core import default_registry, dispatch
from trade_trace.reports.memory_usefulness import report_memory_usefulness
from trade_trace.storage.paths import db_path


def _conn(home):
    return sqlite3.connect(db_path(home))


def test_memory_usefulness_negative_controls_are_caveated_and_read_only(home):
    with _conn(home) as conn:
        _seed(conn)
        conn.execute(
            "INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("e-violate", "review", "rev", "memory_node", "mem-used", "violates", None, "{}", "2026-01-01T00:07:00Z", "actor"),
        )
        before = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        report = report_memory_usefulness(conn, recall_id="recall-1", as_of="2026-01-02T00:00:00Z")
        after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert before == after
    assert report["summary"]["bucket"] == "memory_usefulness"
    assert "DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM" in report["summary"]["caveat_codes"]
    assert "OUTCOME_IMPACT_NOT_INFERRED" in report["summary"]["caveat_codes"]
    assert "causal" in report["summary"]["interpretation"]
    controls = {control["name"]: control for control in report["negative_controls"]}
    assert set(controls) == {
        "recalled_unused",
        "used_contradicted",
        "stale_retrieved",
        "high_confidence_bad_outcome",
        "missing_expected_memory",
        "overfit_harmful",
    }
    assert controls["recalled_unused"]["node_ids"] == ["mem-ignored", "mem-stale"]
    assert controls["stale_retrieved"]["node_ids"] == ["mem-stale"]
    assert controls["overfit_harmful"]["node_ids"] == ["mem-used"]
    assert controls["high_confidence_bad_outcome"]["node_ids"] == ["mem-stale", "mem-used"]
    assert controls["missing_expected_memory"]["measurability"] == "not_measurable"
    assert controls["missing_expected_memory"]["sample_warning"] == "insufficient_evidence"
    diagnostics = {item["node_id"]: item for item in report["memory_diagnostics"]}
    assert diagnostics["mem-used"]["strategy_id"] == "strat"
    assert diagnostics["mem-used"]["agent_id"] == "agent"
    assert diagnostics["mem-used"]["model_id"] == "model"
    assert diagnostics["mem-used"]["run_id"] == "run"
    assert diagnostics["mem-used"]["memory_kind"] == "observation"
    assert diagnostics["mem-used"]["confidence_base"] == 1.0
    assert diagnostics["mem-used"]["age_days_at_recall"] == 0.002083
    assert diagnostics["mem-used"]["outcome_impact"] == "not_measurable_from_current_receipt_evidence"
    group_keys = {group["key"] for group in report["groups"]}
    assert "strategy:strat" in group_keys
    assert "retrieval_strategy:bm25" in group_keys
    assert "retrieval_strategy:graph" in group_keys
    assert "decay:unknown" in group_keys
    assert "outcome_impact:not_measurable_from_current_receipt_evidence" in group_keys
    assert "citation_use:used" in group_keys


def test_memory_usefulness_tool_filters_memory_kind_and_context(home):
    with _conn(home) as conn:
        _seed(conn)
    registry = default_registry()
    result = dispatch(
        "report.memory_usefulness",
        {"home": str(home), "instrument_id": "inst", "strategy_id": "strat", "memory_kind": "observation", "consumer_kind": "decision", "consumer_id": "dec"},
        actor_id="agent:test",
        registry=registry,
    )
    dumped = result.model_dump(mode="json", exclude_none=True)
    assert dumped["ok"] is True, dumped
    data = dumped["data"]
    assert data["summary"]["metrics"]["retrieved_item_count"] == 3
    assert data["summary"]["metrics"]["used_count"] == 1
    assert data["negative_controls"][0]["name"] == "recalled_unused"
