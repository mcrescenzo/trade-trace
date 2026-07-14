from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.contracts.envelope import ErrorEnvelope, SuccessEnvelope
from trade_trace.mcp_server import mcp_call

FIXTURES = Path(__file__).parent / "fixtures" / "polymarket"
REQUIRED_FIXTURES = {
    "market_binary_open.json",
    "market_binary_open_amm.json",
    "market_binary_resolved_yes.json",
    "market_binary_resolved_no.json",
    "market_binary_ambiguous.json",
    "market_binary_voided.json",
    "market_binary_disputed.json",
    "market_categorical_rejected.json",
    "market_scalar_rejected.json",
    "snapshot_thick_book.json",
    "snapshot_thin_book.json",
    "snapshot_amm_curve.json",
    "polygon_resolution_tx.json",
    # negRisk parent-event enrichment corpus (trade-trace-lf82j):
    "market_negrisk_bracket_leg.json",
    "market_negrisk_bracket_leg_no_parent.json",
    # models Gamma's /markets?id= LIST response shape (top-level array):
    "market_negrisk_parent_event_markets_response.json",
}

# Fixtures whose authentic Gamma payload shape is a top-level JSON array.
LIST_SHAPED_FIXTURES = {"market_negrisk_parent_event_markets_response.json"}


def _fixture(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _enable_adapter(home: str) -> None:
    assert mcp_call(
        "journal.config_set",
        {"home": home, "key": "network.polymarket.enabled", "value": "true", "confirm": True, "idempotency_key": "test-legacy:config-polymarket-enabled"},
    ).ok


def test_market_bind_manual_disabled_adapter(tmp_path: Path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    env = mcp_call(
        "market.bind",
        {
            "home": home,
            "source": "polymarket",
            "external_id": "pm-manual",
            "state": "open",
            "mechanism": "clob",
            "title": "Manual PM",
            "bound_via": "manual",
        },
    )
    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert env.data["bound_via"] == "manual"


def test_polymarket_fixture_corpus_is_complete_and_parseable():
    names = {p.name for p in FIXTURES.glob("*.json")}
    assert names == REQUIRED_FIXTURES
    for name in REQUIRED_FIXTURES:
        expected = list if name in LIST_SHAPED_FIXTURES else dict
        assert isinstance(_fixture(name), expected), name


def test_market_bind_enabled_fetches_fixture_backed_market(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)
    calls: list[str] = []

    def fake_gamma_get(self: PolymarketClient, path: str):
        calls.append(path)
        return _fixture("market_binary_open_amm.json")

    monkeypatch.setattr(PolymarketClient, "gamma_get", fake_gamma_get)

    env = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": "pm-open-amm"})

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert calls == ["/markets/pm-open-amm"]
    assert env.data["source"] == "polymarket"
    assert env.data["external_id"] == "pm-open-amm"
    assert env.data["bound_via"] == "adapter"
    assert env.data["mechanism"] == "amm"
    meta = json.loads(env.data["metadata_json"])
    assert meta["polymarket_identity"]["gamma_market_id"]
    assert "condition_id" in meta["polymarket_identity"]
    assert "outcome_token_ids_by_label" in meta["polymarket_identity"]
    assert meta["resolution_rule"]["provenance"] == "polymarket_gamma_payload"
    assert "event_grouping" in meta



def test_market_bind_prefers_gamma_market_id_over_namespaced_external_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Regression (AX dogfood FR-1): on the FIRST bind the row does not exist yet,
    # so the Gamma /markets/{id} lookup must use the caller-supplied
    # gamma_market_id, not the namespaced external_id. The AGENT_GUIDE's own
    # market.bind example passes external_id="polymarket:<id>" + a bare
    # gamma_market_id; building the URL from external_id 422s on the namespace.
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)
    calls: list[str] = []

    def fake_gamma_get(self: PolymarketClient, path: str):
        calls.append(path)
        return _fixture("market_binary_open.json")

    monkeypatch.setattr(PolymarketClient, "gamma_get", fake_gamma_get)

    env = mcp_call(
        "market.bind",
        {
            "home": home,
            "source": "polymarket",
            "external_id": "polymarket:2410562",
            "gamma_market_id": "2410562",
        },
    )

    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    # The lookup used the bare gamma_market_id, not the namespaced external_id.
    assert calls == ["/markets/2410562"]
    # The caller's namespaced external_id is still persisted for bookkeeping.
    assert env.data["external_id"] == "polymarket:2410562"
    assert env.data["bound_via"] == "adapter"


def test_adapter_bound_market_is_immediately_forecastable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Regression (AX dogfood AX-023): market.bind via the adapter path returns a
    # market_id the docstring promises is a prerequisite for forecast.add, but it
    # previously created only the markets row and left the compatibility
    # instruments row to the first snapshot.fetch. So bind -> forecast.add (no
    # snapshot yet) failed NOT_FOUND "instrument_id not found". The adapter bind
    # path must materialize the instrument row at bind time, like the manual path.
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)
    monkeypatch.setattr(
        PolymarketClient, "gamma_get", lambda self, path: _fixture("market_binary_open.json")
    )

    bind = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": "pm-forecastable"})
    assert bind.ok, bind
    assert bind.data["bound_via"] == "adapter"
    market_id = bind.data["id"]

    # No snapshot.fetch in between — forecast.add must still resolve the instrument.
    fc = mcp_call(
        "forecast.add",
        {
            "home": home,
            "kind": "binary",
            "market_id": market_id,
            "yes_label": "yes",
            "outcomes": [
                {"label": "yes", "outcome_label": "yes", "probability": 0.4},
                {"label": "no", "outcome_label": "no", "probability": 0.6},
            ],
            "rationale_body": "Adapter-bound market should be forecastable without a prior snapshot.",
            "idempotency_key": "test:ax023:forecast-after-adapter-bind",
        },
    )
    assert fc.ok, fc
    assert isinstance(fc, SuccessEnvelope)
    assert fc.data["kind"] == "binary"


