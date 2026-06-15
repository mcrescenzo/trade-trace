from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _seed_market(home: Path, *, mechanism: str = "clob", state: str = "resolved") -> str:
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})["data"]["id"]
    inst = _envelope(
        home,
        "instrument.add",
        {"venue_id": venue, "asset_class": "prediction_market", "title": "Will X happen?"},
    )["data"]["id"]
    _envelope(
        home,
        "market.bind",
        {
            "id": inst,
            "source": "polymarket",
            "external_id": f"ext-{inst}",
            "title": "Will X happen?",
            "state": state,
            "mechanism": mechanism,
            "bound_via": "manual",
            "opened_at": "2027-01-01T00:00:00Z",
            "close_at": "2027-01-10T00:00:00Z",
            "closed_for_trading_at": "2027-01-10T00:00:00Z",
            "resolving_at": "2027-01-11T00:00:00Z",
            "resolved_at": "2027-01-12T00:00:00Z" if state == "resolved" else None,
            "voided_at": "2027-01-12T00:00:00Z" if state == "voided" else None,
            "ambiguous_at": "2027-01-12T00:00:00Z" if state == "ambiguous" else None,
        },
    )
    return inst


def _seed_scored_forecast(home: Path, market_id: str, *, probability: float = 0.7) -> str:
    thesis = _envelope(home, "thesis.add", {"instrument_id": market_id, "side": "yes", "body": "local test thesis"})["data"]["id"]
    forecast = _envelope(
        home,
        "forecast.add",
        {
            "thesis_id": thesis,
            "kind": "binary",
            "yes_label": "yes",
            "resolution_at": "2027-01-12T00:00:00Z",
            "outcomes": [
                {"outcome_label": "yes", "probability": probability},
                {"outcome_label": "no", "probability": 1.0 - probability},
            ],
        },
    )["data"]["id"]
    _envelope(
        home,
        "resolution.add",
        {
            "instrument_id": market_id,
            "resolved_at": "2027-01-12T00:00:00Z",
            "outcome_label": "yes",
            "status": "resolved_final",
            "confidence": 0.99,
        },
    )
    return forecast


def test_pm_native_report_tools_registered():
    registry = default_registry()
    public = set(registry.public_names())
    assert "report.time_decay_sharpening" in public
    # market_lifecycle / resolution_quality were unfrozen into the Phase-1
    # public catalog (trade-trace-y0cr): both read only Phase-1 tables and
    # carry no Phase-2 dependency, so they ship in the default catalog view.
    assert {"report.market_lifecycle", "report.resolution_quality"}.issubset(public)


def test_market_lifecycle_reports_state_durations(home: Path):
    market_id = _seed_market(home)

    env = _envelope(home, "report.market_lifecycle", {})

    assert env["ok"] is True
    data = env["data"]
    assert data["summary"]["metrics"]["market_count"] == 1
    assert data["summary"]["metrics"]["state_counts"] == {"resolved": 1}
    group = data["groups"][0]
    assert group["key"] == market_id
    assert group["metrics"]["open_to_terminal_hours"] == pytest.approx(264.0)


def test_market_lifecycle_reports_event_market_outcome_grouping_and_rule_provenance(home: Path):
    market_id = _seed_market(home)
    metadata = {
        "polymarket_identity": {"outcome_token_ids_by_label": {"yes": "yes-token", "no": "no-token"}},
        "event_grouping": {"event_id": "evt-1", "event_slug": "event-one", "event_title": "Event One"},
        "resolution_rule": {"text": "Public rule", "source": "market_contract", "provenance": "caller_supplied"},
    }
    _envelope(home, "market.bind", {"source": "polymarket", "external_id": f"ext-{market_id}", "state": "resolved", "mechanism": "clob"})
    db = home / "trade-trace.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE markets SET metadata_json=? WHERE id=?", (json.dumps(metadata), market_id))

    env = _envelope(home, "report.market_lifecycle", {})

    metrics = env["data"]["summary"]["metrics"]
    assert metrics["event_groupings"] == [
        {
            "event_id": "evt-1",
            "event_slug": "event-one",
            "event_title": "Event One",
            "market_count": 1,
            "markets": [market_id],
            "resolution_rule_provenance": {"caller_supplied": 1},
        }
    ]
    assert metrics["outcome_token_mappings"] == [
        {
            "market_id": market_id,
            "event_id": "evt-1",
            "outcome_token_ids_by_label": {"yes": "yes-token", "no": "no-token"},
            "resolution_rule": {"text": "Public rule", "source": "market_contract", "provenance": "caller_supplied"},
        }
    ]
    assert env["data"]["groups"][0]["market"]["event_grouping"]["event_id"] == "evt-1"


def test_resolution_quality_counts_ambiguous_like_statuses(home: Path):
    market_id = _seed_market(home, state="ambiguous")
    _envelope(
        home,
        "decision.add",
        {"instrument_id": market_id, "type": "review", "review_by": "2027-01-11T00:00:00Z", "reason": "uncertain / ambiguous market rules"},
    )
    _envelope(
        home,
        "resolution.add",
        {
            "instrument_id": market_id,
            "resolved_at": "2027-01-12T00:00:00Z",
            "outcome_label": "yes",
            "status": "ambiguous",
        },
    )

    env = _envelope(home, "report.resolution_quality", {})

    assert env["ok"] is True
    metrics = env["data"]["summary"]["metrics"]
    assert metrics["status_counts"] == {"ambiguous": 1}
    assert metrics["ambiguous_void_disputed_cancelled_count"] == 1
    assert env["data"]["groups"][0]["metrics"]["pre_resolution_uncertainty_flag_count"] == 1


def test_time_decay_report_buckets_scored_forecasts(home: Path):
    market_id = _seed_market(home)
    _seed_scored_forecast(home, market_id, probability=0.8)

    decay = _envelope(home, "report.time_decay_sharpening", {"min_sample": 1})

    assert decay["ok"] is True
    assert decay["data"]["summary"]["sample_size"] == 1
    assert decay["data"]["bin_policy"] == "equal_mass"


def test_terminal_calibration_uses_set_based_latest_snapshot_query():
    source = Path("src/trade_trace/reports/calibration.py").read_text(encoding="utf-8")
    assert "ROW_NUMBER() OVER" in source
    assert "terminal_candidates" in source
    assert "WHERE fs.id = ?" not in source
