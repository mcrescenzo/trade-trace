from __future__ import annotations

import json
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest

from tools.tracelab import seeder
from trade_trace.mcp_server import mcp_call


def _market(idx: int, *, outcomes='["Yes","No"]', end="2026-06-10T00:00:00Z", condition: str | None = None) -> dict:
    return {
        "id": str(1000 + idx),
        "conditionId": condition or f"cond-{idx}",
        "question": f"Market {idx}?",
        "outcomes": outcomes,
        "endDate": end,
        "liquidity": "100",
        "volume": "1000",
        "active": True,
        "closed": False,
    }


def test_json_string_multi_outcome_rejected_before_bind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bind_calls: list[object] = []
    monkeypatch.setattr(seeder, "mcp_call", lambda *args, **kwargs: bind_calls.append((args, kwargs)))

    def page(*args, **kwargs):
        kwargs["budget"].spend()
        return [_market(1, outcomes='["Yes","No","Maybe"]')]

    candidates, requests = seeder.discover_candidates(
        base_url=seeder.GAMMA_BASE_URL,
        request_cap=5,
        target=1,
        as_of=datetime(2026, 6, 1, tzinfo=UTC),
        fetch_page=page,
    )

    assert requests == 1
    assert candidates == []
    assert bind_calls == []


def test_gamma_call_budget_stops_at_cap() -> None:
    offsets: list[int] = []

    def page(*args, **kwargs):
        kwargs["budget"].spend()
        offsets.append(kwargs["offset"])
        return [_market(kwargs["offset"] + 1, end="2026-07-30T00:00:00Z")]

    with pytest.raises(seeder.SeederAbort, match="budget exhausted"):
        seeder.discover_candidates(
            base_url=seeder.GAMMA_BASE_URL,
            request_cap=2,
            target=1,
            page_size=1,
            as_of=datetime(2026, 6, 1, tzinfo=UTC),
            fetch_page=page,
        )
    assert offsets == [0, 1]


def test_seeded_condition_file_written_in_dry_run(tmp_path: Path) -> None:
    artifact = tmp_path / "conditions.json"
    result = seeder.seed(
        home=str(tmp_path / "home"),
        artifact_path=str(artifact),
        dry_run=True,
        base_url=seeder.GAMMA_BASE_URL,
        request_cap=5,
        target=2,
        as_of=datetime(2026, 6, 1, tzinfo=UTC),
        fetch_page=lambda *a, **k: [_market(1), _market(2)],
    )

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert result.condition_ids == ["cond-1", "cond-2"]
    assert payload["condition_ids"] == ["cond-1", "cond-2"]
    assert payload["dry_run"] is True
    assert payload["complete"] is True
    assert payload["candidate_count"] == 2
    assert "histogram" in payload


def test_discovery_histogram_counts_filter_reasons() -> None:
    missing_condition = _market(2)
    missing_condition.pop("conditionId")
    missing_market_id = _market(3)
    missing_market_id.pop("id")
    low_liquidity = _market(4)
    low_liquidity["liquidity"] = "1"

    discovery = seeder.discover_candidates(
        base_url=seeder.GAMMA_BASE_URL,
        request_cap=5,
        target=3,
        as_of=datetime(2026, 6, 1, tzinfo=UTC),
        min_liquidity=50,
        fetch_page=lambda *a, **k: [
            _market(1),
            _market(1, condition="cond-1"),
            _market(10, outcomes='["Yes","No","Maybe"]'),
            missing_condition,
            missing_market_id,
            _market(5, end="2026-07-30T00:00:00Z"),
            low_liquidity,
        ],
    )

    assert discovery.candidates[0].condition_id == "cond-1"
    assert discovery.histogram["pages_scanned"] == 1
    assert discovery.histogram["items_scanned"] == 7
    assert discovery.histogram["accepted"] == 1
    assert discovery.histogram["duplicate_condition_id"] == 1
    assert discovery.histogram["non_binary"] == 1
    assert discovery.histogram["missing_condition_id"] == 1
    assert discovery.histogram["missing_market_id"] == 1
    assert discovery.histogram["outside_window"] == 1
    assert discovery.histogram["low_liquidity"] == 1


