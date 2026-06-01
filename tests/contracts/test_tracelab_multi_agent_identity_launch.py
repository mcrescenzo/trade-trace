"""Contract tests for TraceLab multi-agent identity launch wiring."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from tools.tracelab.agent_launch import DuplicateActorIdError, build_trader_agent_launches
from trade_trace.contracts.errors import ErrorCode
from trade_trace.mcp_server import mcp_call, stdio_actor_id


def _seed_instrument(home: Path, *, actor_id: str = "agent:seed") -> str:
    venue = mcp_call(
        "venue.add",
        {"home": str(home), "name": "TraceLab Venue", "kind": "prediction_market"},
        actor_id=actor_id,
    )
    assert venue.ok, venue
    venue_id = venue.model_dump(mode="json")["data"]["id"]
    instrument = mcp_call(
        "instrument.add",
        {
            "home": str(home),
            "venue_id": venue_id,
            "asset_class": "prediction_market",
            "title": "TraceLab market",
        },
        actor_id=actor_id,
    )
    assert instrument.ok, instrument
    return instrument.model_dump(mode="json")["data"]["id"]


def test_launcher_materializes_shared_home_distinct_actor_and_log_env(tmp_path: Path):
    home = tmp_path / "shared-home"
    trace_path = tmp_path / "dispatch" / "trace.jsonl"
    launches = build_trader_agent_launches(
        ["agent:trader-a", "agent:trader-b"],
        trade_trace_home=home,
        log_root=tmp_path / "logs",
        dispatch_trace_path=trace_path,
        base_env={},
    )

    assert {launch.env["TRADE_TRACE_HOME"] for launch in launches} == {str(home.resolve())}
    assert [launch.env["MCP_ACTOR_ID"] for launch in launches] == ["agent:trader-a", "agent:trader-b"]
    assert len({launch.env["TRADE_TRACE_LOG_DIR"] for launch in launches}) == 2
    assert {launch.env["TRADE_TRACE_DISPATCH_TRACE_PATH"] for launch in launches} == {
        str(trace_path.resolve())
    }
    assert [stdio_actor_id(launch.env) for launch in launches] == [
        "agent:trader-a",
        "agent:trader-b",
    ]


def test_launcher_rejects_duplicate_actor_ids_before_launch(tmp_path: Path):
    try:
        build_trader_agent_launches(
            ["agent:trader-a", "agent:trader-a"],
            trade_trace_home=tmp_path / "shared-home",
            base_env={},
        )
    except DuplicateActorIdError as exc:
        assert "agent:trader-a" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("duplicate actor id was accepted")


def test_two_processes_share_home_and_emit_distinct_dispatch_actor_ids(tmp_path: Path):
    home = tmp_path / "shared-home"
    init = mcp_call("journal.init", {"home": str(home)}, actor_id="agent:controller")
    assert init.ok, init
    instrument_id = _seed_instrument(home)
    trace_path = tmp_path / "dispatch.jsonl"
    launches = build_trader_agent_launches(
        ["agent:trader-a", "agent:trader-b"],
        trade_trace_home=home,
        log_root=tmp_path / "logs",
        dispatch_trace_path=trace_path,
        base_env={"PYTHONPATH": os.pathsep.join(sys.path)},
    )
    script = textwrap.dedent(
        """
        import os
        from trade_trace.mcp_server import mcp_call, stdio_actor_id

        actor = stdio_actor_id(os.environ)
        result = mcp_call(
            "decision.add",
            {
                "home": os.environ["TRADE_TRACE_HOME"],
                "instrument_id": os.environ["TT_INSTRUMENT_ID"],
                "type": "skip",
                "reason": f"dry run from {actor}",
                "idempotency_key": "shared-key-distinct-actors",
            },
            actor_id=actor,
        )
        assert result.ok, result
        """
    )

    for launch in launches:
        env = {**launch.env, "TT_INSTRUMENT_ID": instrument_id}
        subprocess.run([sys.executable, "-c", script], check=True, env=env, cwd=Path.cwd())

    records = [json.loads(line) for line in trace_path.read_text().splitlines()]
    decision_records = [record for record in records if record["tool"] == "decision.add"]
    assert {record["actor_id"] for record in decision_records} == {"agent:trader-a", "agent:trader-b"}
    assert all(record["ok"] for record in decision_records)


def test_same_actor_same_key_different_payload_conflicts_in_shared_home(home: Path):
    instrument_id = _seed_instrument(home)
    args = {
        "home": str(home),
        "instrument_id": instrument_id,
        "type": "skip",
        "reason": "first payload",
        "tags": ["first"],
        "idempotency_key": "misconfigured-same-actor-key",
    }
    first = mcp_call("decision.add", args, actor_id="agent:trader-a")
    assert first.ok, first

    conflict = mcp_call(
        "decision.add",
        {**args, "tags": ["different"]},
        actor_id="agent:trader-a",
    )

    assert not conflict.ok
    error = conflict.model_dump(mode="json")["error"]
    assert error["code"] == ErrorCode.IDEMPOTENCY_CONFLICT
    assert error["details"]["actor_id"] == "agent:trader-a"
    assert error["details"]["idempotency_key"] == "misconfigured-same-actor-key"


def test_distinct_per_actor_log_dirs_are_used_by_concurrent_processes(tmp_path: Path):
    launches = build_trader_agent_launches(
        ["agent:trader-a", "agent:trader-b"],
        trade_trace_home=tmp_path / "shared-home",
        log_root=tmp_path / "logs",
        base_env={"PYTHONPATH": os.pathsep.join(sys.path)},
    )
    script = textwrap.dedent(
        """
        import json
        import os
        from pathlib import Path

        log_dir = Path(os.environ["TRADE_TRACE_LOG_DIR"])
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "agent.log"
        with path.open("a", encoding="utf-8") as fh:
            for i in range(25):
                fh.write(json.dumps({"actor": os.environ["MCP_ACTOR_ID"], "i": i}) + "\\n")
        """
    )
    procs = [
        subprocess.Popen([sys.executable, "-c", script], env=launch.env, cwd=Path.cwd())
        for launch in launches
    ]
    for proc in procs:
        assert proc.wait(timeout=10) == 0

    for launch in launches:
        path = launch.log_dir / "agent.log"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert len(records) == 25
        assert {record["actor"] for record in records} == {launch.actor_id}
    assert launches[0].log_dir != launches[1].log_dir
