"""End-to-end manual ledger flow + per-tool tests per trade-trace-kyr.

Exercises the M1 write surface: venue.add → instrument.add → snapshot.add
→ thesis.add → forecast.add → decision.add → outcome.add (resolved_final)
→ auto-scoring. Plus per-tool happy-path and VALIDATION_ERROR cases for
every M1 write tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call


def _envelope(home: Path, tool: str, args: dict, **kwargs):
    payload = {"home": str(home), **args}
    return mcp_call(tool, payload, actor_id=kwargs.get("actor_id", "agent:default")).model_dump(
        mode="json", exclude_none=True
    )


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


# -- venue.add -----------------------------------------------------------


def test_venue_add_happy(home):
    env = _envelope(home, "venue.add", {"name": "Polymarket", "kind": "prediction_market"})
    assert env["ok"] is True
    assert env["data"]["name"] == "Polymarket"
    assert env["data"]["id"].startswith("ven_")


def test_venue_add_missing_name(home):
    env = _envelope(home, "venue.add", {"kind": "prediction_market"})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "name"


def test_venue_add_invalid_kind(home):
    env = _envelope(home, "venue.add", {"name": "X", "kind": "not_a_kind"})
    assert env["ok"] is False
    # SQLite CHECK constraint surfaces as STORAGE_ERROR via the UnitOfWork.
    # We accept either VALIDATION or STORAGE — the agent gets a typed error.
    assert env["error"]["code"] in ("VALIDATION_ERROR", "STORAGE_ERROR", "INVARIANT_VIOLATION")


# -- instrument.add ------------------------------------------------------


def test_instrument_add_happy(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    env = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Will X happen by 2026-06-30?",
        "currency_or_collateral": "USDC",
    })
    assert env["ok"] is True
    assert env["data"]["title"].startswith("Will X")


def test_instrument_add_missing_title(home):
    env = _envelope(home, "instrument.add", {"venue_id": "v_1", "asset_class": "equity"})
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "title"


# -- snapshot.add --------------------------------------------------------


def test_snapshot_add_happy(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    env = _envelope(home, "snapshot.add", {
        "instrument_id": inst["data"]["id"],
        "captured_at": "2026-05-18T14:00:00Z",
        "price": 0.37,
        "bid": 0.36,
        "ask": 0.39,
    })
    assert env["ok"] is True


def test_snapshot_add_rejects_naive_timestamp(home):
    env = _envelope(home, "snapshot.add", {
        "instrument_id": "i_1",
        "captured_at": "2026-05-18T14:00:00",  # no tz
    })
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "captured_at"


# -- thesis.add ----------------------------------------------------------


def test_thesis_add_happy(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    env = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "Edge in thin-liquidity prediction markets",
        "falsification_criteria": "volume > 100k for 3 consecutive days",
    })
    assert env["ok"] is True
    assert env["data"]["side"] == "yes"


# -- forecast.add (binary invariants) ------------------------------------


def _setup_thesis(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "...",
    })
    return inst["data"]["id"], thesis["data"]["id"]


def test_forecast_add_binary_happy(home):
    _, thesis_id = _setup_thesis(home)
    env = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.48},
            {"outcome_label": "NO", "probability": 0.52},
        ],
    })
    assert env["ok"] is True


def test_forecast_add_binary_invariant_sum(home):
    _, thesis_id = _setup_thesis(home)
    env = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.4},  # sum 0.9, not 1.0
        ],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "INVARIANT_VIOLATION"
    assert "found_sum" in env["error"]["details"]


def test_forecast_add_binary_invariant_count(home):
    _, thesis_id = _setup_thesis(home)
    env = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [{"outcome_label": "YES", "probability": 1.0}],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "INVARIANT_VIOLATION"


def test_forecast_add_binary_invariant_distinct_labels(home):
    _, thesis_id = _setup_thesis(home)
    env = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "yes", "probability": 0.5},  # same after case-fold
        ],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "INVARIANT_VIOLATION"


def test_forecast_add_probability_out_of_range(home):
    _, thesis_id = _setup_thesis(home)
    env = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 1.5},
            {"outcome_label": "NO", "probability": -0.5},
        ],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "INVARIANT_VIOLATION"


# -- decision.add (required-field matrix) --------------------------------


def test_decision_add_skip_requires_reason(home):
    inst_id, _ = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "type": "skip",
        # missing reason
    })
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "reason"


def test_decision_add_skip_forbids_quantity(home):
    inst_id, _ = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "type": "skip",
        "reason": "spread too wide",
        "quantity": 100,
    })
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "quantity"
    assert env["error"]["details"]["decision_type"] == "skip"


def test_decision_add_paper_enter_full(home):
    inst_id, thesis_id = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "thesis_id": thesis_id,
        "type": "paper_enter",
        "side": "long",
        "quantity": 100,
        "price": 0.37,
        "tags": ["liquidity-ignored", "good-skip"],
    })
    assert env["ok"] is True
    assert env["data"]["tags"] == ["good-skip", "liquidity-ignored"]


def test_decision_add_review_requires_review_by(home):
    inst_id, _ = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "type": "review",
    })
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "review_by"


def test_decision_add_unknown_type_rejected(home):
    inst_id, _ = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "type": "not_a_type",
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


# -- outcome.add / resolve.record alias ----------------------------------


def test_outcome_add_creates_row(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    env = _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "YES",
        "outcome_value": 1.0,
        "status": "resolved_final",
    })
    assert env["ok"] is True
    assert env["data"]["status"] == "resolved_final"


def test_resolve_record_is_alias_for_outcome_add(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    env = _envelope(home, "resolve.record", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "NO",
        "status": "void",
    })
    assert env["ok"] is True
    assert env["meta"]["tool"] == "resolve.record"


# -- source.add + source.attach_to_thesis --------------------------------


def test_source_add_and_attach(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "...",
    })
    source = _envelope(home, "source.add", {
        "kind": "research_doc",
        "title": "Liquidity profile of thin PM markets",
        "stance": "supports",
        "summary": "ADV<$5K markets show 40bps wider spreads near resolution",
    })
    attach = _envelope(home, "source.attach_to_thesis", {
        "source_id": source["data"]["id"],
        "target_id": thesis["data"]["id"],
    })
    assert attach["ok"] is True
    assert attach["data"]["edge_type"] == "supports"


def test_source_attach_to_memory_node_m3_functional(home):
    """source.attach_to_memory_node became functional with M3 (bead s3f);
    the M1-era UNSUPPORTED_CAPABILITY stub was replaced by the shared
    attacher factory. With non-existent source + memory_node ids, the
    attacher returns NOT_FOUND (source validated first)."""

    env = _envelope(home, "source.attach_to_memory_node", {
        "source_id": "s_does_not_exist",
        "target_id": "mem_does_not_exist",
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "NOT_FOUND"
    assert env["error"]["details"]["entity_kind"] == "source"


# -- resolve.pending -----------------------------------------------------


def test_resolve_pending_lists_unresolved(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "...",
    })
    _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"],
        "kind": "binary",
        "resolution_at": "2026-06-30T00:00:00Z",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.6},
            {"outcome_label": "NO", "probability": 0.4},
        ],
    })
    env = _envelope(home, "resolve.pending", {})
    assert env["ok"] is True
    assert env["data"]["count"] >= 1
    assert all("resolution_at" in item for item in env["data"]["items"])


def test_resolve_pending_limit_validation(home):
    env = _envelope(home, "resolve.pending", {"limit": 2000})
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "limit"


# -- forecast.supersede --------------------------------------------------


def test_forecast_supersede_writes_edge(home):
    _, thesis_id = _setup_thesis(home)
    first = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.5},
        ],
    })
    sup = _envelope(home, "forecast.supersede", {
        "prior_forecast_id": first["data"]["id"],
        "kind": "binary",
        "yes_label": "YES",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.7},
            {"outcome_label": "NO", "probability": 0.3},
        ],
    })
    assert sup["ok"] is True
    assert sup["data"]["supersedes_prior_forecast_id"] == first["data"]["id"]


# -- end-to-end manual flow ----------------------------------------------


def test_manual_end_to_end_auto_scores(home):
    """The full M1 vertical: instrument → snapshot → thesis → forecast →
    decision → outcome (resolved_final) → forecast_scores row appears."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Will X happen by 2026-06-30?",
    })
    snap = _envelope(home, "snapshot.add", {
        "instrument_id": inst["data"]["id"],
        "captured_at": "2026-05-18T14:00:00Z",
        "price": 0.37,
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "Edge in thin-liquidity PM",
    })
    forecast = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"],
        "kind": "binary",
        "resolution_at": "2026-06-30T00:00:00Z",
        "yes_label": "YES",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.6},
            {"outcome_label": "NO", "probability": 0.4},
        ],
    })
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"],
        "thesis_id": thesis["data"]["id"],
        "forecast_id": forecast["data"]["id"],
        "snapshot_id": snap["data"]["id"],
        "type": "paper_enter",
        "side": "yes",
        "quantity": 100,
        "price": 0.37,
    })
    outcome = _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "YES",
        "outcome_value": 1.0,
        "status": "resolved_final",
    })
    assert outcome["ok"] is True
    # Auto-scoring should have fired.
    scored = outcome["data"]["auto_scored_forecasts"]
    assert len(scored) == 1
    record = scored[0]
    assert record["forecast_id"] == forecast["data"]["id"]
    assert record["failure_reason"] is None
    # YES probability was 0.6, outcome resolved YES; brier = (0.6-1)^2 = 0.16
    assert abs(record["score"] - 0.16) < 1e-9


