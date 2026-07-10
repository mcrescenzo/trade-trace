from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.contracts.envelope import dump_envelope
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    init = mcp_call("journal.init", {"home": str(h)})
    assert init.ok, init
    return h


def _call(home: Path, args: dict | None = None) -> dict:
    env = mcp_call("report.current_exposure", {"home": str(home), **(args or {})})
    return dump_envelope(env)


def _assert_boundary(data: dict) -> None:
    for field in (
        "local_evidence_only",
        "non_executing",
        "credential_blind",
        "advice_free",
        "no_live_execution_claims",
        "no_settlement_or_redemption_claims",
        "not_broker_truth",
    ):
        assert data[field] is True
    caveat = data["boundary_caveat"].lower()
    for phrase in ("local journal/projection", "not broker/imported account truth", "live execution", "settlement", "redemption", "advice"):
        assert phrase in caveat


def _instrument(home: Path) -> str:
    venue = dump_envelope(mcp_call("venue.add", {"home": str(home), "name": "Test", "kind": "prediction_market"}))
    assert venue["ok"] is True, venue
    inst = dump_envelope(mcp_call(
        "instrument.add",
        {"home": str(home), "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "Will X happen?"},
    ))
    assert inst["ok"] is True, inst
    return inst["data"]["id"]


def _strategy(home: Path, slug: str) -> str:
    strategy = dump_envelope(mcp_call(
        "strategy.upsert",
        {"home": str(home), "name": slug, "slug": slug, "idempotency_key": f"test-{slug}"},
    ))
    assert strategy["ok"] is True, strategy
    return strategy["data"]["id"]


def _insert_decision(
    home: Path,
    *,
    decision_id: str,
    instrument_id: str,
    type_: str,
    created_at: str,
    reason: str = "recent note",
    strategy_id: str | None = None,
) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            """
            INSERT INTO decisions(
                id, instrument_id, type, side, quantity, price, reason,
                run_id, metadata_json, created_at, actor_id, strategy_id
            ) VALUES (?, ?, ?, 'yes', 1.0, 0.42, ?, 'run_current', '{}', ?, 'agent:test', ?)
            """,
            (decision_id, instrument_id, type_, reason, created_at, strategy_id),
        )
        db.connection.commit()
    finally:
        db.close()


def _insert_position(
    home: Path,
    *,
    instrument_id: str,
    position_id: str,
    decision_id: str,
    side: str = "yes",
    quantity: float = 1.0,
    initial_risk_amount: float = 10.0,
) -> None:
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            """
            INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, closed_at,
                                  resolved_at, realized_pnl, unrealized_pnl, avg_entry_price,
                                  updated_at, initial_risk_amount)
            VALUES (?, ?, 'paper', ?, 'open', '2026-05-20T00:00:00Z', NULL,
                    NULL, NULL, NULL, 0.42, '2026-05-20T00:00:00Z', ?)
            """,
            (position_id, instrument_id, side, initial_risk_amount),
        )
        db.connection.execute(
            """
            INSERT INTO position_events(id, position_id, instrument_id, decision_id, event_type,
                                        quantity_delta, price, fees, slippage, metadata_json, created_at, actor_id)
            VALUES (?, ?, ?, ?, 'open', ?, 0.42, 0.0, 0.0, '{}', '2026-05-20T00:00:00Z', 'agent:test')
            """,
            (f"pe_current_open_{position_id}", position_id, instrument_id, decision_id, quantity),
        )
        db.connection.commit()
    finally:
        db.close()


def test_current_exposure_clean_empty_is_positive(home: Path) -> None:
    body = _call(home)

    assert body["ok"] is True
    data = body["data"]
    assert data["summary"]["bucket"] == "current_exposure"
    assert data["summary"]["buckets"] == ["open_positions", "event_exposure_sets", "watchlist", "recent_trade_activity", "projection_anomalies"]
    for bucket in data["summary"]["buckets"]:
        assert bucket in data
    assert "anomalies" not in data
    assert data["event_exposure_sets"] == []
    assert data["lower_level_reports"]["projection_anomalies"] == "report.exposure_anomalies"
    assert data["summary"]["open_position_count"] == 0
    assert data["summary"]["watch_count"] == 0
    assert data["summary"]["recent_trade_decision_count"] == 0
    assert data["summary"]["anomaly_count"] == 0
    assert data["open_positions"] == []
    assert data["watchlist"] == []
    assert data["recent_trade_activity"] == []
    assert data["projection_anomalies"] == []
    assert any("No watch ideas" in hint for hint in data["agent_answer_hints"])
    _assert_boundary(data)


