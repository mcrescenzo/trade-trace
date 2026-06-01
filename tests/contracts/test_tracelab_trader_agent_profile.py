from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.tracelab import seeder
from trade_trace.dispatch_trace import ENABLE_ENV, PATH_ENV
from trade_trace.mcp_server import mcp_call

PROMPT_PATH = Path(__file__).parents[2] / "docs" / "tracelab" / "trader-agent-profile.md"


def _trace_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_trader_agent_prompt_uses_native_affordances_without_hardcoded_discipline() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    forbidden = "->".join(("commit_blind", "reveal_snapshot", "interpret_resolution"))

    assert forbidden not in prompt
    for report in ("report.bootstrap", "report.work_queue", "report.watchlist", "report.coach"):
        assert report in prompt
    assert "Do not paste raw `0x...` addresses" in prompt
    assert "bare 40-hex" in prompt
    assert "risk_unit_label" in prompt
    assert "risk-unit-small" in prompt
    assert "risk-unit-medium" in prompt
    assert "risk-unit-large" in prompt


def test_trader_agent_dry_run_discovers_seeded_markets_via_report_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = str(tmp_path / "home")
    trace_path = tmp_path / "trace" / "dispatch.jsonl"
    actor_id = "agent:tracelab-trader-dry-run"

    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.setenv(PATH_ENV, str(trace_path))

    assert mcp_call("journal.init", {"home": home}, actor_id=actor_id).ok
    market = mcp_call(
        "market.bind",
        {
            "home": home,
            "source": "polymarket",
            "external_id": "1001",
            "state": "open",
            "mechanism": "clob",
            "title": "Seeded from public report affordance",
            "bound_via": "manual",
        },
        actor_id=actor_id,
    )
    assert market.ok, market
    snapshot = mcp_call(
        "snapshot.add",
        {
            "home": home,
            "instrument_id": market.data["id"],
            "captured_at": "2026-06-01T00:00:00Z",
            "source": "manual",
            "price": 0.5,
        },
        actor_id=actor_id,
    )
    assert snapshot.ok, snapshot

    def fake_call(tool: str, args: dict):
        if tool == "market.bind":
            return market
        if tool == "snapshot.fetch":
            return snapshot
        return mcp_call(tool, args, actor_id=actor_id)

    monkeypatch.setattr(seeder, "mcp_call", fake_call)
    result = seeder.bind_snapshot_and_mark(
        home,
        [
            seeder.Candidate(
                "1001",
                "cond-agent-discovered",
                "Seeded from public report affordance?",
                "2026-06-10T00:00:00Z",
            )
        ],
        artifact_path=tmp_path / "seeded.json",
    )
    assert result.condition_ids == ["cond-agent-discovered"]

    watchlist = mcp_call(
        "report.watchlist",
        {"home": home, "_dry_run": True},
        actor_id=actor_id,
        request_id="trader-watchlist-dry-run",
    )
    assert watchlist.ok, watchlist
    assert "tracelab_seeded" in json.dumps(watchlist.data)
    assert "cond-agent-discovered" in json.dumps(watchlist.data)

    work_queue = mcp_call(
        "report.work_queue",
        {"home": home, "as_of": "2027-06-01T00:00:01Z", "_dry_run": True},
        actor_id=actor_id,
        request_id="trader-work-queue-dry-run",
    )
    assert work_queue.ok, work_queue
    queue_json = json.dumps(work_queue.data)
    assert "review_due_watch" in queue_json
    assert "tracelab_seeded" in queue_json

    records = _trace_records(trace_path)
    report_records = [
        record
        for record in records
        if record["actor_id"] == actor_id and record["tool"] in {"report.watchlist", "report.work_queue"}
    ]
    assert [record["tool"] for record in report_records] == ["report.watchlist", "report.work_queue"]
    assert all(record["dry_run"] is True for record in report_records)
    assert all(record["ok"] is True for record in report_records)
    assert {record["request_id"] for record in report_records} == {
        "trader-watchlist-dry-run",
        "trader-work-queue-dry-run",
    }
