from __future__ import annotations

import json
import re
import socket
import sqlite3
import urllib.request
from pathlib import Path

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage.paths import db_path


def _init_home(tmp_path) -> Path:
    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}).model_dump(mode="json")["ok"] is True
    return home


def _assert_no_fetch_or_advice_text(payload: object, *, description: str = "") -> None:
    text = (json.dumps(payload, sort_keys=True) + " " + description).lower()
    forbidden = re.compile(
        r"\b(buy recommendation|sell recommendation|trade recommendation|recommended trade|"
        r"best strategy|trade more|profitable|profit ranking|ranked by profit|"
        r"guaranteed profit|buy now|sell now)\b"
    )
    assert forbidden.findall(text) == []


def _seed_binary_case(
    home: Path,
    *,
    implied_probability: float | None = 0.55,
    decision_type: str = "skip",
    strategy_id: str | None = None,
    snapshot_overrides: dict | None = None,
) -> dict[str, str]:
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {"venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "X"})
    snap_args = {"instrument_id": inst["data"]["id"], "captured_at": "2026-05-18T14:00:00Z", "spread": 0.03, "volume": 100.0}
    if implied_probability is not None:
        snap_args["implied_probability"] = implied_probability
    if snapshot_overrides:
        snap_args.update(snapshot_overrides)
    snap = _envelope(home, "snapshot.add", snap_args)
    thesis_args = {"instrument_id": inst["data"]["id"], "side": "yes", "body": "retrospective case"}
    if strategy_id:
        thesis_args["strategy_id"] = strategy_id
    thesis = _envelope(home, "thesis.add", thesis_args)
    forecast = _envelope(home, "forecast.add", {"thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes", "outcomes": [{"outcome_label": "yes", "probability": 0.70}, {"outcome_label": "no", "probability": 0.30}]})
    decision_args = {"instrument_id": inst["data"]["id"], "thesis_id": thesis["data"]["id"], "forecast_id": forecast["data"]["id"], "snapshot_id": snap["data"]["id"], "type": decision_type, "reason": "diagnostic fixture"}
    if strategy_id:
        decision_args["strategy_id"] = strategy_id
    if decision_type not in {"skip", "review"}:
        decision_args["side"] = "yes"
    decision = _envelope(home, "decision.add", decision_args)
    outcome = _envelope(home, "outcome.add", {"instrument_id": inst["data"]["id"], "resolved_at": "2026-06-30T00:00:00Z", "outcome_label": "yes", "status": "resolved_final", "confidence": 0.99})
    return {"instrument": inst["data"]["id"], "forecast": forecast["data"]["id"], "thesis": thesis["data"]["id"], "decision": decision["data"]["id"], "snapshot": snap["data"]["id"], "outcome": outcome["data"]["id"]}


def test_report_forecast_diagnostics_registered():
    assert "report.forecast_diagnostics" in default_registry().names()


def test_binary_scored_forecast_with_caller_snapshot_reference(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_binary_case(home, implied_probability=0.55, decision_type="skip")

    env = _envelope(home, "report.forecast_diagnostics", {"min_sample": 1})
    data = env["data"]

    assert data["summary"]["sample_size"] == 1
    assert data["summary"]["metrics"]["brier"] == 0.09
    market = data["summary"]["market_reference"]
    assert market["reference_source"] == "caller_supplied_snapshots_implied_probability"
    assert market["count_with_recorded_implied_probability"] == 1
    assert market["mean_recorded_market_reference_gap"] == 0.15
    assert ids["forecast"] in data["groups"][0]["record_ids"]["forecasts"]
    assert ids["decision"] in data["groups"][0]["record_ids"]["decisions"]
    assert data["summary"]["decision_coverage"]["by_decision_type"]["skip"]["with_forecast_count"] == 1


def test_forecast_diagnostics_prefers_canonical_probability_when_legacy_outcomes_disagree(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_binary_case(home, implied_probability=0.55, decision_type="skip")
    with sqlite3.connect(db_path(home)) as conn:
        conn.execute("DROP TRIGGER trg_forecasts_no_update")
        conn.execute("UPDATE forecasts SET probability = 0.8 WHERE id = ?", (ids["forecast"],))
        conn.execute(
            """
            CREATE TRIGGER trg_forecasts_no_update
            BEFORE UPDATE ON forecasts
            BEGIN
                SELECT RAISE(ABORT, 'append-only invariant: UPDATE on forecasts is forbidden; use a supersedes edge to record a correction (persistence.md §8)');
            END
            """
        )
        conn.commit()

    data = _envelope(home, "report.forecast_diagnostics", {"min_sample": 1})["data"]
    assert data["summary"]["sample_size"] == 1
    assert data["summary"]["metrics"]["brier"] == 0.04
    assert data["summary"]["market_reference"]["mean_recorded_market_reference_gap"] == 0.25


def test_multiple_decisions_do_not_duplicate_forecast_metrics(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_binary_case(home, implied_probability=0.55, decision_type="skip")
    snap2 = _envelope(home, "snapshot.add", {"instrument_id": ids["instrument"], "captured_at": "2026-05-18T15:00:00Z", "implied_probability": 0.60, "spread": 0.04, "volume": 25.0})
    decision2 = _envelope(home, "decision.add", {"instrument_id": ids["instrument"], "thesis_id": ids["thesis"], "forecast_id": ids["forecast"], "snapshot_id": snap2["data"]["id"], "type": "skip", "reason": "second diagnostic reference"})

    data = _envelope(home, "report.forecast_diagnostics", {"min_sample": 1})["data"]

    assert data["summary"]["sample_size"] == 1
    assert data["summary"]["metrics"]["brier"] == 0.09
    market = data["summary"]["market_reference"]
    assert market["weighting"] == "snapshot_decision_reference_counted"
    assert market["count_with_recorded_implied_probability"] == 2
    assert market["mean_recorded_market_reference_gap"] == 0.125
    assert decision2["data"]["id"] in data["groups"][0]["record_ids"]["decisions"]


def test_strategy_slug_filter_matches_strategy_id_filter(tmp_path):
    home = _init_home(tmp_path)
    strategy = _envelope(home, "strategy.create", {"name": "Diagnostic Strategy", "slug": "diagnostic-strategy"})
    ids = _seed_binary_case(home, implied_probability=0.55, strategy_id=strategy["data"]["id"])

    by_id = _envelope(home, "report.forecast_diagnostics", {"filter": {"strategy": {"strategy_id": strategy["data"]["id"]}}, "min_sample": 1})["data"]
    by_slug = _envelope(home, "report.forecast_diagnostics", {"filter": {"strategy": {"strategy_id": "diagnostic-strategy"}}, "min_sample": 1})["data"]

    assert by_id["summary"]["sample_size"] == 1
    assert by_slug["summary"]["sample_size"] == 1
    assert by_slug["groups"][0]["record_ids"]["forecasts"] == [ids["forecast"]]
    assert by_slug["summary"]["metrics"] == by_id["summary"]["metrics"]


def test_source_reference_coverage_caveat_reports_missing_local_refs(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_binary_case(home, implied_probability=0.55)
    source = _envelope(home, "source.add", {"kind": "url", "uri": "https://example.invalid/diagnostic-source"})
    _envelope(home, "source.attach_to_forecast", {"source_id": source["data"]["id"], "target_id": ids["forecast"]})

    data = _envelope(home, "report.forecast_diagnostics", {"min_sample": 1})["data"]
    coverage = data["summary"]["source_reference_coverage"]

    assert "missing_source_reference" in data["summary"]["caveat_codes"]
    assert coverage["covered_source_reference_count"] == 1
    assert ids["thesis"] in coverage["missing_record_ids_by_kind"]["theses"]
    assert ids["decision"] in coverage["missing_record_ids_by_kind"]["decisions"]


def test_non_binary_excluded_and_missing_reference_low_n_caveats(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_binary_case(home, implied_probability=None, decision_type="watch")
    venue = _envelope(home, "venue.add", {"name": "PM2", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {"venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "Y"})
    thesis = _envelope(home, "thesis.add", {"instrument_id": inst["data"]["id"], "side": "yes", "body": "categorical"})
    # forecast.add is binary-only in v0.0.2, but the diagnostic report still needs
    # to account for legacy categorical/scalar rows in existing journals.
    categorical_forecast_id = "fc_legacy_categorical"
    with sqlite3.connect(db_path(home)) as conn:
        conn.execute(
            """
            INSERT INTO forecasts (id, thesis_id, kind, scoring_support, scoring_state, created_at, actor_id)
            VALUES (?, ?, 'categorical', 'unsupported', 'failed', '2026-05-18T14:00:00.000Z', 'test')
            """,
            (categorical_forecast_id, thesis["data"]["id"]),
        )
        conn.executemany(
            """
            INSERT INTO forecast_outcomes (id, forecast_id, outcome_label, probability)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("fo_legacy_categorical_a", categorical_forecast_id, "a", 0.5),
                ("fo_legacy_categorical_b", categorical_forecast_id, "b", 0.5),
            ],
        )

    data = _envelope(home, "report.forecast_diagnostics", {})["data"]

    assert data["summary"]["sample_size"] == 1
    assert "low_n" in data["summary"]["caveat_codes"]
    assert "missing_market_reference" in data["summary"]["market_reference"]["caveat_codes"]
    assert data["summary"]["exclusions"]["counts_by_reason"]["unsupported_non_binary"] == 1
    assert categorical_forecast_id in data["summary"]["exclusions"]["forecast_ids_by_reason"]["unsupported_non_binary"]
    assert ids["snapshot"] in data["groups"][0]["record_ids"]["snapshots"]


def test_missing_implied_probability_is_not_inferred_from_price_bid_ask_mid(tmp_path):
    home = _init_home(tmp_path)
    _seed_binary_case(
        home,
        implied_probability=None,
        decision_type="watch",
        snapshot_overrides={"price": 0.42, "bid": 0.40, "ask": 0.44, "mid": 0.42, "spread": 0.04},
    )

    data = _envelope(home, "report.forecast_diagnostics", {"min_sample": 1})["data"]
    market = data["summary"]["market_reference"]

    assert market["count_with_recorded_implied_probability"] == 0
    assert market["count_missing_recorded_implied_probability"] == 1
    assert market["mean_recorded_market_reference_gap"] is None
    assert market["max_abs_recorded_market_reference_gap"] is None
    assert "missing_market_reference" in market["caveat_codes"]


def test_wide_spread_and_skipped_opportunity_caveats_are_explicit(tmp_path):
    home = _init_home(tmp_path)
    ids = _seed_binary_case(
        home,
        implied_probability=0.55,
        decision_type="skip",
        snapshot_overrides={"spread": 0.25, "volume": None, "open_interest": None},
    )

    data = _envelope(home, "report.forecast_diagnostics", {})["data"]
    market = data["summary"]["market_reference"]

    assert data["summary"]["sample_size"] == 1
    assert data["summary"]["sample_warning"] is not None
    assert "low_n" in data["summary"]["caveat_codes"]
    assert "wide_spread" in market["caveat_codes"]
    assert "wide_spread" in data["summary"]["caveat_codes"]
    assert market["wide_spread_threshold"] == 0.10
    assert data["summary"]["decision_coverage"]["by_decision_type"]["skip"]["decision_ids"] == [ids["decision"]]


def test_output_avoids_forbidden_advice_fetch_profit_ranking_phrases(tmp_path):
    home = _init_home(tmp_path)
    _seed_binary_case(home, implied_probability=0.55)
    registry = default_registry()
    desc = registry.get("report.forecast_diagnostics").description
    data = _envelope(home, "report.forecast_diagnostics", {})["data"]
    _assert_no_fetch_or_advice_text(data, description=desc)
    assert "no external fetching" in (json.dumps(data).lower() + " " + desc.lower())


def test_forecast_diagnostics_does_not_open_network_paths(tmp_path, monkeypatch):
    home = _init_home(tmp_path)
    _seed_binary_case(home, implied_probability=0.55)

    def fail_network(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("forecast diagnostics must not fetch live data")

    monkeypatch.setattr(socket, "socket", fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)
    env = _envelope(home, "report.forecast_diagnostics", {"min_sample": 1})
    assert env["ok"] is True