def test_current_exposure_omitted_as_of_surfaces_effective_timestamp_in_summary_and_meta(home: Path) -> None:
    current = _call(home)

    assert current["ok"] is True
    current_as_of = current["data"]["summary"]["filter"]["as_of"]
    assert current_as_of is not None
    assert current_as_of.endswith("Z")
    assert current["meta"]["normalized_filter"]["as_of"] == current_as_of


def test_current_exposure_explicit_as_of_preserved_in_summary_and_meta(home: Path) -> None:
    as_of = "2026-05-25T12:34:56Z"
    normalized_as_of = "2026-05-25T12:34:56.000Z"

    current = _call(home, {"as_of": as_of})
    assert current["ok"] is True
    assert current["data"]["summary"]["filter"]["as_of"] == normalized_as_of
    assert current["meta"]["normalized_filter"]["as_of"] == normalized_as_of


def test_current_exposure_combines_open_watch_recent_and_anomalies(home: Path) -> None:
    instrument_id = _instrument(home)
    watch = dump_envelope(mcp_call("decision.add", {
        "home": str(home), "instrument_id": instrument_id, "type": "watch",
        "reason": "watch this idea", "review_by": "2026-05-01T00:00:00Z",
    }))
    assert watch["ok"] is True, watch
    _insert_decision(home, decision_id="dec_open_current", instrument_id=instrument_id, type_="paper_enter", created_at="2026-05-20T00:00:00Z")
    _insert_position(home, instrument_id=instrument_id, position_id="pos_current", decision_id="dec_open_current")
    _insert_decision(home, decision_id="dec_record_only_current", instrument_id=instrument_id, type_="actual_enter", created_at="2026-05-21T00:00:00Z", reason="record-only actual note")

    body = _call(home, {"recent_limit": 5})

    assert body["ok"] is True
    data = body["data"]
    assert data["summary"]["open_position_count"] == 1
    assert data["summary"]["watch_count"] == 1
    assert data["summary"]["recent_trade_decision_count"] == 2
    assert data["summary"]["anomaly_count"] >= 1
    assert data["open_positions"][0]["position_id"] == "pos_current"
    assert data["watchlist"][0]["decision_id"] == watch["data"]["id"]
    assert data["watchlist"][0]["caveat_codes"] == ["WATCH_ONLY_IDEA"]
    recent = {row["decision_id"]: row for row in data["recent_trade_activity"]}
    assert recent["dec_record_only_current"]["instrument_id"] == instrument_id
    assert recent["dec_record_only_current"]["strategy_id"] is None
    assert recent["dec_record_only_current"]["run_id"] == "run_current"
    assert "RECORD_ONLY_ACTUAL" in recent["dec_record_only_current"]["caveat_codes"]
    assert any(row["code"] == "RECORD_ONLY_ACTUAL" for row in data["projection_anomalies"])
    assert any("Recent trade activity" in hint for hint in data["agent_answer_hints"])


def test_current_exposure_surfaces_fragmented_same_side_anomaly(home: Path) -> None:
    # trade-trace-scx8: two open same-side paper positions on one instrument
    # (the cross-run fragmentation hazard) surface through the composed
    # projection_anomalies bucket as FRAGMENTED_SAME_SIDE_EXPOSURE.
    instrument_id = _instrument(home)
    _insert_decision(home, decision_id="dec_frag_1", instrument_id=instrument_id, type_="paper_enter", created_at="2026-05-20T00:00:00Z")
    _insert_decision(home, decision_id="dec_frag_2", instrument_id=instrument_id, type_="paper_enter", created_at="2026-05-21T00:00:00Z")
    _insert_position(home, instrument_id=instrument_id, position_id="pos_frag_1", decision_id="dec_frag_1", side="yes")
    _insert_position(home, instrument_id=instrument_id, position_id="pos_frag_2", decision_id="dec_frag_2", side="yes")

    body = _call(home)

    assert body["ok"] is True, body
    frag = [r for r in body["data"]["projection_anomalies"] if r["code"] == "FRAGMENTED_SAME_SIDE_EXPOSURE"]
    assert len(frag) == 1, frag
    assert frag[0]["evidence"]["open_position_count"] == 2
    assert set(frag[0]["affected_ids"]["positions"]) == {"pos_frag_1", "pos_frag_2"}


