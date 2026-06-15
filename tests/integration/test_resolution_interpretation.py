"""Resolution-criteria interpretation + contract-misread diagnostic
(trade-trace-4kec.12).
"""

from __future__ import annotations

import json
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


def _market(home: Path, idx: int, *, resolution_source: str, resolved: bool) -> str:
    venue = _envelope(home, "venue.add", {"name": f"PM{idx}", "kind": "prediction_market"})["data"]["id"]
    inst = _envelope(home, "instrument.add", {"venue_id": venue, "asset_class": "prediction_market", "title": f"M{idx}"})["data"]["id"]
    _envelope(
        home, "market.bind",
        {"id": inst, "source": "polymarket", "external_id": f"ext-{inst}", "title": f"M{idx}",
         "state": "resolved" if resolved else "open", "mechanism": "clob", "bound_via": "manual",
         "resolution_source": resolution_source,
         "opened_at": "2027-01-01T00:00:00Z", "close_at": "2027-01-10T00:00:00Z",
         "closed_for_trading_at": "2027-01-10T00:00:00Z", "resolving_at": "2027-01-11T00:00:00Z",
         "resolved_at": "2027-01-12T00:00:00Z" if resolved else None},
    )
    return inst


def _forecast(home: Path, inst: str) -> str:
    thesis = _envelope(home, "thesis.add", {"instrument_id": inst, "side": "yes", "body": "t"})["data"]["id"]
    return _envelope(
        home, "forecast.add",
        {"thesis_id": thesis, "kind": "binary", "yes_label": "yes",
         "outcomes": [{"outcome_label": "yes", "probability": 0.6}, {"outcome_label": "no", "probability": 0.4}]},
    )["data"]["id"]


def _resolve(home: Path, inst: str, label: str = "yes") -> None:
    _envelope(home, "resolution.add", {"instrument_id": inst, "resolved_at": "2027-01-12T00:00:00Z", "outcome_label": label, "status": "resolved_final", "confidence": 0.99})


def _interpret(home: Path, forecast_id: str, **extra):
    return mcp_call(
        "forecast.interpret_resolution",
        {"home": str(home), "forecast_id": forecast_id,
         "interpreted_yes_condition": "YES if AP calls it", "as_of": "2027-01-02T00:00:00Z", **extra},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)


def _misreads(home: Path):
    return mcp_call("report.resolution_misreads", {"home": str(home)}, actor_id="agent:default").model_dump(mode="json", exclude_none=True)


def test_tools_registered_public():
    names = set(default_registry().public_names())
    assert {"forecast.interpret_resolution", "forecast.resolution_interpretation", "report.resolution_misreads"}.issubset(names)


def test_record_and_read_interpretation(home: Path):
    inst = _market(home, 0, resolution_source="oracle_feed", resolved=False)
    fc = _forecast(home, inst)
    env = _interpret(home, fc, interpreted_resolution_source="oracle_feed")
    assert env["ok"], env
    assert env["data"]["instrument_id"] == inst
    assert env["data"]["interpreted_resolution_source"] == "oracle_feed"

    got = mcp_call("forecast.resolution_interpretation", {"home": str(home), "forecast_id": fc}).model_dump(mode="json", exclude_none=True)
    assert got["ok"]
    assert got["data"]["forecast_id"] == fc


def test_contract_misread_when_source_differs(home: Path):
    inst = _market(home, 0, resolution_source="market_contract", resolved=True)
    fc = _forecast(home, inst)
    _interpret(home, fc, interpreted_resolution_source="oracle_feed")
    _resolve(home, inst)
    env = _misreads(home)
    assert env["ok"], env
    summary = env["data"]["summary"]
    assert summary["contract_misread_count"] == 1
    assert env["data"]["groups"][0]["metrics"]["classification"] == "contract_misread"


def test_aligned_when_source_matches(home: Path):
    inst = _market(home, 0, resolution_source="oracle_feed", resolved=True)
    fc = _forecast(home, inst)
    _interpret(home, fc, interpreted_resolution_source="oracle_feed")  # case-insensitive
    _resolve(home, inst)
    env = _misreads(home)
    assert env["data"]["summary"]["aligned_count"] == 1
    assert env["data"]["summary"]["contract_misread_count"] == 0


def test_unresolved_market_is_not_a_misread(home: Path):
    inst = _market(home, 0, resolution_source="oracle_feed", resolved=False)
    fc = _forecast(home, inst)
    _interpret(home, fc, interpreted_resolution_source="oracle_feed")
    env = _misreads(home)
    assert env["data"]["summary"]["unresolved_count"] == 1
    assert env["data"]["summary"]["contract_misread_count"] == 0


