from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from trade_trace.mcp_server import mcp_call
from trade_trace.storage.paths import db_path

AS_OF = "2026-02-15T00:00:00Z"


def _seed(home: Path):
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok, init
    env = mcp_call("journal.fixture_seed", {"home": str(home), "target": "agent-continuity-loop"})
    assert env.ok, env
    return env.data


def _call(home: Path, tool: str, args: dict):
    env = mcp_call(tool, {"home": str(home), **args})
    assert env.ok, env
    return env.data


def _table_counts(home: Path) -> dict[str, int]:
    with sqlite3.connect(db_path(home)) as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "decisions",
                "forecasts",
                "outcomes",
                "memory_nodes",
                "edges",
                "memory_recall_events",
                "playbook_versions",
                "decision_playbook_rules",
            )
        }


def test_agent_continuity_fixture_seed_contract_and_local_boundary(home: Path) -> None:
    data = _seed(home)
    assert data["target"] == "agent-continuity-loop"
    assert data["counts"]["recall_receipts"] == 1
    assert data["counts"]["policy_quarantine_reflections"] == 1

    with sqlite3.connect(db_path(home)) as conn:
        policy_rows = conn.execute(
            """
            SELECT meta_json FROM memory_nodes
            WHERE json_extract(meta_json, '$.policy_candidate.status') = 'quarantined'
            """
        ).fetchall()
        recall = conn.execute(
            "SELECT recall_id, node_ids_returned FROM memory_recall_events WHERE recall_id = 'rec_agent_continuity_0001'"
        ).fetchone()
        credential_columns = [
            (table, col[1])
            for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            for col in conn.execute(f"PRAGMA table_info({table})")
            if any(term in col[1].lower() for term in ("wallet", "private_key", "signing_key", "api_key"))
        ]
    assert len(policy_rows) == 1
    assert recall is not None
    assert len(json.loads(recall[1])) == 2
    assert credential_columns == []


def test_agent_continuity_fixture_exercises_bootstrap_work_queue_recall_and_health(home: Path) -> None:
    _seed(home)
    before = _table_counts(home)

    bootstrap = _call(home, "agent.bootstrap", {"as_of": AS_OF, "filter": {}})
    work_queue = _call(home, "agent.next_actions", {"as_of": AS_OF, "stale_threshold_days": 14})
    recall = _call(home, "report.recall_receipts", {"recall_id": "rec_agent_continuity_0001"})
    health = _call(home, "report.strategy_health", {"as_of": AS_OF, "min_sample": 20})

    after = _table_counts(home)
    assert after == before

    assert bootstrap["kind"] == "agent.bootstrap"
    assert bootstrap["hard_constraints"]["no_trade_execution"] is True
    assert bootstrap["hard_constraints"]["no_scheduler_or_alert_creation"] is True
    assert bootstrap["obligations"]

    kinds = {item["kind"] for item in work_queue["work_queue"]}
    assert {"review_stale_record", "resolve_due_forecast"} & kinds
    for item in work_queue["work_queue"]:
        assert "fetch_market_data" in item["forbidden_actions"]
        assert "trading_execution" in item["forbidden_actions"]
        assert "schedule_job" in item["forbidden_actions"]

    receipt = recall["recall_receipts"][0]
    statuses = {item["id"]: item for item in receipt["items"]}
    assert receipt["recall_id"] == "rec_agent_continuity_0001"
    assert any(item["status"] == "cited_or_used" for item in statuses.values())
    assert any("CONTRADICTED_DOWNSTREAM" in item["caveat_codes"] for item in statuses.values())

    assert health["groups"]
    assert any("low_n_decisions" in group["caveats"] for group in health["groups"])
    serialized = json.dumps({"bootstrap": bootstrap, "work_queue": work_queue, "health": health}).lower()
    for forbidden in ("buy now", "sell now", "best trade", "profit ranking", "broker truth"):
        assert forbidden not in serialized


def test_agent_continuity_fixture_exercises_forecast_replay_and_quarantine(home: Path) -> None:
    _seed(home)

    diagnostics = _call(home, "report.forecast_diagnostics", {"min_sample": 20})
    assert diagnostics["summary"]["sample_warning"] is not None
    assert "low_n" in diagnostics["summary"]["caveat_codes"]
    assert diagnostics["summary"]["sample_size"] > 0

    with sqlite3.connect(db_path(home)) as conn:
        forecast_id = conn.execute(
            "SELECT forecast_id FROM forecast_scores ORDER BY id LIMIT 1"
        ).fetchone()[0]

    bundle = _call(
        home,
        "replay.case_bundle",
        {
            "as_of": "2026-01-02T00:00:00Z",
            "case_selection": {"source_refs": [{"kind": "forecast", "id": forecast_id}], "max_cases": 1},
            "task": {"mode": "blind_decision", "include_evaluation_labels": True},
        },
    )
    assert bundle["cases"]
    assert bundle["leakage_protections"]["candidate_context_excludes_future_labels"] is True
    assert bundle["evaluation_labels"]["status"] == "included_for_evaluator_only"
    label_text = json.dumps(bundle["evaluation_labels"], sort_keys=True)
    case_text = json.dumps(bundle["cases"], sort_keys=True)
    assert "outcome_id" in label_text
    assert "forecast_score_id" in label_text
    assert "forecast_score_id" not in case_text

    with sqlite3.connect(db_path(home)) as conn:
        quarantined = conn.execute(
            """
            SELECT id, meta_json FROM memory_nodes
            WHERE json_extract(meta_json, '$.policy_candidate.status') = 'quarantined'
            """
        ).fetchall()
        playbook_versions = conn.execute("SELECT COUNT(*) FROM playbook_versions").fetchone()[0]
    assert len(quarantined) == 1
    assert playbook_versions == 1