def test_current_exposure_recent_without_open_positions_warns_not_exposure(home: Path) -> None:
    instrument_id = _instrument(home)
    _insert_decision(home, decision_id="dec_recent_only", instrument_id=instrument_id, type_="actual_enter", created_at="2026-05-21T00:00:00Z")

    body = _call(home, {"include_watchlist": False, "include_anomalies": False})

    assert body["data"]["summary"]["open_position_count"] == 0
    assert body["data"]["summary"]["recent_trade_decision_count"] == 1
    assert body["data"]["watchlist"] == []
    assert body["data"]["projection_anomalies"] == []
    assert "Canonical open positions: zero; recent journal entries exist but are not open exposure." in body["data"]["agent_answer_hints"]


def test_current_exposure_filters_scope_child_buckets(home: Path) -> None:
    in_scope = _instrument(home)
    out_scope = _instrument(home)
    keep_strategy = _strategy(home, "strat-keep")
    other_strategy = _strategy(home, "strat-other")
    _insert_decision(
        home,
        decision_id="watch_in_scope",
        instrument_id=in_scope,
        type_="watch",
        created_at="2026-05-19T00:00:00Z",
        reason="watch in scope",
        strategy_id=keep_strategy,
    )
    _insert_decision(
        home,
        decision_id="watch_out_scope",
        instrument_id=out_scope,
        type_="watch",
        created_at="2026-05-19T00:01:00Z",
        reason="watch out of scope",
        strategy_id=other_strategy,
    )
    _insert_decision(
        home,
        decision_id="recent_in_scope",
        instrument_id=in_scope,
        type_="paper_enter",
        created_at="2026-05-20T00:00:00Z",
        strategy_id=keep_strategy,
    )
    _insert_decision(
        home,
        decision_id="recent_out_scope",
        instrument_id=out_scope,
        type_="actual_enter",
        created_at="2026-05-21T00:00:00Z",
        reason="record-only out of scope",
        strategy_id=other_strategy,
    )
    _insert_decision(
        home,
        decision_id="anomaly_in_scope",
        instrument_id=in_scope,
        type_="paper_enter",
        created_at="2026-05-21T00:01:00Z",
        strategy_id=keep_strategy,
    )

    scoped = _call(home, {"instrument_id": in_scope, "strategy_id": keep_strategy, "recent_limit": 10})

    assert scoped["ok"] is True
    scoped_data = scoped["data"]
    assert scoped_data["summary"]["filter"]["instrument_id"] == in_scope
    assert scoped_data["summary"]["filter"]["strategy_id"] == keep_strategy
    assert {row["decision_id"] for row in scoped_data["watchlist"]} == {"watch_in_scope"}
    assert scoped_data["summary"]["watch_count"] == 1
    assert "watch_out_scope" not in {row["decision_id"] for row in scoped_data["watchlist"]}
    assert {row["decision_id"] for row in scoped_data["recent_trade_activity"]} == {
        "anomaly_in_scope",
        "recent_in_scope",
    }
    assert scoped_data["summary"]["recent_trade_decision_count"] == 2
    assert all(
        row["instrument_id"] == in_scope and row["strategy_id"] == keep_strategy
        for row in scoped_data["recent_trade_activity"]
    )
    scoped_anomaly_decisions = {
        decision_id
        for row in scoped_data["projection_anomalies"]
        for decision_id in row["affected_ids"].get("decisions", [])
    }
    assert "anomaly_in_scope" in scoped_anomaly_decisions
    assert "recent_out_scope" not in scoped_anomaly_decisions
    assert all(in_scope in row["affected_ids"].get("instruments", []) for row in scoped_data["projection_anomalies"])
    assert scoped_data["summary"]["anomaly_count"] == len(scoped_data["projection_anomalies"])

    kind_scoped = _call(
        home,
        {"instrument_id": in_scope, "strategy_id": keep_strategy, "kind": "paper", "recent_limit": 10},
    )

    assert kind_scoped["ok"] is True
    kind_data = kind_scoped["data"]
    assert kind_data["summary"]["filter"]["kind"] == "paper"
    assert kind_data["watchlist"] == []
    assert kind_data["summary"]["watch_count"] == 0
    assert {row["decision_id"] for row in kind_data["recent_trade_activity"]} == {
        "anomaly_in_scope",
        "recent_in_scope",
    }
    assert all(row["type"] == "paper_enter" for row in kind_data["recent_trade_activity"])
    kind_anomaly_decisions = {
        decision_id
        for row in kind_data["projection_anomalies"]
        for decision_id in row["affected_ids"].get("decisions", [])
    }
    assert "anomaly_in_scope" in kind_anomaly_decisions
    assert "recent_out_scope" not in kind_anomaly_decisions