def test_interpretation_is_idempotent_one_per_forecast(home: Path):
    inst = _market(home, 0, resolution_source="oracle_feed", resolved=False)
    fc = _forecast(home, inst)
    first = _interpret(home, fc, interpreted_resolution_source="oracle_feed")
    second = _interpret(home, fc, interpreted_resolution_source="manual_review")
    assert first["data"]["id"] == second["data"]["id"]
    assert second["data"]["interpreted_resolution_source"] == "oracle_feed"  # first wins
    # AX-052: the one-per-forecast collision must be self-documenting, not a
    # silent no-op false-success. A divergent revision is flagged + told plainly
    # that the supplied values were not applied.
    assert second["data"]["already_interpreted"] is True
    assert "already_interpreted" not in first["data"]
    assert "NOT applied" in second["data"]["caveat"]


def test_interpretation_is_append_only(home: Path):
    inst = _market(home, 0, resolution_source="oracle_feed", resolved=False)
    fc = _forecast(home, inst)
    _interpret(home, fc)
    import sqlite3

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(home))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute("UPDATE resolution_interpretations SET interpreted_yes_condition = 'x' WHERE forecast_id = ?", (fc,))
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute("DELETE FROM resolution_interpretations WHERE forecast_id = ?", (fc,))
    finally:
        db.close()


def test_interpret_rejects_unknown_forecast(home: Path):
    env = _interpret(home, "fc_missing")
    assert env["ok"] is False
    assert env["error"]["code"] == "NOT_FOUND"


def test_misread_surfaces_manual_source_provenance(home: Path):
    # AX-067: every misread group now reports actual_source_provenance (the
    # market's bound_via) so a consumer can tell whether the "actual" resolution
    # source it is being scored against was caller-asserted (manual) or stamped
    # by a venue adapter. A manually-bound market is high-confidence ground truth.
    inst = _market(home, 0, resolution_source="market_contract", resolved=True)
    fc = _forecast(home, inst)
    _interpret(home, fc, interpreted_resolution_source="oracle_feed")
    _resolve(home, inst)
    env = _misreads(home)
    assert env["data"]["summary"]["contract_misread_count"] == 1
    assert env["data"]["summary"]["contract_misread_adapter_bound_count"] == 0
    assert env["data"]["groups"][0]["metrics"]["actual_source_provenance"] == "manual"


