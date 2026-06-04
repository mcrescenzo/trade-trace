"""market.find_similar — structural/analogical recall over markets
(trade-trace-4kec.13). Demonstrates a fixture where lexical recall misses
(no shared keywords) but structural recall hits.
"""

from __future__ import annotations

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


def _market(
    home: Path, idx: int, *, title: str, mechanism: str, resolution_source: str,
    ambiguity_kind: str | None, prob: float, volume: float, spread: float,
) -> str:
    venue = _envelope(home, "venue.add", {"name": f"PM{idx}", "kind": "prediction_market"})["data"]["id"]
    inst = _envelope(home, "instrument.add", {"venue_id": venue, "asset_class": "prediction_market", "title": title})["data"]["id"]
    bind = {
        "id": inst, "source": "polymarket", "external_id": f"ext-{inst}", "title": title,
        "state": "open", "mechanism": mechanism, "resolution_source": resolution_source, "bound_via": "manual",
        "opened_at": "2027-01-01T00:00:00Z", "close_at": "2027-02-01T00:00:00Z",
    }
    if ambiguity_kind is not None:
        bind["ambiguity_kind"] = ambiguity_kind
    _envelope(home, "market.bind", bind)
    _envelope(home, "snapshot.add", {
        "instrument_id": inst, "captured_at": "2027-01-05T00:00:00Z", "source": "manual",
        "mid": prob, "implied_probability": prob, "price": prob, "volume": volume, "spread": spread,
    })
    return inst


def _find_similar(home: Path, instrument_id: str, **extra):
    return mcp_call("market.find_similar", {"home": str(home), "instrument_id": instrument_id, **extra}, actor_id="agent:default").model_dump(mode="json", exclude_none=True)


def test_registered_public():
    assert "market.find_similar" in set(default_registry().public_names())


def test_structural_recall_hits_where_keywords_miss(home: Path):
    # Reference: AMM, arbitration (ambiguous), longshot, thin liquidity.
    ref = _market(home, 0, title="Will the Lakers win the title?", mechanism="amm",
                  resolution_source="arbitration", ambiguity_kind="market_rules_unclear", prob=0.05, volume=10.0, spread=0.2)
    # Analogue: SHARES NO TITLE WORDS but identical structure.
    analogue = _market(home, 1, title="Coup d'etat before March?", mechanism="amm",
                       resolution_source="arbitration", ambiguity_kind="market_rules_unclear", prob=0.08, volume=12.0, spread=0.2)
    # Structural opposite: clob, market_contract, mainstream prob, deep liquidity.
    _market(home, 2, title="Lakers championship odds tracker", mechanism="clob",
            resolution_source="market_contract", ambiguity_kind=None, prob=0.5, volume=100000.0, spread=0.01)

    env = _find_similar(home, ref, min_score=0.99)
    assert env["ok"], env
    matches = env["data"]["matches"]
    assert env["data"]["embeddings_used"] is False
    ids = [m["instrument_id"] for m in matches]
    assert analogue in ids
    top = matches[0]
    assert top["instrument_id"] == analogue
    assert top["score"] == pytest.approx(1.0)
    assert {"mechanism", "resolution_source", "ambiguous", "longshot"}.issubset(set(top["matched_dimensions"]))

    # Lexical sanity: the analogue shares no title keyword with the reference,
    # so a keyword match on the reference's distinctive word would miss it.
    assert "lakers" not in env["data"]["matches"][0]["title"].lower()


def test_dissimilar_market_scores_below_threshold(home: Path):
    ref = _market(home, 0, title="A", mechanism="amm", resolution_source="arbitration",
                  ambiguity_kind="market_rules_unclear", prob=0.05, volume=10.0, spread=0.2)
    _market(home, 1, title="B", mechanism="clob", resolution_source="market_contract",
            ambiguity_kind=None, prob=0.5, volume=100000.0, spread=0.01)
    env = _find_similar(home, ref, min_score=0.8)
    assert env["data"]["count"] == 0


def test_sparse_match_exposes_coverage_and_ranks_below_full_match(home: Path):
    """A snapshot-less candidate is comparable on only the snapshot-independent
    dimensions (mechanism, resolution_source, ambiguous); matching all of those
    yields score 1.0 — the same headline score as a candidate that matches all
    six dimensions. The result must (a) expose comparable_dimensions so a consumer
    can tell a 1.0-over-3 from a 1.0-over-6, and (b) rank the fuller, more
    corroborated match first within the tied score band."""
    ref = _market(home, 0, title="Ref", mechanism="amm", resolution_source="arbitration",
                  ambiguity_kind="market_rules_unclear", prob=0.05, volume=10.0, spread=0.2)
    full = _market(home, 1, title="Full analogue", mechanism="amm", resolution_source="arbitration",
                   ambiguity_kind="market_rules_unclear", prob=0.08, volume=12.0, spread=0.2)
    # Sparse candidate: matches the three snapshot-independent dims but has NO
    # snapshot, so liquidity/spread/longshot are non-comparable.
    venue = _envelope(home, "venue.add", {"name": "PMsparse", "kind": "prediction_market"})["data"]["id"]
    sparse = _envelope(home, "instrument.add", {"venue_id": venue, "asset_class": "prediction_market", "title": "Sparse"})["data"]["id"]
    _envelope(home, "market.bind", {
        "id": sparse, "source": "polymarket", "external_id": f"ext-{sparse}", "title": "Sparse",
        "state": "open", "mechanism": "amm", "resolution_source": "arbitration", "bound_via": "manual",
        "ambiguity_kind": "market_rules_unclear",
        "opened_at": "2027-01-01T00:00:00Z", "close_at": "2027-02-01T00:00:00Z",
    })

    env = _find_similar(home, ref, min_score=0.99)
    assert env["ok"], env
    matches = env["data"]["matches"]
    by_id = {m["instrument_id"]: m for m in matches}
    assert by_id[full]["score"] == pytest.approx(1.0)
    assert by_id[sparse]["score"] == pytest.approx(1.0)
    assert by_id[full]["comparable_dimensions"] == 6
    assert by_id[sparse]["comparable_dimensions"] == 3
    # Fuller coverage ranks first despite the tied headline score.
    assert matches.index(by_id[full]) < matches.index(by_id[sparse])


def test_rejects_unknown_market(home: Path):
    env = _find_similar(home, "ins_missing")
    assert env["ok"] is False
    assert env["error"]["code"] == "NOT_FOUND"