def test_current_exposure_limit_surfaces_truncation_and_cursor_pages_remainder(home: Path) -> None:
    # Three open positions, one per instrument. A limited current_exposure call
    # must NOT silently drop the rows beyond the page: it has to surface
    # truncated=true + a next_cursor (mirroring report.open_positions), and that
    # cursor must page the remaining exposure. Regression for trade-trace-lszg
    # (AX-034): current_exposure previously discarded open_positions' truncated/
    # next_cursor, so a bot under-read its own exposure with no signal.
    ids = ["a", "b", "c"]
    for tag in ids:
        instrument_id = _instrument(home)
        _insert_decision(
            home,
            decision_id=f"dec_open_{tag}",
            instrument_id=instrument_id,
            type_="paper_enter",
            created_at="2026-05-20T00:00:00Z",
        )
        _insert_position(
            home,
            instrument_id=instrument_id,
            position_id=f"pos_trunc_{tag}",
            decision_id=f"dec_open_{tag}",
        )

    page1 = _call(home, {"limit": 2})
    assert page1["ok"] is True, page1
    data1 = page1["data"]
    assert len(data1["open_positions"]) == 2
    assert data1["truncated"] is True
    assert data1["next_cursor"], "limited current_exposure must surface a next_cursor"

    page2 = _call(home, {"limit": 2, "cursor": data1["next_cursor"]})
    assert page2["ok"] is True, page2
    data2 = page2["data"]
    assert len(data2["open_positions"]) == 1
    assert data2["truncated"] is False
    assert data2["next_cursor"] is None

    seen = {row["position_id"] for row in data1["open_positions"]} | {
        row["position_id"] for row in data2["open_positions"]
    }
    assert seen == {"pos_trunc_a", "pos_trunc_b", "pos_trunc_c"}


def test_current_exposure_default_no_limit_call_is_bounded_by_transport_default(home: Path) -> None:
    # The documented default exposure call (no limit) must NOT page the full
    # open-position set: open-position rows are heavy (each embeds two 78-digit
    # CLOB token IDs), so the old 100-row default overflowed the MCP token cap
    # once positions accumulated (trade-trace-lszg / AX-034 observed ~69KB at
    # N=9). The default call is now bounded to the small transport default and
    # signals truncated=true + a next_cursor so callers can walk the rest.
    from trade_trace.reports.tool_handlers.portfolio_exposure import (
        OPEN_POSITIONS_TRANSPORT_DEFAULT_LIMIT,
    )

    seeded = OPEN_POSITIONS_TRANSPORT_DEFAULT_LIMIT + 1
    for idx in range(seeded):
        instrument_id = _instrument(home)
        _insert_decision(
            home,
            decision_id=f"dec_default_{idx}",
            instrument_id=instrument_id,
            type_="paper_enter",
            created_at="2026-05-20T00:00:00Z",
        )
        _insert_position(
            home,
            instrument_id=instrument_id,
            position_id=f"pos_default_{idx}",
            decision_id=f"dec_default_{idx}",
        )

    body = _call(home)
    assert body["ok"] is True, body
    data = body["data"]
    assert len(data["open_positions"]) == OPEN_POSITIONS_TRANSPORT_DEFAULT_LIMIT
    assert data["summary"]["filter"]["limit"] == OPEN_POSITIONS_TRANSPORT_DEFAULT_LIMIT
    assert data["truncated"] is True
    assert data["next_cursor"], "bounded default exposure call must page the rest via next_cursor"


