from __future__ import annotations

import json
import re

from tests.integration.test_replay_case_bundle import _bundle, _init_home, _seed_case
from tests.integration.test_replay_evaluate_output import _criterion, _evaluate, _valid_candidate
from trade_trace.core import default_registry


def _explicit_labeled_bundle(home, ids: dict[str, str]) -> dict:
    return _bundle(
        home,
        case_selection={"source_refs": [{"kind": "decision", "id": ids["decision"]}], "max_cases": 1},
        task={"mode": "blind_decision", "include_evaluation_labels": True},
    )["data"]


def _label_ids(bundle: dict) -> tuple[str, str]:
    labels = bundle["evaluation_labels"]["labels"][0]
    outcome_id = labels["outcomes"][0]["outcome_id"]
    forecast_score_id = labels["forecast_scores"][0]["forecast_score_id"]
    return outcome_id, forecast_score_id


def test_case_bundle_keeps_future_labels_out_of_candidate_visible_context(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(home)

    bundle = _explicit_labeled_bundle(home, ids)
    outcome_id, forecast_score_id = _label_ids(bundle)

    cases_text = json.dumps(bundle["cases"], sort_keys=True)
    assert outcome_id not in cases_text
    assert forecast_score_id not in cases_text
    assert "forecast_score_id" not in cases_text
    assert "scoring_state_as_recorded" not in cases_text

    # Future labels may be present for evaluator-only use, but only in the
    # explicit top-level label bucket and the excluded-artifact audit trail.
    assert bundle["evaluation_labels"]["status"] == "included_for_evaluator_only"
    assert outcome_id in json.dumps(bundle["evaluation_labels"], sort_keys=True)
    assert forecast_score_id in json.dumps(bundle["evaluation_labels"], sort_keys=True)
    assert {item["id"] for item in bundle["excluded_artifacts"]} >= {outcome_id, forecast_score_id}

    top_level_allowed = {"evaluation_labels", "excluded_artifacts"}
    for key, value in bundle.items():
        if key in top_level_allowed:
            continue
        text = json.dumps(value, sort_keys=True)
        assert outcome_id not in text, key
        assert forecast_score_id not in text, key


def test_evaluator_flags_future_outcome_and_score_ids_in_candidate_output(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(home)
    bundle = _explicit_labeled_bundle(home, ids)
    outcome_id, forecast_score_id = _label_ids(bundle)
    candidate = _valid_candidate(bundle)
    candidate["analysis"] = (
        f"I inspected evaluator-only outcome {outcome_id} and forecast score "
        f"{forecast_score_id} from evaluation_labels."
    )

    data = _evaluate(home, bundle, candidate)["data"]

    assert data["summary"]["overall_status"] == "fail"
    future_leakage = _criterion(data, "future_leakage")
    assert future_leakage["status"] == "fail"
    assert outcome_id in future_leakage["source_refs"]
    assert forecast_score_id in future_leakage["source_refs"]
    assert "evaluation_labels" in future_leakage["caveat_codes"]


def test_evaluator_flags_unsupported_backtest_execution_and_profit_language(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(home)
    bundle = _explicit_labeled_bundle(home, ids)
    candidate = _valid_candidate(bundle)
    candidate["analysis"] = (
        "I performed market path reconstruction, placed order instructions, "
        "captured a simulated fill, and use backtest return as profit proof."
    )

    data = _evaluate(home, bundle, candidate)["data"]

    assert data["summary"]["overall_status"] == "fail"
    boundary = _criterion(data, "boundary_language")
    assert boundary["status"] == "fail"
    assert set(boundary["caveat_codes"]) >= {
        "execution_or_fill",
        "backtest_claim",
        "profitability_claim",
        "market_path_reconstruction",
    }


def test_replay_tool_metadata_only_uses_forbidden_concepts_as_negative_boundaries():
    forbidden = {
        "market simulator",
        "market simulation",
        "market-path simulation",
        "simulated fills",
        "simulated fill",
        "backtester",
        "backtesting",
        "backtest",
        "profit proof",
        "execution semantics",
        "broker/execution path",
        "market path reconstruction",
    }
    negative_prefix = re.compile(r"\b(no|not|non-goal|unsupported|forbidden|does not|without|never)\b")
    reg = default_registry()

    for tool_name in ("replay.case_bundle", "replay.evaluate_output"):
        tool = reg.get(tool_name)
        text = json.dumps({"description": tool.description, "schema": tool.json_schema}, sort_keys=True).lower()
        for phrase in forbidden:
            start = 0
            while True:
                idx = text.find(phrase, start)
                if idx == -1:
                    break
                window = text[max(0, idx - 80) : idx + len(phrase) + 40]
                assert negative_prefix.search(window), (tool_name, phrase, window)
                start = idx + len(phrase)

    case_text = json.dumps(reg.get("replay.case_bundle").json_schema, sort_keys=True).lower()
    evaluate_text = json.dumps(reg.get("replay.evaluate_output").json_schema, sort_keys=True).lower()
    assert "future outcomes/labels are withheld from candidate context" in case_text
    assert "process checker" in evaluate_text