def test_adapter_maps_undisputed_polymarket_market_to_oracle_feed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # trade-trace-v5va (design half of AX-067): the faithful Polymarket
    # resolution mechanism is the UMA optimistic oracle, not an on-chain
    # market_contract. The adapter now maps every undisputed, non-ambiguous
    # market to oracle_feed, so an agent that reads a UMA-over-Binance crypto
    # strike as oracle_feed scores *aligned* instead of being hard-classified a
    # contract_misread against a coarse market_contract default. (The ergonomic
    # provenance/caveat surfacing from 81345c8 stays; it now only fires when the
    # venue genuinely supplies a different mechanism.)
    from trade_trace.adapters.polymarket.client import PolymarketClient

    fixtures = Path(__file__).parent / "fixtures" / "polymarket"
    home = tmp_path / "home"
    home_s = str(home)
    assert mcp_call("journal.init", {"home": home_s}).ok
    assert mcp_call(
        "journal.config_set",
        {"home": home_s, "key": "network.polymarket.enabled", "value": "true",
         "confirm": True, "idempotency_key": "test:cfg-pm-enabled"},
    ).ok
    raw = json.loads((fixtures / "market_binary_resolved_yes.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: raw)

    bind = mcp_call("market.bind", {"home": home_s, "source": "polymarket", "external_id": "pm-res-yes"})
    assert bind.ok, bind
    inst = bind.data["id"]
    # Faithful mechanism mapping: undisputed Polymarket market -> oracle_feed.
    assert bind.data["resolution_source"] == "oracle_feed"
    assert bind.data["bound_via"] == "adapter"

    fc = _forecast(home, inst)
    _interpret(home, fc, interpreted_resolution_source="oracle_feed")
    _resolve(home, inst)

    env = _misreads(home)
    summary = env["data"]["summary"]
    # The oracle_feed reading now aligns with the faithfully-mapped source.
    assert summary["contract_misread_count"] == 0
    assert summary["contract_misread_adapter_bound_count"] == 0
    assert summary["aligned_count"] == 1
    grp = env["data"]["groups"][0]["metrics"]
    assert grp["classification"] == "aligned"
    assert grp["actual_resolution_source"] == "oracle_feed"
    assert grp["actual_source_provenance"] == "adapter"


def test_misread_against_genuine_adapter_mechanism_still_flagged_low_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The provenance/caveat surfacing (81345c8) still fires when an agent's
    # reading genuinely disagrees with the faithfully-mapped adapter mechanism:
    # here a disputed market maps to arbitration but the agent read oracle_feed.
    from trade_trace.adapters.polymarket.client import PolymarketClient

    fixtures = Path(__file__).parent / "fixtures" / "polymarket"
    home = tmp_path / "home"
    home_s = str(home)
    assert mcp_call("journal.init", {"home": home_s}).ok
    assert mcp_call(
        "journal.config_set",
        {"home": home_s, "key": "network.polymarket.enabled", "value": "true",
         "confirm": True, "idempotency_key": "test:cfg-pm-enabled"},
    ).ok
    raw = json.loads((fixtures / "market_binary_disputed.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: raw)

    bind = mcp_call("market.bind", {"home": home_s, "source": "polymarket", "external_id": "pm-disputed"})
    assert bind.ok, bind
    inst = bind.data["id"]
    assert bind.data["resolution_source"] == "arbitration"
    assert bind.data["bound_via"] == "adapter"

    fc = _forecast(home, inst)
    _interpret(home, fc, interpreted_resolution_source="oracle_feed")
    _resolve(home, inst)

    env = _misreads(home)
    summary = env["data"]["summary"]
    assert summary["contract_misread_count"] == 1
    assert summary["contract_misread_adapter_bound_count"] == 1
    grp = env["data"]["groups"][0]["metrics"]
    assert grp["classification"] == "contract_misread"
    assert grp["actual_source_provenance"] == "adapter"
    assert any("provenance='adapter'" in c for c in summary["caveats"])


def test_adapter_maps_gamma_description_to_resolution_rule_text_and_instrument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # trade-trace-n33z: Polymarket's Gamma payload carries the consequential
    # resolution prose in `description`, not `resolutionCriteria`. The adapter
    # must map it into the structured resolution_rule.text AND the compatibility
    # instrument's resolution_criteria_text so the criterion an agent needs to
    # forecast travels with the bound market instead of sitting unreadable in
    # venue_metadata_json.description.
    from trade_trace.adapters.polymarket.client import PolymarketClient
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    fixtures = Path(__file__).parent / "fixtures" / "polymarket"
    home = tmp_path / "home"
    home_s = str(home)
    assert mcp_call("journal.init", {"home": home_s}).ok
    assert mcp_call(
        "journal.config_set",
        {"home": home_s, "key": "network.polymarket.enabled", "value": "true",
         "confirm": True, "idempotency_key": "test:cfg-pm-enabled"},
    ).ok
    rule_text = (
        "Resolves YES per the official AP call; if not called by 2027-08-31 "
        "23:59 ET resolve to the LOWEST bracket; a boundary value rounds UP."
    )
    raw = json.loads((fixtures / "market_binary_open.json").read_text(encoding="utf-8"))
    raw["description"] = rule_text
    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: raw)

    bind = mcp_call("market.bind", {"home": home_s, "source": "polymarket", "external_id": "pm-desc"})
    assert bind.ok, bind
    inst = bind.data["id"]
    assert bind.data["bound_via"] == "adapter"
    # The Gamma description is mapped into the structured resolution_rule.text.
    meta = json.loads(bind.data["metadata_json"])
    assert meta["resolution_rule"]["text"] == rule_text
    assert meta["resolution_rule"]["provenance"] == "polymarket_gamma_payload"

    # ...and into the compatibility instrument's resolution_criteria_text, not
    # the question, so report surfaces can echo the criterion.
    db = open_database(db_path(home))
    try:
        row = db.connection.execute(
            "SELECT resolution_criteria_text FROM instruments WHERE id = ?", (inst,)
        ).fetchone()
    finally:
        db.close()
    assert row is not None
    assert row[0] == rule_text


def test_manual_bind_carries_caller_resolution_rule_into_instrument(home: Path):
    # trade-trace-n33z: the manual bind path previously hard-wired the
    # instrument's resolution_criteria_text to the question, dropping a
    # caller-supplied resolution rule. The caller's resolution_rule_text must
    # land in resolution_criteria_text so the auditable criterion travels with
    # the market.
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    rule_text = "Resolves YES if the official source reports the value above the strike."
    env = mcp_call(
        "market.bind",
        {"home": str(home), "source": "polymarket", "external_id": "manual-rule",
         "title": "M", "question": "Will it happen?", "state": "open",
         "mechanism": "clob", "bound_via": "manual",
         "resolution_rule_text": rule_text,
         "idempotency_key": "test:manual-rule-1"},
    )
    assert env.ok, env
    inst = env.data["id"]
    db = open_database(db_path(home))
    try:
        row = db.connection.execute(
            "SELECT resolution_criteria_text FROM instruments WHERE id = ?", (inst,)
        ).fetchone()
    finally:
        db.close()
    assert row is not None
    assert row[0] == rule_text