def test_current_exposure_schema_advertises_limit_and_cursor() -> None:
    reg = __import__("trade_trace.core", fromlist=["default_registry"]).default_registry()
    registration = reg.get("report.current_exposure")
    props = registration.json_schema.get("properties", {})
    assert "limit" in props, "current_exposure must advertise limit so pagination is discoverable"
    assert "cursor" in props, "current_exposure must advertise cursor for safe paging"


def test_current_exposure_schema_mentions_recommended_packet() -> None:
    reg = __import__("trade_trace.core", fromlist=["default_registry"]).default_registry()
    registration = reg.get("report.current_exposure")

    assert registration.json_schema is not None
    text = (registration.description + " " + registration.json_schema.get("description", "")).lower()
    for phrase in ("recommended trader-agent entry point", "open_positions", "watchlist", "recent_trade_activity", "projection_anomalies"):
        assert phrase in text
    for phrase in ("not assert broker/imported account truth", "live execution", "settlement/redemption", "advice"):
        assert phrase in text


def _bind_market_metadata(home: Path, *, instrument_id: str, external_id: str, outcome_label: str) -> None:
    import json

    db = open_database(db_path(home), create_parent=False)
    try:
        metadata = {
            "polymarket_identity": {
                "gamma_event_id": "evt-2026",
                "gamma_market_id": external_id,
                "event_slug": "event-2026",
                "market_slug": f"market-{outcome_label.lower()}",
                "outcome_token_ids_by_label": {outcome_label: f"tok-{outcome_label.lower()}"},
            },
            "event_grouping": {
                "event_id": "evt-2026",
                "event_slug": "event-2026",
                "event_title": "Mutually exclusive event",
                "mutually_exclusive": True,
            },
            "negative_risk": {"enabled": True, "provenance": "caller_supplied_fixture"},
        }
        db.connection.execute(
            """
            INSERT INTO markets(id, source, external_id, title, state, mechanism, bound_via,
                                venue_metadata_json, metadata_json, created_at, actor_id)
            VALUES (?, 'polymarket', ?, ?, 'open', 'clob', 'manual', '{}', ?, '2026-05-19T00:00:00Z', 'agent:test')
            """,
            (instrument_id, external_id, f"Outcome {outcome_label}", json.dumps(metadata)),
        )
        db.connection.commit()
    finally:
        db.close()