def test_outcome_provisional_does_not_autoscore(home):
    """Per scoring.md §5 hard invariant: status != 'resolved_final' must
    leave forecast pending."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "...",
    })
    _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"],
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.5},
        ],
    })
    out = _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "YES",
        "status": "resolved_provisional",
    })
    assert out["ok"] is True
    assert out["data"]["auto_scored_forecasts"] == []


def test_no_credential_args_accepted(home):
    """No tool surface accepts trading credentials. Inserting credential-
    shaped fields into any write tool's args either silently ignores them
    or surfaces no error path that allows credential storage."""

    venue = _envelope(home, "venue.add", {
        "name": "PM",
        "kind": "prediction_market",
        "api_key": "sk-leaky-key-PLEASE-NEVER-PERSIST",
        "wallet_seed": "twelve word mnemonic that should be rejected",
        "broker_token": "live-trading-token",
    })
    # The write succeeds because none of these are real tool args; they're
    # silently ignored. The point is: no schema PATH accepts them.
    assert venue["ok"] is True
    # Confirm nothing crept into the DB metadata_json or any other column.
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(home), create_parent=False)
    try:
        cur = db.connection.execute(
            "SELECT metadata_json FROM venues WHERE id = ?", (venue["data"]["id"],)
        )
        row = cur.fetchone()
        meta = json.loads(row[0])
        assert "api_key" not in meta
        assert "wallet_seed" not in meta
        assert "broker_token" not in meta
    finally:
        db.close()
