from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from trade_trace.contracts.envelope import dump_envelope
from trade_trace.core import _reset_deterministic_request_id_counter, build_registry, dispatch
from trade_trace.storage.paths import db_path
from trade_trace.tools._helpers import CLOCK_OVERRIDE, reset_deterministic_id_counter

_ANCHOR = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)
_AS_OF = "2026-05-28T12:00:00.000Z"

_PHASE2_LOOP_TOOLS = {
    "risk.policy_version_add",
    "risk.evaluate",
    "risk.check_record",
    "pretrade_intent.record",
    "pretrade_intent.get",
    "pretrade_intent.list",
    "paper_fill.record",
    "paper_fill.get",
    "paper_fill.list",
    "account_snapshot.import",
    "account_snapshot.get",
    "account_snapshot.list",
    "external_receipt.import",
    "external_receipt.get",
    "external_receipt.list",
    "reconciliation.record",
    "reconciliation.get",
    "report.paper_exposure",
    "report.current_exposure",
    "report.reconciliation_mismatches",
}

_ADAPTER_BACKED_POLYMARKET_TOOLS = {
    "market.refresh",
    "market.search",
    "outcome.fetch",
    "snapshot.fetch",
    "snapshot.fetch_series",
}


def _call(home: Path, tool: str, args: dict[str, Any], *, actor_id: str = "agent:phase2") -> dict[str, Any]:
    env = dispatch(tool, {"home": str(home), **args}, actor_id=actor_id)
    body = dump_envelope(env)
    assert body["ok"] is True, body
    return body["data"]