def test_current_exposure_event_sets_net_mutually_exclusive_negative_risk_without_conversion(home: Path) -> None:
    yes_instr = _instrument(home)
    venue = dump_envelope(mcp_call("venue.add", {"home": str(home), "name": "Test 2", "kind": "prediction_market"}))
    assert venue["ok"] is True, venue
    inst = dump_envelope(mcp_call(
        "instrument.add",
        {"home": str(home), "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "Will Y happen?"},
    ))
    assert inst["ok"] is True, inst
    no_instr = inst["data"]["id"]
    _bind_market_metadata(home, instrument_id=yes_instr, external_id="pm-yes", outcome_label="YES")
    _bind_market_metadata(home, instrument_id=no_instr, external_id="pm-no", outcome_label="NO")
    _insert_decision(home, decision_id="dec_evt_yes", instrument_id=yes_instr, type_="paper_enter", created_at="2026-05-20T00:00:00Z")
    _insert_position(home, instrument_id=yes_instr, position_id="pos_evt_yes", decision_id="dec_evt_yes")
    _insert_decision(home, decision_id="dec_evt_no", instrument_id=no_instr, type_="paper_enter", created_at="2026-05-20T00:01:00Z")
    _insert_position(home, instrument_id=no_instr, position_id="pos_evt_no", decision_id="dec_evt_no")

    body = _call(home)

    assert body["ok"] is True, body
    event_sets = body["data"]["event_exposure_sets"]
    assert len(event_sets) == 1
    event = event_sets[0]
    assert event["event_id"] == "evt-2026"
    assert event["mutually_exclusive"] is True
    assert "event_level_net_exposure" not in event
    summary = event["event_level_directional_summary"]
    assert summary["raw_market_gross_quantity"] == 2.0
    assert summary["directional_net_quantity"] == 2.0
    assert summary["conservative_event_risk_amount"] == 20.0
    assert summary["unconverted_negative_risk_caveated"] is True
    assert "no broker/account reconciliation" in summary["metric_caveat"]
    assert {row["position_id"] for row in event["market_level_net_exposure"]} == {"pos_evt_yes", "pos_evt_no"}
    assert {row["outcome_label"] for row in event["market_level_net_exposure"]} == {"YES", "NO"}
    buckets = {(row["outcome_label"], row["side"]): row for row in event["outcome_side_buckets"]}
    assert set(buckets) == {("YES", "yes"), ("NO", "yes")}
    assert buckets[("YES", "yes")]["signed_projected_quantity"] == 1.0
    assert buckets[("NO", "yes")]["signed_projected_quantity"] == 1.0
    assert set(event["contributing_record_ids"]["positions"]) == {"pos_evt_yes", "pos_evt_no"}
    assert set(event["contributing_record_ids"]["decisions"]) == {"dec_evt_yes", "dec_evt_no"}
    assert event["negative_risk"]["flagged"] is True
    assert "NEGATIVE_RISK_EQUIVALENCE_UNCONVERTED" in event["caveat_codes"]
    assert "MUTUALLY_EXCLUSIVE_EVENT_CONCENTRATION_UNCONVERTED" in event["caveat_codes"]
    caveat_text = " ".join(event["negative_risk"]["caveats"]).lower()
    assert "no conversion" in caveat_text
    assert event["truth_label"] == "local_projection_only_not_imported_account_truth"


def test_current_exposure_event_sets_bucket_opposing_sides_and_caveat_not_true_net(home: Path) -> None:
    yes_instr = _instrument(home)
    venue = dump_envelope(mcp_call("venue.add", {"home": str(home), "name": "Test offset", "kind": "prediction_market"}))
    assert venue["ok"] is True, venue
    inst = dump_envelope(mcp_call(
        "instrument.add",
        {"home": str(home), "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "Will offset outcome happen?"},
    ))
    assert inst["ok"] is True, inst
    no_instr = inst["data"]["id"]
    _bind_market_metadata(home, instrument_id=yes_instr, external_id="pm-yes-offset", outcome_label="YES")
    _bind_market_metadata(home, instrument_id=no_instr, external_id="pm-no-offset", outcome_label="NO")
    _insert_decision(home, decision_id="dec_evt_yes_long", instrument_id=yes_instr, type_="paper_enter", created_at="2026-05-20T00:00:00Z")
    _insert_position(home, instrument_id=yes_instr, position_id="pos_evt_yes_long", decision_id="dec_evt_yes_long", side="yes")
    _insert_decision(home, decision_id="dec_evt_yes_no", instrument_id=yes_instr, type_="paper_enter", created_at="2026-05-20T00:01:00Z")
    _insert_position(home, instrument_id=yes_instr, position_id="pos_evt_yes_no", decision_id="dec_evt_yes_no", side="no")
    _insert_decision(home, decision_id="dec_evt_no_long", instrument_id=no_instr, type_="paper_enter", created_at="2026-05-20T00:02:00Z")
    _insert_position(home, instrument_id=no_instr, position_id="pos_evt_no_long", decision_id="dec_evt_no_long", side="yes")

    body = _call(home)

    assert body["ok"] is True, body
    event = body["data"]["event_exposure_sets"][0]
    assert event["mutually_exclusive"] is True
    assert "event_level_net_exposure" not in event
    summary = event["event_level_directional_summary"]
    assert summary["raw_market_gross_quantity"] == 3.0
    assert summary["directional_net_quantity"] == 1.0
    assert summary["conservative_event_risk_amount"] == 30.0
    assert summary["mutually_exclusive_netting_caveated"] is True
    assert summary["unconverted_negative_risk_caveated"] is True
    buckets = {(row["outcome_label"], row["side"]): row for row in event["outcome_side_buckets"]}
    assert set(buckets) == {("YES", "yes"), ("YES", "no"), ("NO", "yes")}
    assert buckets[("YES", "yes")]["signed_projected_quantity"] == 1.0
    assert buckets[("YES", "no")]["signed_projected_quantity"] == -1.0
    assert buckets[("NO", "yes")]["signed_projected_quantity"] == 1.0
    assert "NEGATIVE_RISK_EQUIVALENCE_UNCONVERTED" in event["caveat_codes"]
    assert "MUTUALLY_EXCLUSIVE_EVENT_CONCENTRATION_UNCONVERTED" in event["caveat_codes"]
    assert set(event["contributing_record_ids"]["positions"]) == {
        "pos_evt_yes_long",
        "pos_evt_yes_no",
        "pos_evt_no_long",
    }
