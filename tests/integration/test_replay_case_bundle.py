from __future__ import annotations

import json
import socket
import sqlite3
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage.paths import db_path
from trade_trace.tools._helpers import CLOCK_OVERRIDE


def _init_home(tmp_path) -> Path:
    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}).model_dump(mode="json")["ok"] is True
    return home


def _seed_case(home: Path, thesis_overrides: dict | None = None, forecast_overrides: dict | None = None) -> dict[str, str]:
    token = CLOCK_OVERRIDE.set(datetime(2026, 5, 18, 14, 0, 0, tzinfo=UTC))
    try:
        venue = _envelope(home, "venue.add", {"name": "Replay PM", "kind": "prediction_market"})
        inst = _envelope(home, "instrument.add", {"venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "Replay Event", "symbol": "RPLY"})
        snap = _envelope(home, "snapshot.add", {"instrument_id": inst["data"]["id"], "captured_at": "2026-05-18T12:00:00Z", "implied_probability": 0.52, "spread": 0.03})
        thesis_args = {"instrument_id": inst["data"]["id"], "side": "yes", "body": "pre as_of thesis body", **(thesis_overrides or {})}
        thesis = _envelope(home, "thesis.add", thesis_args)
        forecast_args = {"thesis_id": thesis["data"]["id"], "kind": "binary", "resolution_at": "2026-06-01T00:00:00Z", "yes_label": "yes", "resolution_rule_text": "caller supplied rule", "outcomes": [{"outcome_label": "yes", "probability": 0.7}, {"outcome_label": "no", "probability": 0.3}], **(forecast_overrides or {})}
        forecast = _envelope(home, "forecast.add", forecast_args)
        decision = _envelope(home, "decision.add", {"instrument_id": inst["data"]["id"], "thesis_id": thesis["data"]["id"], "forecast_id": forecast["data"]["id"], "snapshot_id": snap["data"]["id"], "type": "skip", "reason": "future answer hidden"})
        source = _envelope(home, "source.add", {"kind": "note", "title": "Pre as_of local note", "excerpt": "stored snippet"})
        _envelope(home, "source.attach_to_forecast", {"source_id": source["data"]["id"], "target_id": forecast["data"]["id"]})
    finally:
        CLOCK_OVERRIDE.reset(token)
    token = CLOCK_OVERRIDE.set(datetime(2026, 5, 21, 14, 0, 0, tzinfo=UTC))
    try:
        outcome = _envelope(home, "resolution.add", {"instrument_id": inst["data"]["id"], "resolved_at": "2026-06-02T00:00:00Z", "outcome_label": "yes", "status": "resolved_final", "confidence": 0.99})
    finally:
        CLOCK_OVERRIDE.reset(token)
    return {"instrument": inst["data"]["id"], "snapshot": snap["data"]["id"], "thesis": thesis["data"]["id"], "forecast": forecast["data"]["id"], "decision": decision["data"]["id"], "source": source["data"]["id"], "outcome": outcome["data"]["id"]}


def _seed_other_forecast(home: Path, symbol: str = "OTHER") -> dict[str, str]:
    token = CLOCK_OVERRIDE.set(datetime(2026, 5, 18, 15, 0, 0, tzinfo=UTC))
    try:
        venue = _envelope(home, "venue.add", {"name": f"Replay {symbol}", "kind": "prediction_market"})
        inst = _envelope(home, "instrument.add", {"venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": f"Replay {symbol}", "symbol": symbol})
        thesis = _envelope(home, "thesis.add", {"instrument_id": inst["data"]["id"], "side": "yes", "body": "other thesis"})
        forecast = _envelope(home, "forecast.add", {"thesis_id": thesis["data"]["id"], "kind": "binary", "resolution_at": "2026-06-01T00:00:00Z", "yes_label": "yes", "resolution_rule_text": "other rule", "outcomes": [{"outcome_label": "yes", "probability": 0.4}, {"outcome_label": "no", "probability": 0.6}]})
    finally:
        CLOCK_OVERRIDE.reset(token)
    return {"instrument": inst["data"]["id"], "thesis": thesis["data"]["id"], "forecast": forecast["data"]["id"]}


def _bundle(home: Path, **overrides):
    args = {"as_of": "2026-05-20T00:00:00-00:00", "case_selection": {"max_cases": 10}}
    args.update(overrides)
    return _envelope(home, "replay.case_bundle", args)


def test_registered_schema_and_read_only_boundary_text():
    reg = default_registry()
    tool = reg.get("replay.case_bundle")
    assert "replay.case_bundle" in reg.names()
    assert tool.is_write is False
    schema = tool.json_schema
    assert schema["required"] == ["as_of"]
    text = (tool.description + " " + schema["description"]).lower()
    assert "read-only" in text
    assert "no fetch" in text
    assert "no model runner" in text
    assert "no market simulator" in text


def test_deterministic_bundle_id_and_ordering(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(home)
    first = _bundle(home)["data"]
    second = _bundle(home)["data"]
    assert first["bundle_id"] == second["bundle_id"]
    assert [c["source_id"] for c in first["case_index"]] == [ids["decision"], ids["forecast"]]
    assert first["as_of_boundary"]["as_of"] == "2026-05-20T00:00:00.000Z"


def test_source_refs_selection_includes_pre_as_of_context_and_hides_original(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(home)
    data = _bundle(home, case_selection={"source_refs": [{"kind": "decision", "id": ids["decision"]}], "max_cases": 5})["data"]
    assert len(data["cases"]) == 1
    case = data["cases"][0]
    assert case["source_refs"] == [{"kind": "decision", "id": ids["decision"]}]
    assert case["original_artifact"]["status"] == "withheld"
    ctx = case["point_in_time_context"]
    assert ctx["instrument"]["instrument_id"] == ids["instrument"]
    assert ctx["snapshots"][0]["snapshot_id"] == ids["snapshot"]
    assert ctx["theses"][0]["thesis_id"] == ids["thesis"]
    assert ctx["forecasts"][0]["forecast_id"] == ids["forecast"]
    assert ids["source"] in {s["source_id"] for s in ctx["sources"]}
    assert data["evaluation_labels"]["status"] == "withheld"


def test_future_labels_absent_from_context_and_only_included_on_opt_in(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(home)
    hidden = _bundle(home, case_selection={"source_refs": [{"kind": "decision", "id": ids["decision"]}]})["data"]
    ctx_text = json.dumps(hidden["cases"][0]["point_in_time_context"], sort_keys=True)
    assert ids["outcome"] not in ctx_text
    assert hidden["evaluation_labels"]["status"] == "withheld"
    included = _bundle(home, case_selection={"source_refs": [{"kind": "decision", "id": ids["decision"]}]}, task={"mode": "blind_decision", "include_evaluation_labels": True})["data"]
    assert included["evaluation_labels"]["status"] == "included_for_evaluator_only"
    assert included["evaluation_labels"]["labels"][0]["outcomes"][0]["outcome_id"] == ids["outcome"]
    assert ids["outcome"] not in json.dumps(included["cases"][0]["point_in_time_context"], sort_keys=True)
    forecast_context = included["cases"][0]["point_in_time_context"]["forecasts"][0]
    assert "scoring_state_as_recorded" not in forecast_context
    assert forecast_context["scoring_state_as_of_caveat"] == "not_reconstructed_v0"


def test_invalid_filter_rejected_not_broadened(tmp_path):
    home = _init_home(tmp_path)
    _seed_case(home)
    env = _bundle(home, case_selection={"filter": {"outcome": {"resolution_status": ["resolved_final"]}}, "max_cases": 5})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert "unsupported replay.case_bundle filter fields" in env["error"]["message"]


def test_no_hidden_writes_and_no_network(tmp_path, monkeypatch):
    home = _init_home(tmp_path)
    _seed_case(home)

    def fail_network(*args, **kwargs):  # pragma: no cover
        raise AssertionError("replay.case_bundle must not fetch")

    monkeypatch.setattr(socket, "socket", fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)
    before = sqlite3.connect(db_path(home)).execute("SELECT COUNT(*) FROM events").fetchone()[0]
    env = _bundle(home, case_selection={"max_cases": 1})
    after = sqlite3.connect(db_path(home)).execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert env["ok"] is True
    assert before == after
    assert env["data"]["leakage_protections"]["no_hidden_writes"] is True
    assert env["data"]["hard_constraints"]["no_market_simulator"] is True


def test_filter_selection_decision_and_forecast_cases(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(home)
    data = _bundle(
        home,
        case_selection={
            "filter": {
                "instrument": {"instrument_id": [ids["instrument"]], "symbol": []},
                "decision": {"decision_type": ["skip"], "has_forecast": True},
            },
            "max_cases": 5,
        },
    )["data"]
    assert {c["case_key"]["source_kind"] for c in data["cases"]} == {"decision", "forecast"}
    assert data["leakage_protections"]["candidate_context_excludes_future_labels"] is True
    assert data["hard_constraints"]["read_only"] is True


def test_symbol_and_forecast_filters_are_not_broadened(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(home)
    other = _seed_other_forecast(home)
    data = _bundle(home, case_selection={"filter": {"instrument": {"symbol": ["RPLY"]}}, "max_cases": 10})["data"]
    selected_ids = {c["case_key"]["source_id"] for c in data["cases"]}
    assert ids["decision"] in selected_ids
    assert ids["forecast"] in selected_ids
    assert other["forecast"] not in selected_ids

    empty = _bundle(home, case_selection={"filter": {"instrument": {"instrument_id": [other["instrument"]]}, "decision": {"decision_type": ["skip"]}}, "max_cases": 10})["data"]
    assert empty["cases"] == []


def test_case_id_roundtrip_and_mismatch_rejected(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(home)
    initial = _bundle(home, case_selection={"source_refs": [{"kind": "decision", "id": ids["decision"]}], "max_cases": 1})["data"]
    case_id = initial["cases"][0]["case_id"]
    roundtrip = _bundle(home, case_selection={"case_ids": [case_id], "max_cases": 10})["data"]
    assert [c["case_id"] for c in roundtrip["cases"]] == [case_id]

    rejected = _bundle(home, case_selection={"case_ids": [case_id]}, task={"mode": "review_original"})
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_thesis_and_forecast_windows_excluded_from_candidate_context(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(home, thesis_overrides={"valid_to": "2026-05-19T00:00:00Z"}, forecast_overrides={"valid_to": "2026-05-19T12:00:00Z"})

    data = _bundle(home, case_selection={"source_refs": [{"kind": "decision", "id": ids["decision"]}], "max_cases": 1})["data"]
    case = data["cases"][0]
    ctx = case["point_in_time_context"]
    assert ctx["theses"] == []
    assert ctx["forecasts"] == []
    assert {item["reason"] for item in data["excluded_artifacts"] if item["kind"] in {"thesis", "forecast"}} == {"not_valid_at_as_of"}
    assert "thesis_not_valid_at_as_of_excluded" in case["caveat_codes"]
    assert "forecast_not_valid_at_as_of_excluded" in case["caveat_codes"]


def test_valid_forecast_with_invalid_linked_thesis_excluded_from_decision_context(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(
        home,
        thesis_overrides={"valid_to": "2026-05-19T00:00:00Z"},
        forecast_overrides={"valid_to": "2026-05-21T00:00:00Z"},
    )

    data = _bundle(home, case_selection={"source_refs": [{"kind": "decision", "id": ids["decision"]}], "max_cases": 1})["data"]
    case = data["cases"][0]
    ctx = case["point_in_time_context"]
    assert ctx["theses"] == []
    assert ctx["forecasts"] == []
    assert "thesis_not_valid_at_as_of_excluded" in case["caveat_codes"]
    assert "forecast_linked_thesis_not_valid_at_as_of_excluded" in case["caveat_codes"]
    assert {item["reason"] for item in data["excluded_artifacts"] if item["kind"] == "forecast"} == {"linked_thesis_not_valid_at_as_of"}


def test_not_yet_valid_forecast_source_ref_produces_no_case(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(home, forecast_overrides={"valid_from": "2026-05-21T00:00:00Z"})

    data = _bundle(home, case_selection={"source_refs": [{"kind": "forecast", "id": ids["forecast"]}], "max_cases": 1})["data"]
    assert data["cases"] == []
    assert data["case_index"] == []


def test_forecast_source_ref_with_invalid_linked_thesis_produces_no_case(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_case(
        home,
        thesis_overrides={"valid_to": "2026-05-19T00:00:00Z"},
        forecast_overrides={"valid_to": "2026-05-21T00:00:00Z"},
    )

    data = _bundle(home, case_selection={"source_refs": [{"kind": "forecast", "id": ids["forecast"]}], "max_cases": 1})["data"]
    assert data["cases"] == []
    assert data["case_index"] == []


def test_recall_event_source_ref_must_exist_and_be_pre_as_of(tmp_path):
    home = _init_home(tmp_path)
    missing = _bundle(home, case_selection={"source_refs": [{"kind": "recall_event", "id": "rec_missing"}], "max_cases": 1})
    assert missing["ok"] is False
    assert missing["error"]["code"] == "VALIDATION_ERROR"
    assert "not locally verifiable" in missing["error"]["message"]

    conn = sqlite3.connect(db_path(home))
    try:
        conn.execute(
            "INSERT INTO memory_recall_events(recall_id, query, strategies_used, node_ids_returned, context_json, limit_k, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("rec_future", "q", "[]", "[]", "{}", 5, "2026-05-21T00:00:00.000Z", "test"),
        )
        conn.execute(
            "INSERT INTO memory_recall_events(recall_id, query, strategies_used, node_ids_returned, context_json, limit_k, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("rec_past", "q", "[]", "[]", "{}", 5, "2026-05-19T00:00:00.000Z", "test"),
        )
        conn.commit()
    finally:
        conn.close()

    future = _bundle(home, case_selection={"source_refs": [{"kind": "recall_event", "id": "rec_future"}], "max_cases": 1})
    assert future["ok"] is False
    assert future["error"]["code"] == "VALIDATION_ERROR"
    assert "created after as_of" in future["error"]["message"]

    data = _bundle(home, case_selection={"source_refs": [{"kind": "recall_event", "id": "rec_past"}], "max_cases": 1})["data"]
    assert data["case_index"][0]["source_id"] == "rec_past"
    assert data["cases"][0]["eligibility_status"] == "needs_caveat"


def _seed_n_distinct_forecasts(home: Path, n: int) -> None:
    """Seed `n` forecasts each on its own instrument so case selection can
    return more than one case (forecast.add folds repeated forecasts on the
    same instrument, so distinct instruments are required to grow the count)."""
    token = CLOCK_OVERRIDE.set(datetime(2026, 5, 18, 14, 0, 0, tzinfo=UTC))
    try:
        venue = _envelope(home, "venue.add", {"name": "Trunc Venue", "kind": "prediction_market"})
        for i in range(n):
            inst = _envelope(home, "instrument.add", {"venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": f"Trunc {i}", "symbol": f"TRUNC{i}"})
            thesis = _envelope(home, "thesis.add", {"instrument_id": inst["data"]["id"], "side": "yes", "body": f"trunc thesis {i}"})
            _envelope(home, "forecast.add", {"thesis_id": thesis["data"]["id"], "kind": "binary", "resolution_at": "2026-06-01T00:00:00Z", "yes_label": "yes", "resolution_rule_text": "rule", "outcomes": [{"outcome_label": "yes", "probability": 0.6}, {"outcome_label": "no", "probability": 0.4}]})
    finally:
        CLOCK_OVERRIDE.reset(token)


def test_bundle_meta_truncated_mirrors_bundle_truncation_flag(tmp_path):
    """trade-trace-5eh3 / nyix(10): the replay.case_bundle handler propagates
    the bundle's `truncation.is_partial` onto the envelope `meta.truncated`
    (tool_handlers/replay.py:37). This pins that propagation contract: whatever
    the bundle reports as its partial flag is exactly what surfaces on the
    envelope meta — they must never diverge."""
    home = _init_home(tmp_path)
    _seed_n_distinct_forecasts(home, 4)

    # Selecting fewer than the available cases physically clips the result set.
    env = _bundle(home, case_selection={"max_cases": 2})
    assert env["ok"] is True, env
    assert len(env["data"]["cases"]) == 2, "case set is physically clipped to max_cases"
    # The propagation contract: meta.truncated == bundle truncation.is_partial.
    assert env["meta"].get("truncated") == bool(env["data"]["truncation"]["is_partial"])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFERRED (trade-trace-5eh3 / nyix item 10): meta.truncated can only "
        "surface True if the bundle sets truncation.is_partial=True when the "
        "selection exceeds max_cases. The source (src/trade_trace/reports/"
        "replay.py:399) hardcodes is_partial=False and _rows_for_selection "
        "clips via LIMIT/[:max_cases] without recording that extra rows "
        "existed, so over-limit truncation is silently undetected. Surfacing "
        "truncated=True requires a change to that replay module, which is "
        "OUTSIDE this bead's in-scope files. This xfail(strict) documents the "
        "intended behavior and will fail loudly (prompting promotion) once the "
        "source learns to detect and report over-limit truncation."
    ),
)
def test_bundle_meta_truncated_surfaces_true_when_over_max_cases(tmp_path):
    home = _init_home(tmp_path)
    _seed_n_distinct_forecasts(home, 4)
    env = _bundle(home, case_selection={"max_cases": 2})
    assert env["meta"].get("truncated") is True
