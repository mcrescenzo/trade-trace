"""TraceLab trader-agent launch environment contract helpers.

The helpers here are intentionally sidecar-only: they do not start external
agents, mutate user profiles, or choose a production home. They materialize the
environment shape that a controller can pass to each trader-agent process.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.tracelab.run_config import dispatch_trace_rotation_env


class DuplicateActorIdError(ValueError):
    """Raised when a multi-agent launch would reuse an actor id."""


@dataclass(frozen=True)
class TraderAgentLaunch:
    """Per-agent launch contract with a shared home and isolated log directory."""

    name: str
    actor_id: str
    trade_trace_home: Path
    log_dir: Path
    dispatch_trace_path: Path
    command: tuple[str, ...]
    env: dict[str, str]


def build_trader_agent_launches(
    actor_ids: Sequence[str],
    *,
    trade_trace_home: Path | str,
    log_root: Path | str | None = None,
    dispatch_trace_path: Path | str | None = None,
    command: Sequence[str] = ("trade-trace-mcp",),
    base_env: Mapping[str, str] | None = None,
) -> list[TraderAgentLaunch]:
    """Return per-agent env/command records for a TraceLab trader cohort.

    Invariants enforced before launch:
    - every agent shares exactly one absolute ``TRADE_TRACE_HOME``;
    - every agent has a distinct ``MCP_ACTOR_ID``;
    - every agent writes operational logs to a distinct
      ``TRADE_TRACE_LOG_DIR`` under ``log_root``;
    - dispatch tracing is enabled to one shared JSONL path so controller tests
      can prove calls arrived with distinct actors.
    """

    if not actor_ids:
        raise ValueError("at least one actor id is required")
    duplicates = sorted({actor_id for actor_id in actor_ids if actor_ids.count(actor_id) > 1})
    if duplicates:
        raise DuplicateActorIdError(f"duplicate MCP_ACTOR_ID values are not allowed: {duplicates}")

    home = Path(trade_trace_home).expanduser().resolve()
    logs = Path(log_root).expanduser().resolve() if log_root is not None else home / "logs" / "agents"
    trace = (
        Path(dispatch_trace_path).expanduser().resolve()
        if dispatch_trace_path is not None
        else home / "trace" / "tracelab-dispatch.jsonl"
    )
    cmd = tuple(command)
    launches: list[TraderAgentLaunch] = []
    for idx, actor_id in enumerate(actor_ids, start=1):
        name = _safe_name(actor_id) or f"agent-{idx}"
        log_dir = logs / name
        env = dict(os.environ if base_env is None else base_env)
        env.update(dispatch_trace_rotation_env())
        env.update(
            {
                "TRADE_TRACE_HOME": str(home),
                "MCP_ACTOR_ID": actor_id,
                "TRADE_TRACE_LOG_DIR": str(log_dir),
                "TRADE_TRACE_DISPATCH_TRACE_PATH": str(trace),
            }
        )
        launches.append(
            TraderAgentLaunch(
                name=name,
                actor_id=actor_id,
                trade_trace_home=home,
                log_dir=log_dir,
                dispatch_trace_path=trace,
                command=cmd,
                env=env,
            )
        )
    return launches


def _safe_name(actor_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in actor_id).strip("-")
