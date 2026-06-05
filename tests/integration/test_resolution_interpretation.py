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
    _envelope(home, "outcome.add", {"instrument_id": inst, "resolved_at": "2027-01-12T00:00:00Z", "outcome_label": label, "status": "resolved_final", "confidence": 0.99})


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


def test_misread_against_adapter_default_source_is_flagged_low_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # AX-067: report.resolution_misreads scores the agent against
    # markets.resolution_source, but the Polymarket adapter stamps a coarse
    # default ("market_contract" unless disputed) because Gamma exposes no
    # enum-mappable resolution category. So a defensible oracle_feed reading of a
    # UMA-over-Binance crypto strike is hard-classified contract_misread against
    # an adapter default, not a faithfully-recorded mechanism. The fix does not
    # silence the classification (that ground-truth-quality half is filed), but
    # surfaces provenance + a dedicated count so a consumer can discount it.
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
    # The adapter stamped the coarse default rather than a mapped mechanism.
    assert bind.data["resolution_source"] == "market_contract"
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
