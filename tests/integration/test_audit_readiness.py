from __future__ import annotations

from pathlib import Path

import pytest

from tests._mcp_helpers import mcp_default as _mcp


def test_audit_readiness_empty_journal_safe(home: Path):
    env = _mcp(home, "report.audit_readiness", {})
    assert env.ok, env
    assert env.data["summary"]["sample_size"] == 0
    assert env.data["summary"]["ready"] is False
    assert env.data["summary"]["sample_warning"] == "no_data"
    assert env.data["issues"] == []


def test_audit_readiness_surfaces_prediction_market_blockers_and_warnings(home: Path):
    venue = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue,
        "asset_class": "prediction_market",
        "title": "Will X happen?",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {"instrument_id": inst, "side": "yes", "body": "because"}).data["id"]
    fcst = _mcp(home, "forecast.add", {
        "thesis_id": thesis,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.55},
            {"outcome_label": "no", "probability": 0.45},
        ],
    }).data["id"]
    old_snap = _mcp(home, "snapshot.add", {
        "instrument_id": inst,
        "captured_at": "2026-01-01T00:00:00Z",
        "price": 0.55,
    }).data["id"]
    dec = _mcp(home, "decision.add", {
        "type": "actual_enter",
        "instrument_id": inst,
        "thesis_id": thesis,
        "forecast_id": fcst,
        "snapshot_id": old_snap,
        "side": "yes",
        "quantity": 1,
        "price": 0.55,
        "idempotency_key": "00000000-0000-4000-8000-566000000001",
    }).data["id"]
    stale_src = _mcp(home, "source.add", {
        "kind": "url",
        "stance": "supports",
        "uri": "https://example.test/old",
        "freshness_at": "2025-01-01T00:00:00Z",
        "idempotency_key": "00000000-0000-4000-8000-566000000002",
    }).data["id"]
    con_src = _mcp(home, "source.add", {
        "kind": "url",
        "stance": "contradicts",
        "uri": "https://example.test/no",
        "idempotency_key": "00000000-0000-4000-8000-566000000003",
    }).data["id"]
    _mcp(home, "source.attach_to_thesis", {"source_id": stale_src, "target_id": thesis, "idempotency_key": "00000000-0000-4000-8000-566000000004"})
    _mcp(home, "source.attach_to_thesis", {"source_id": con_src, "target_id": thesis, "idempotency_key": "00000000-0000-4000-8000-566000000005"})

    env = _mcp(home, "report.audit_readiness", {"stale_snapshot_threshold_days": 7, "stale_source_threshold_days": 7})
    assert env.ok, env
    data = env.data
    assert data["summary"]["ready"] is False
    by_check = {issue["check"]: issue for issue in data["issues"]}
    assert by_check["missing_resolution_rule_provenance"]["severity"] == "blocking"
    assert by_check["stale_snapshot"]["severity"] == "warning"
    assert by_check["missing_market_microstructure"]["severity"] == "warning"
    assert by_check["stale_source"]["severity"] == "warning"
    assert by_check["contradictory_sources"]["severity"] == "blocking"
    assert dec in by_check["stale_snapshot"]["sample_ids"]["decisions"]
    # Every surfaced issue carries point-of-failure remediation guidance so a
    # caller has an in-surface path to clear a "blocking" count (AX dogfood run 22).
    for issue in data["issues"]:
        assert issue["remediation"], issue["check"]
    # The resolution-rule blocker names the forecast-level remedy explicitly,
    # not just the instrument-level one.
    rr_remediation = by_check["missing_resolution_rule_provenance"]["remediation"]
    assert "forecast.add" in rr_remediation
    assert "resolution_rule_text" in rr_remediation


def _seed_entered_decision(home: Path, idx: int, *, reason: str | None) -> str:
    """Seed one clean (no blocking-check) prediction-market entered decision.

    Uses distinct venue/instrument/thesis/forecast/snapshot per call so
    multiple decisions can be seeded in one journal without id collisions;
    forecast carries resolution_rule_text and the market carries
    resolution_criteria_text so this helper does not itself trip
    missing_resolution_rule_provenance.
    """
    venue = _mcp(home, "venue.add", {"name": f"PM-{idx}", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue,
        "asset_class": "prediction_market",
        "title": f"Will Z-{idx} happen?",
        "resolution_criteria_text": "Resolves per the fixture rule.",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {"instrument_id": inst, "side": "yes", "body": "because"}).data["id"]
    fcst = _mcp(home, "forecast.add", {
        "thesis_id": thesis,
        "kind": "binary",
        "yes_label": "yes",
        "resolution_rule_text": "Resolves per the fixture rule.",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.55},
            {"outcome_label": "no", "probability": 0.45},
        ],
    }).data["id"]
    snap = _mcp(home, "snapshot.add", {
        "instrument_id": inst,
        "captured_at": "2027-02-01T00:00:00Z",
        "price": 0.55,
    }).data["id"]
    dec_args = {
        "type": "paper_enter",
        "instrument_id": inst,
        "thesis_id": thesis,
        "forecast_id": fcst,
        "snapshot_id": snap,
        "side": "yes",
        "quantity": 1,
        "price": 0.55,
        "idempotency_key": f"00000000-0000-4000-8000-56610000{idx:04d}",
    }
    if reason is not None:
        dec_args["reason"] = reason
    return _mcp(home, "decision.add", dec_args).data["id"]