def test_market_bind_accepts_string_list_outcomes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)
    raw = _fixture("market_binary_open.json") | {"outcomes": ["Yes", "No"]}

    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: raw)

    env = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": "pm-string-outcomes"})
    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert env.data["external_id"] == "pm-string-outcomes"


def test_market_bind_accepts_gamma_json_string_outcomes_and_clob_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)
    raw = _fixture("market_binary_open.json") | {
        "outcomes": '["Yes","No"]',
        "clobTokenIds": '["token-yes","token-no"]',
    }

    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: raw)

    env = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": "540844"})
    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert env.data["external_id"] == "540844"
    venue_meta = json.loads(env.data["venue_metadata_json"])
    assert venue_meta["outcomes"] == ["Yes", "No"]
    assert venue_meta["clobTokenIds"] == ["token-yes", "token-no"]


def test_market_bind_rejects_malformed_gamma_json_string_outcomes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)
    raw = _fixture("market_binary_open.json") | {"outcomes": '["Yes",'}

    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: raw)

    env = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": "pm-bad-json-outcomes"})
    assert not env.ok
    assert isinstance(env, ErrorEnvelope)
    assert env.error.code == "ADAPTER_PROTOCOL_ERROR"
    assert env.error.details == {"external_id": "pm-bad-json-outcomes", "field": "outcomes"}


def test_market_bind_accepts_string_list_tokens_without_outcomes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)
    raw = _fixture("market_binary_open.json") | {"tokens": ["Yes", "No"]}
    raw.pop("outcomes", None)

    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: raw)

    env = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": "pm-string-tokens"})
    assert env.ok, env
    assert isinstance(env, SuccessEnvelope)
    assert env.data["external_id"] == "pm-string-tokens"


@pytest.mark.parametrize("field", ["outcomes", "tokens"])
def test_market_bind_rejects_invalid_string_list_outcome_elements_without_attribute_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)
    raw = _fixture("market_binary_open.json") | {field: ["Yes", 123]}
    if field == "tokens":
        raw.pop("outcomes", None)

    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: raw)

    env = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": f"pm-invalid-{field}"})
    assert not env.ok
    assert isinstance(env, ErrorEnvelope)
    assert env.error.code == "ADAPTER_PROTOCOL_ERROR"


@pytest.mark.parametrize("fixture_name", ["market_categorical_rejected.json", "market_scalar_rejected.json"])
def test_market_bind_rejects_non_binary_polymarket_fixtures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    _enable_adapter(home)

    monkeypatch.setattr(PolymarketClient, "gamma_get", lambda self, path: _fixture(fixture_name))

    env = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": fixture_name})
    assert not env.ok
    assert isinstance(env, ErrorEnvelope)
    assert env.error.code == "ADAPTER_PROTOCOL_ERROR"
