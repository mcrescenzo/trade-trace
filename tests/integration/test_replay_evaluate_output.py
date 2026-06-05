from __future__ import annotations

import socket
import sqlite3
import urllib.request

from tests._mcp_helpers import envelope_default as _envelope
from tests.integration.test_replay_case_bundle import _bundle, _init_home, _seed_case
from trade_trace.core import default_registry
from trade_trace.storage.paths import db_path


def _labeled_bundle(home):
    return _bundle(
        home,
        case_selection={"source_refs": [{"kind": "decision", "id": _seed_case(home)["decision"]}], "max_cases": 1},
        task={"mode": "blind_decision", "include_evaluation_labels": True},
    )["data"]


def _metadata():
    return {
        "agent_id": "agent-a",
        "model_id": "model-a",
        "prompt_id_or_hash": "prompt-a",
        "environment": "test",
        "candidate_run_id": "run-a",
        "tool_policy_id": "local-read-only",
        "recall_policy_id": "recall-a",
        "playbook_version_id": "pb-v1",
    }


def _valid_candidate(bundle):
    case = bundle["cases"][0]
    ctx = case["point_in_time_context"]
    source_id = ctx["sources"][0]["source_id"]
    forecast_id = ctx["forecasts"][0]["forecast_id"]
    return {
        "metadata": _metadata(),
        "case_id": case["case_id"],
        "decision": {"type": "skip", "rationale": "process-only replay output"},
        "forecast": {"forecast_id": forecast_id, "outcomes": [{"outcome_label": "yes", "probability": 0.62}]},
        "citations": [{"kind": "source", "id": source_id}],
        "playbook_adherence": {"source_refs": case["source_refs"], "caveat_codes": ["mutable_strategy_reconstruction"]},
        "caveats": ["mutable_strategy_reconstruction"],
    }


def _evaluate(home, bundle, candidate):
    return _envelope(home, "replay.evaluate_output", {"case_bundle": bundle, "candidate_output": candidate})


def _criterion(data, name):
    return next(item for item in data["criteria_results"] if item["criterion"] == name)


def test_registered_schema_and_pass_path(tmp_path):
    home = _init_home(tmp_path)
    bundle = _labeled_bundle(home)
    reg = default_registry()
    tool = reg.get("replay.evaluate_output")
    assert "replay.evaluate_output" in reg.names()
    assert tool.is_write is False
    assert tool.json_schema["required"] == ["case_bundle", "candidate_output"]
    text = (tool.description + " " + tool.json_schema["description"]).lower()
    assert "read-only" in text
    assert "no fetch" in text
    assert "no model runner" in text

    first = _evaluate(home, bundle, _valid_candidate(bundle))["data"]
    second = _evaluate(home, bundle, _valid_candidate(bundle))["data"]
    assert first["evaluation_id"] == second["evaluation_id"]
    assert first["summary"]["overall_status"] == "pass"
    assert _criterion(first, "future_leakage")["status"] == "pass"
    assert first["hard_constraints"]["no_backtester"] is True


def test_future_leakage_fails_on_evaluator_only_ids(tmp_path):
    home = _init_home(tmp_path)
    bundle = _labeled_bundle(home)
    candidate = _valid_candidate(bundle)
    outcome_id = bundle["evaluation_labels"]["labels"][0]["outcomes"][0]["outcome_id"]
    candidate["analysis"] = f"I used future outcome {outcome_id} from evaluation_labels."

    data = _evaluate(home, bundle, candidate)["data"]
    assert data["summary"]["overall_status"] == "fail"
    assert _criterion(data, "future_leakage")["status"] == "fail"


def test_boundary_language_fails(tmp_path):
    home = _init_home(tmp_path)
    bundle = _labeled_bundle(home)
    candidate = _valid_candidate(bundle)
    candidate["analysis"] = "This is a buy recommendation with simulated fill and backtest return proof."

    data = _evaluate(home, bundle, candidate)["data"]
    assert _criterion(data, "boundary_language")["status"] == "fail"
    assert data["summary"]["overall_status"] == "fail"


def test_missing_metadata_and_forecast_required_fail(tmp_path):
    home = _init_home(tmp_path)
    bundle = _labeled_bundle(home)
    candidate = _valid_candidate(bundle)
    candidate["metadata"].pop("model_id")
    candidate.pop("forecast")

    data = _evaluate(home, bundle, candidate)["data"]
    assert _criterion(data, "candidate_metadata")["status"] == "fail"
    assert _criterion(data, "forecast_required")["status"] == "fail"
    assert data["summary"]["overall_status"] == "fail"


def test_candidate_metadata_alias_accepted(tmp_path):
    # AX-053: a caller supplying metadata under `candidate_metadata` (mirroring
    # the bundle's `candidate_metadata_required` field) must pass, not report
    # every field missing. There is no published candidate_output schema, so the
    # checker accepts both `metadata` and `candidate_metadata`.
    home = _init_home(tmp_path)
    bundle = _labeled_bundle(home)
    candidate = _valid_candidate(bundle)
    candidate["candidate_metadata"] = candidate.pop("metadata")

    data = _evaluate(home, bundle, candidate)["data"]
    assert _criterion(data, "candidate_metadata")["status"] == "pass"


def test_invalid_decision_type_fails(tmp_path):
    home = _init_home(tmp_path)
    bundle = _labeled_bundle(home)
    candidate = _valid_candidate(bundle)
    candidate["decision"]["type"] = "definitely_buy"

    data = _evaluate(home, bundle, candidate)["data"]
    assert _criterion(data, "decision_type")["status"] == "fail"
    assert data["summary"]["overall_status"] == "fail"


def test_ambiguous_no_citations_with_insufficient_context(tmp_path):
    home = _init_home(tmp_path)
    bundle = _labeled_bundle(home)
    candidate = _valid_candidate(bundle)
    candidate.pop("citations")
    candidate["insufficient_context"] = True

    data = _evaluate(home, bundle, candidate)["data"]
    assert _criterion(data, "citation_coverage")["status"] == "ambiguous"
    assert data["summary"]["overall_status"] in {"ambiguous", "fail"}


def test_malformed_case_bundle_cases_returns_criteria_failure(tmp_path):
    home = _init_home(tmp_path)
    bundle = {
        "kind": "replay.case_bundle",
        "contract_version": "replay.case_bundle.v0",
        "cases": ["bad"],
    }

    env = _evaluate(home, bundle, {"metadata": _metadata()})

    assert env["ok"] is True
    data = env["data"]
    assert _criterion(data, "bundle_contract")["status"] == "fail"
    assert "malformed_case_entries" in _criterion(data, "bundle_contract")["caveat_codes"]
    assert _criterion(data, "case_coverage")["status"] == "fail"
    assert data["summary"]["overall_status"] == "fail"


def test_no_hidden_writes_and_no_network(tmp_path, monkeypatch):
    home = _init_home(tmp_path)
    bundle = _labeled_bundle(home)

    def fail_network(*args, **kwargs):  # pragma: no cover
        raise AssertionError("replay.evaluate_output must not fetch")

    monkeypatch.setattr(socket, "socket", fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)
    before = sqlite3.connect(db_path(home)).execute("SELECT COUNT(*) FROM events").fetchone()[0]
    env = _evaluate(home, bundle, _valid_candidate(bundle))
    after = sqlite3.connect(db_path(home)).execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert env["ok"] is True
    assert before == after
    assert env["data"]["metadata"]["read_only"] is True