def test_audit_readiness_sample_size_splits_conviction_and_exercise(home: Path):
    """Mixed journal: conviction_sample_size / exercise_sample_size split the
    overall sample_size correctly (trade-trace-u9u1c). Marker: an exercise
    decision's reason starts with 'exercise_trade:'."""
    _seed_entered_decision(home, 1, reason="Conviction thesis entry.")
    _seed_entered_decision(home, 2, reason="exercise_trade: daily plumbing exercise")

    env = _mcp(home, "report.audit_readiness", {})
    assert env.ok, env
    summary = env.data["summary"]
    assert summary["sample_size"] == 2
    assert summary["conviction_sample_size"] == 1
    assert summary["exercise_sample_size"] == 1


def test_audit_readiness_exercise_only_journal_reads_as_plumbing_only(home: Path):
    """An exercise-only journal must read unambiguously as plumbing-only:
    conviction_sample_size == 0 even though sample_size > 0."""
    _seed_entered_decision(home, 1, reason="exercise_trade: daily plumbing exercise")
    _seed_entered_decision(home, 2, reason="exercise_trade: daily plumbing exercise")

    env = _mcp(home, "report.audit_readiness", {})
    assert env.ok, env
    summary = env.data["summary"]
    assert summary["sample_size"] == 2
    assert summary["conviction_sample_size"] == 0
    assert summary["exercise_sample_size"] == 2


def test_audit_readiness_sample_warning_distinguishes_no_trades_yet_from_no_data(home: Path):
    """Regression for trade-trace-nvy9e: a response listing concrete blocking
    findings must never present as sample_size=0/'no_data' -- that reads as
    "nothing to audit" when 18 real findings exist. missing_resolution_rule_
    provenance reads from `forecasts`, a denominator independent of
    sample_size's `decisions` count, so a journal can have zero entered
    decisions yet real blocking findings."""
    venue = _mcp(home, "venue.add", {"name": "PM-nvy9e", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue,
        "asset_class": "prediction_market",
        "title": "Will nvy9e happen?",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {"instrument_id": inst, "side": "yes", "body": "because"}).data["id"]
    # No resolution_criteria_text on the instrument and no resolution_rule_text
    # on the forecast -> missing_resolution_rule_provenance blocking finding.
    # No decision.add call at all -> sample_size (decisions-based) is 0.
    _mcp(home, "forecast.add", {
        "thesis_id": thesis,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.5},
            {"outcome_label": "no", "probability": 0.5},
        ],
    })

    env = _mcp(home, "report.audit_readiness", {})
    assert env.ok, env
    summary = env.data["summary"]
    assert summary["sample_size"] == 0
    assert summary["conviction_sample_size"] == 0
    assert summary["exercise_sample_size"] == 0
    assert summary["blocking_count"] > 0
    # The self-consistency fix: never "no_data" while blocking findings exist.
    assert summary["sample_warning"] != "no_data"
    assert summary["sample_warning"] == "no_trades_yet"
    assert summary["ready"] is False
    by_check = {issue["check"]: issue for issue in env.data["issues"]}
    assert "missing_resolution_rule_provenance" in by_check
    assert by_check["missing_resolution_rule_provenance"]["count"] == summary["blocking_count"]


def test_audit_readiness_ignores_non_prediction_market_entered_decisions(home: Path):
    venue = _mcp(home, "venue.add", {"name": "Broker", "kind": "broker"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue,
        "asset_class": "equity",
        "symbol": "XYZ",
        "title": "XYZ Corp",
    }).data["id"]
    _mcp(home, "decision.add", {
        "type": "actual_enter",
        "instrument_id": inst,
        "side": "long",
        "quantity": 1,
        "price": 10,
        "idempotency_key": "00000000-0000-4000-8000-566000000006",
    })

    env = _mcp(home, "report.audit_readiness", {})
    assert env.ok, env
    assert env.data["summary"]["sample_size"] == 0
    assert env.data["summary"]["sample_warning"] == "no_data"
    assert env.data["issues"] == []


@pytest.mark.parametrize(
    "args,expected_field",
    [
        ({"stale_snapshot_threshold_days": -1}, "stale_snapshot_threshold_days"),
        ({"stale_source_threshold_days": -1}, "stale_source_threshold_days"),
        # Both out of range: the handler validates stale_snapshot first, so it
        # is the field surfaced on the typed error.
        (
            {"stale_snapshot_threshold_days": -1, "stale_source_threshold_days": -1},
            "stale_snapshot_threshold_days",
        ),
        # bool is not a meaningful day count even though isinstance(True, int).
        ({"stale_snapshot_threshold_days": True}, "stale_snapshot_threshold_days"),
        ({"stale_source_threshold_days": True}, "stale_source_threshold_days"),
    ],
)
def test_audit_readiness_rejects_out_of_range_stale_thresholds(
    home: Path, args: dict, expected_field: str,
):
    """Per bead trade-trace-zuyj: `_report_audit_readiness` rejects a
    non-negative-integer stale threshold at the tool layer.

    The schema's `minimum: 0` constraint only fires at the stdio boundary;
    the in-process dispatch path used here reaches the handler guard, so
    these cases exercise the previously test-dead branches and assert the
    typed VALIDATION_ERROR names the failing param."""

    env = _mcp(home, "report.audit_readiness", args)
    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == expected_field
    assert env.error.details["value"] == args[expected_field]


def test_audit_readiness_registered_read_only_schema(home: Path):
    env = _mcp(home, "tool.schema", {"tool": "report.audit_readiness"})
    assert env.ok, env
    tool = env.data
    assert tool["tool"] == "report.audit_readiness"
    assert tool["is_write"] is False
    assert tool["json_schema"]["properties"]["stale_snapshot_threshold_days"]["minimum"] == 0
