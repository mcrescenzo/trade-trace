"""TraceLab operational run-configuration loader.

The JSON artifact is documentation-first, but this loader makes the safety
knobs machine-checkable and reusable by launch helpers without introducing a
YAML dependency.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUN_CONFIG_PATH = ROOT / "docs" / "tracelab" / "run-config.json"


@lru_cache(maxsize=1)
def load_run_config(path: Path | str = RUN_CONFIG_PATH) -> dict[str, Any]:
    """Load and minimally validate the TraceLab run-config artifact."""

    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if config.get("schema") != "trade-trace.tracelab.run-config.v1":
        raise ValueError("unsupported TraceLab run-config schema")
    hygiene = config.get("capture_hygiene")
    caveat = config.get("replay_caveat")
    if not isinstance(hygiene, dict) or not isinstance(caveat, dict):
        raise ValueError("TraceLab run-config missing capture_hygiene or replay_caveat")
    return config


def dispatch_trace_rotation_env(config: dict[str, Any] | None = None) -> dict[str, str]:
    """Return explicit B1 dispatch-trace rotation env for trader launches."""

    cfg = config or load_run_config()
    env = cfg["capture_hygiene"]["dispatch_trace_rotation"]["env"]
    return {str(key): str(value) for key, value in env.items()}


def exporter_drain_enabled_during_run(config: dict[str, Any] | None = None) -> bool:
    """Whether TraceLab operators may run the one-file-per-event JSONL drain."""

    cfg = config or load_run_config()
    return bool(cfg["capture_hygiene"]["exporter_jsonl_drain"]["enabled_during_run"])


def include_late_recorded_default(config: dict[str, Any] | None = None) -> bool:
    """Return the decided TraceLab default for late-recorded scored forecasts."""

    cfg = config or load_run_config()
    policy = cfg["scorecard"]["late_recorded_policy"]
    return bool(policy["include_late_recorded_default"])