def test_seed_writes_partial_artifact_on_budget_exhaustion(tmp_path: Path) -> None:
    artifact = tmp_path / "partial.json"

    def page(*args, **kwargs):
        kwargs["budget"].spend()
        idx = kwargs["offset"] + 1
        return [_market(idx)]

    with pytest.raises(seeder.SeederAbort, match="budget exhausted"):
        seeder.seed(
            home=str(tmp_path / "home"),
            artifact_path=str(artifact),
            dry_run=True,
            base_url=seeder.GAMMA_BASE_URL,
            request_cap=2,
            target=3,
            page_size=1,
            as_of=datetime(2026, 6, 1, tzinfo=UTC),
            fetch_page=page,
        )

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["complete"] is False
    assert "budget exhausted" in payload["abort_reason"]
    assert payload["gamma_requests"] == 2
    assert payload["candidate_count"] == 2
    assert payload["condition_ids"] == ["cond-1", "cond-2"]
    assert payload["histogram"]["accepted"] == 2
    assert payload["histogram"]["pages_scanned"] == 2


def test_seed_writes_partial_artifact_on_gamma_429(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    artifact = tmp_path / "partial-429.json"

    def raise_429(*args, **kwargs):
        raise HTTPError("https://gamma-api.polymarket.com/markets", 429, "Too Many Requests", hdrs=Message(), fp=None)

    monkeypatch.setattr(seeder.urllib.request, "urlopen", raise_429)

    with pytest.raises(seeder.SeederAbort, match="Gamma rate limit: HTTP 429"):
        seeder.seed(
            home=str(tmp_path / "home"),
            artifact_path=str(artifact),
            dry_run=True,
            base_url=seeder.GAMMA_BASE_URL,
            request_cap=5,
            target=3,
            page_size=1,
            as_of=datetime(2026, 6, 1, tzinfo=UTC),
        )

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["complete"] is False
    assert "Gamma rate limit: HTTP 429" in payload["abort_reason"]
    assert payload["gamma_requests"] == 1
    assert payload["candidate_count"] == 0
    assert payload["histogram"]["pages_scanned"] == 0


def test_cli_filter_args_are_plumbed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = {}

    def fake_seed(**kwargs):
        seen.update(kwargs)
        return seeder.SeedResult(str(tmp_path / "artifact.json"), 0, 0, 0, 0, 0)

    monkeypatch.setattr(seeder, "seed", fake_seed)
    assert seeder.main(["--home", str(tmp_path), "--dry-run", "--min-days", "2", "--max-days", "21", "--min-liquidity", "25.5"]) == 0
    assert seen["min_days"] == 2
    assert seen["max_days"] == 21
    assert seen["min_liquidity"] == 25.5


def test_seeded_markers_surface_in_watchlist_and_work_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    # Manual bind/snapshot through the public surface keeps this unit contract network-free.
    market = mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": "1001", "state": "open", "mechanism": "clob", "title": "Seeded", "bound_via": "manual"})
    assert market.ok, market
    snap = mcp_call("snapshot.add", {"home": home, "instrument_id": market.data["id"], "captured_at": "2026-06-01T00:00:00Z", "source": "manual", "price": 0.5})
    assert snap.ok, snap

    def fake_call(tool: str, args: dict):
        if tool == "market.bind":
            return market
        if tool == "snapshot.fetch":
            return snap
        return mcp_call(tool, args)

    monkeypatch.setattr(seeder, "mcp_call", fake_call)
    artifact = tmp_path / "seeded.json"
    result = seeder.bind_snapshot_and_mark(home, [seeder.Candidate("1001", "cond-surfaced", "Seeded?", "2026-06-10T00:00:00Z")], artifact_path=artifact)
    assert result.condition_ids == ["cond-surfaced"]

    watchlist = mcp_call("report.watchlist", {"home": home})
    assert watchlist.ok, watchlist
    serialized_watchlist = json.dumps(watchlist.data)
    assert "tracelab_seeded" in serialized_watchlist
    assert "cond-surfaced" in serialized_watchlist

    work_queue = mcp_call("report.work_queue", {"home": home, "as_of": "2027-06-01T00:00:01Z"})
    assert work_queue.ok, work_queue
    serialized_queue = json.dumps(work_queue.data)
    assert "review_due_watch" in serialized_queue
    assert "tracelab_seeded" in serialized_queue