def _deny_network(monkeypatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(f"unexpected network call: args={args!r} kwargs={kwargs!r}")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(httpx.Client, "get", fail)
    monkeypatch.setattr(httpx.Client, "post", fail)


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _assert_no_credential_markers_persisted(home: Path) -> None:
    markers = ("api_key", "private_key", "broker_token", "wallet_secret", "mnemonic")
    conn = sqlite3.connect(db_path(home))
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for table in tables:
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({_q(table)})")]
            for row in conn.execute(f"SELECT * FROM {_q(table)}").fetchall():
                for column, value in zip(columns, row, strict=False):
                    if value is None:
                        continue
                    text = str(value).lower()
                    for marker in markers:
                        assert marker not in text, f"{marker!r} persisted in {table}.{column}"
    finally:
        conn.close()


def _db_summary(home: Path) -> dict[str, Any]:
    conn = sqlite3.connect(db_path(home))
    try:
        return {
            "event_counts": dict(
                conn.execute(
                    "SELECT event_type, COUNT(*) FROM events GROUP BY event_type ORDER BY event_type"
                ).fetchall()
            ),
            "actual_decision_count": conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE type LIKE 'actual_%'"
            ).fetchone()[0],
            "position_kinds": [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT kind FROM positions ORDER BY kind"
                ).fetchall()
            ],
        }
    finally:
        conn.close()


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _run_phase2_paper_loop(home: Path) -> dict[str, Any]:
    reset_deterministic_id_counter()
    _reset_deterministic_request_id_counter()
    token = CLOCK_OVERRIDE.set(_ANCHOR)
    try:
        _call(home, "journal.init", {}, actor_id="agent:init")

        market = _call(
            home,
            "market.bind",
            {
                "source": "polymarket",
                "external_id": "phase2-local-market",
                "state": "open",
                "mechanism": "clob",
                "bound_via": "manual",
                "title": "Phase-2 local fixture market",
                "question": "Will the local fixture remain coherent?",
                "resolution_source": "market_contract",
                "gamma_event_id": "evt-phase2-local",
                "gamma_market_id": "phase2-local-market",
                "event_slug": "phase2-local-fixture",
                "market_slug": "phase2-local-market",
                "condition_id": "condition-phase2-local",
                "outcome_ids_by_label": {"yes": "token-yes", "no": "token-no"},
                "event_grouping": {"event_id": "evt-phase2-local", "event_slug": "phase2-local-fixture"},
                "resolution_rule_text": "Resolve from the local fixture assertion only.",
                "tick_size": 0.01,
                "fee_rate_bps": 0,
                "tradable": True,
                "accepting_orders": True,
                "idempotency_key": "phase2-market-bind",
            },
        )
        market_id = market["market_id"]
        instrument_id = market["instrument_id"]

        snapshot = _call(
            home,
            "snapshot.add",
            {
                "instrument_id": instrument_id,
                "captured_at": _AS_OF,
                "source": "local_fixture",
                "price": 0.42,
                "bid": 0.41,
                "ask": 0.43,
                "mid": 0.42,
                "spread": 0.02,
                "implied_probability": 0.42,
                "liquidity_depth_json": {"yes": [{"price": 0.42, "quantity": 10}]},
                "depth_provenance": "local_fixture",
                "idempotency_key": "phase2-snapshot-add",
            },
        )

        forecast = _call(
            home,
            "forecast.add",
            {
                "market_id": market_id,
                "instrument_id": instrument_id,
                "snapshot_id": snapshot["id"],
                "kind": "binary",
                "yes_label": "yes",
                "outcomes": [
                    {"outcome_label": "yes", "probability": 0.58},
                    {"outcome_label": "no", "probability": 0.42},
                ],
                "rationale_body": "Local fixture forecast context for the paper loop.",
                "resolution_rule_text": "Resolve from the local fixture assertion only.",
                "idempotency_key": "phase2-forecast-add",
            },
        )

        decision = _call(
            home,
            "decision.add",
            {
                "instrument_id": instrument_id,
                "forecast_id": forecast["id"],
                "snapshot_id": snapshot["id"],
                "type": "paper_enter",
                "side": "yes",
                "quantity": 10,
                "price": 0.42,
                "fees": 0.01,
                "declared_risk_amount": 4.2,
                "declared_risk_unit": "USDC",
                "reason": "Deterministic local paper-loop fixture.",
                "idempotency_key": "phase2-decision-paper-enter",
            },
        )

        policy = _call(
            home,
            "risk.policy_version_add",
            {
                "policy_key": "phase2-local-paper",
                "version": "1",
                "limits_json": {"max_notional": 100, "paper_only": True},
                "rules_json": [
                    {
                        "rule_id": "max_notional",
                        "limit_class": "notional",
                        "severity": "hard_block",
                        "threshold": 100,
                    },
                    {
                        "rule_id": "paper_only",
                        "limit_class": "paper_only",
                        "severity": "hard_block",
                        "threshold": True,
                    },
                ],
                "source": "local_fixture",
                "effective_from": _AS_OF,
                "idempotency_key": "phase2-risk-policy",
            },
        )
        proposed_intent = {
            "id": "phase2-proposed-intent-material",
            "market_id": market_id,
            "instrument_id": instrument_id,
            "forecast_id": forecast["id"],
            "decision_id": decision["id"],
            "snapshot_id": snapshot["id"],
            "approval_state": "not_requested",
            "is_paper": True,
            "proposed_shape": {
                "venue_family": "polymarket",
                "side": "yes",
                "quantity": 10,
                "limit_price": 0.43,
                "notional": 4.2,
                "time_in_force": "local_fixture_only",
            },
        }
        risk_inputs = {
            "market": {"spread": 0.02, "stale": False},
            "exposure": {"market_exposure": 4.2, "total_exposure": 4.2},
            "market_input_ids": [snapshot["id"]],
            "exposure_input_ids": [decision["position_id"]],
        }
        risk_eval = _call(
            home,
            "risk.evaluate",
            {
                "policy_version_id": policy["id"],
                "proposed_intent": proposed_intent,
                "snapshots": risk_inputs,
            },
        )
        assert risk_eval["status"] == "pass"
        assert risk_eval["non_executing"] is True

        receipt = _call(
            home,
            "risk.check_record",
            {
                "policy_version_id": policy["id"],
                "status": risk_eval["status"],
                "outcome": risk_eval["outcome"],
                "as_of": _AS_OF,
                "market_id": market_id,
                "instrument_id": instrument_id,
                "snapshot_id": snapshot["id"],
                "proposed_intent_hash": _digest(proposed_intent),
                "rule_results": risk_eval["rule_results"],
                "proposed_intent": proposed_intent,
                "snapshots": risk_inputs,
                "evidence_input_ids_json": [snapshot["id"], forecast["id"], decision["id"]],
                "input_provenance_json": {"mode": "local_fixture"},
                "idempotency_key": "phase2-risk-receipt",
            },
        )
        assert receipt["status"] == "pass"

        intent = _call(
            home,
            "pretrade_intent.record",
            {
                "semantic_key": "phase2:local-paper:intent",
                "market_id": market_id,
                "instrument_id": instrument_id,
                "snapshot_id": snapshot["id"],
                "forecast_id": forecast["id"],
                "decision_id": decision["id"],
                "risk_check_receipt_id": receipt["id"],
                "proposed_shape": proposed_intent["proposed_shape"],
                "risk_budget": {"max_loss": "4.20", "unit": "USDC"},
                "evidence_refs": [
                    {"kind": "snapshot", "id": snapshot["id"]},
                    {"kind": "forecast", "id": forecast["id"]},
                    {"kind": "risk_check_receipt", "id": receipt["id"]},
                ],
                "source_ids": [],
                "as_of": _AS_OF,
                "idempotency_key": "phase2-pretrade-intent",
            },
        )
        assert intent["non_executing"] is True
        assert intent["evaluation"] == {
            "evaluated": True,
            "risk_check_receipt_id": receipt["id"],
            "status": "pass",
        }

        paper_fill = _call(
            home,
            "paper_fill.record",
            {
                "semantic_key": "phase2:local-paper:fill",
                "account_label": "local-paper-fixture",
                "market_id": market_id,
                "instrument_id": instrument_id,
                "pretrade_intent_id": intent["id"],
                "side": "buy",
                "outcome_side": "yes",
                "requested_quantity": 10,
                "limit_price": 0.43,
                "reference_mid_price": 0.42,
                "slippage_cap_bps": 500,
                "fee_amount": 0.01,
                "quote_id": "quote-local-phase2",
                "book_id": "book-local-phase2",
                "snapshot_id": snapshot["id"],
                "snapshot_as_of": _AS_OF,
                "order_as_of": _AS_OF,
                "book_levels": [{"price": 0.42, "quantity": 10}],
                "evidence_json": {"source": "local_fixture"},
                "idempotency_key": "phase2-paper-fill",
            },
        )
        assert paper_fill["fill_status"] == "full"
        assert paper_fill["paper_only"] is True
        assert paper_fill["non_executing"] is True
        assert paper_fill["not_imported_account_truth"] is True

        account_snapshot = _call(
            home,
            "account_snapshot.import",
            {
                "semantic_key": "phase2:local-paper:account-snapshot",
                "source_system": "local_fixture_importer",
                "source_run_id": "phase2-loop",
                "source_precedence": 1,
                "confidence_label": "high",
                "staleness_status": "fresh",
                "environment_label": "paper",
                "account_label": "local-paper-fixture",
                "venue_label": "polymarket-fixture",
                "captured_at": _AS_OF,
                "as_of": _AS_OF,
                "balances": [{"asset": "USDC", "total": "95.79", "available": "95.79"}],
                "positions": [
                    {
                        "instrument_id": instrument_id,
                        "side": "yes",
                        "quantity": "10",
                        "average_price": "0.42",
                    }
                ],
                "fills_trades": [{"external_fill_ref": "fixture-fill-1", "quantity": "10"}],
                "redacted_artifact_ref": "local-fixture://phase2/account-snapshot",
                "idempotency_key": "phase2-account-snapshot",
            },
        )
        assert account_snapshot["non_executing"] is True
        assert account_snapshot["credential_blind"] is True

        receipt_import = _call(
            home,
            "external_receipt.import",
            {
                "semantic_key": "phase2:local-paper:external-receipt",
                "lifecycle_state": "filled",
                "external_event_type": "fill",
                "pretrade_intent_id": intent["id"],
                "market_id": market_id,
                "instrument_id": instrument_id,
                "source_system": "local_fixture_importer",
                "source_run_id": "phase2-loop",
                "as_of": _AS_OF,
                "external_order_ref": "fixture-order-1",
                "external_fill_ref": "fixture-fill-1",
                "sanitized_facts": {
                    "requested_quantity": "10",
                    "filled_quantity": "10",
                    "remaining_quantity": "0",
                    "average_fill_price": "0.42",
                    "fee_amount": "0.01",
                },
                "redacted_artifact_ref": "local-fixture://phase2/external-receipt",
                "idempotency_key": "phase2-external-receipt",
            },
        )
        assert receipt_import["non_executing"] is True
        assert receipt_import["credential_blind"] is True

        paper_exposure = _call(
            home,
            "report.paper_exposure",
            {"account_label": "local-paper-fixture", "as_of": _AS_OF},
        )
        assert paper_exposure["non_executing"] is True
        assert paper_exposure["no_live_execution_claims"] is True

        current_exposure = _call(
            home,
            "report.current_exposure",
            {"as_of": _AS_OF, "recent_limit": 5},
        )
        assert current_exposure["summary"]["open_position_count"] == 1
        assert current_exposure["summary"]["position_truth_caveat"] == "projected_local_positions_not_imported_account_truth"

        reconciliation = _call(
            home,
            "reconciliation.record",
            {
                "semantic_key": "phase2:local-paper:reconciliation",
                "as_of": _AS_OF,
                "idempotency_key": "phase2-reconciliation",
            },
        )
        assert reconciliation["non_executing"] is True
        assert reconciliation["credential_blind"] is True
        assert reconciliation["mismatch_codes"] == []
        assert reconciliation["diff_severity"] == "none"
        assert reconciliation["contributing_ids"]["paper_fills"] == [paper_fill["id"]]
        assert reconciliation["contributing_ids"]["risk_check_receipts"] == [receipt["id"]]

        mismatch_report = _call(home, "report.reconciliation_mismatches", {})
        assert mismatch_report["non_executing"] is True
        assert mismatch_report["credential_blind"] is True
        assert mismatch_report["summary"]["mismatch_codes"] == []

        db_summary = _db_summary(home)
        assert db_summary["actual_decision_count"] == 0
        assert db_summary["position_kinds"] == ["paper"]

        return {
            "ids": {
                "market": market_id,
                "snapshot": snapshot["id"],
                "forecast": forecast["id"],
                "decision": decision["id"],
                "position": decision["position_id"],
                "risk_receipt": receipt["id"],
                "intent": intent["id"],
                "paper_fill": paper_fill["id"],
                "account_snapshot": account_snapshot["id"],
                "external_receipt": receipt_import["id"],
                "reconciliation": reconciliation["id"],
            },
            "risk_status": risk_eval["status"],
            "intent_evaluation": intent["evaluation"],
            "paper_fill_status": paper_fill["fill_status"],
            "paper_exposure": paper_exposure["paper_exposure"],
            "current_open_position_count": current_exposure["summary"]["open_position_count"],
            "reconciliation_codes": reconciliation["mismatch_codes"],
            "reconciliation_severity": reconciliation["diff_severity"],
            "mismatch_report_codes": mismatch_report["summary"]["mismatch_codes"],
            "db_summary": db_summary,
        }
    finally:
        CLOCK_OVERRIDE.reset(token)


def test_phase2_paper_trading_loop_is_repeatable_local_and_non_executing(tmp_path, monkeypatch) -> None:
    _deny_network(monkeypatch)

    first_home = tmp_path / "first-home"
    second_home = tmp_path / "second-home"
    first = _run_phase2_paper_loop(first_home)
    second = _run_phase2_paper_loop(second_home)

    assert first == second
    _assert_no_credential_markers_persisted(first_home)
    _assert_no_credential_markers_persisted(second_home)


def test_phase2_loop_tools_are_public_without_live_polymarket_catalog_leak() -> None:
    reg = build_registry()
    public = set(reg.public_names())
    experimental = set(reg.public_names(include_experimental=True))

    assert _PHASE2_LOOP_TOOLS <= public
    for name in _PHASE2_LOOP_TOOLS:
        assert reg.get(name).metadata()["catalog_visibility"] == "public"

    assert _ADAPTER_BACKED_POLYMARKET_TOOLS.isdisjoint(public)
    assert _ADAPTER_BACKED_POLYMARKET_TOOLS <= experimental
