"""Read-only health snapshots for Trade Trace tracelab runs.

This sidecar intentionally uses the read-only database entrypoint. It never
migrates, never writes to SQLite, and appends JSONL health observations to an
operator-provided file.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trade_trace.mcp_server import mcp_call as default_mcp_call
from trade_trace.storage.database import open_database_readonly, read_snapshot
from trade_trace.storage.paths import db_path, resolve_home

DiskUsageFn = Callable[[Path], Any]
StatVfsFn = Callable[[Path], Any]
McpCallFn = Callable[[str, dict[str, Any]], Any]


@dataclass(frozen=True)
class Thresholds:
    """Alarm thresholds for filesystem health."""

    min_free_bytes: int = 0
    min_free_inodes: int = 0


@dataclass(frozen=True)
class CanaryConfig:
    """Gamma schema canary configuration.

    The canary calls ``snapshot.fetch`` through an injectable MCP caller so
    tests and offline runs can exercise the contract without live networking.
    """

    home: str
    market_id: str
    enabled: bool = True
    mcp_call: McpCallFn = default_mcp_call


@dataclass(frozen=True)
class HealthSnapshotConfig:
    home: Path
    output_path: Path
    thresholds: Thresholds = field(default_factory=Thresholds)
    canary: CanaryConfig | None = None


def _count(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row is not None else 0


def collect_db_counts(db_file: Path) -> dict[str, int]:
    """Collect health counts through a read-only/query-only connection."""

    db = open_database_readonly(db_file)
    try:
        conn = db.connection
        with read_snapshot(conn):
            return {
                "events": _count(conn, "SELECT COUNT(*) FROM events"),
                "forecast_scores": _count(conn, "SELECT COUNT(*) FROM forecast_scores"),
                "positions_open": _count(conn, "SELECT COUNT(*) FROM positions WHERE status IN ('open','partial')"),
                "positions_closed": _count(conn, "SELECT COUNT(*) FROM positions WHERE status NOT IN ('open','partial')"),
                "outbox_backlog": _count(conn, "SELECT COUNT(*) FROM outbox WHERE state IN ('pending','failed')"),
                "resolved_but_unclosed_forecasts": _count(
                    conn,
                    """
                    SELECT COUNT(DISTINCT f.id)
                    FROM forecasts f
                    JOIN theses t ON t.id = f.thesis_id
                    JOIN outcomes o ON o.instrument_id = t.instrument_id
                    WHERE o.status IN ('resolved_final','resolved_provisional')
                      AND f.scoring_state != 'scored'
                      AND NOT EXISTS (
                          SELECT 1 FROM forecast_scores fs WHERE fs.forecast_id = f.id
                      )
                    """,
                ),
            }
    finally:
        db.close()


def collect_filesystem_health(
    path: Path,
    *,
    thresholds: Thresholds,
    disk_usage: DiskUsageFn = shutil.disk_usage,
    statvfs: StatVfsFn | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Return free disk/inode metrics and threshold alarms."""

    usage = disk_usage(path)
    if statvfs is None:
        statvfs = os.statvfs
    vfs = statvfs(path)
    metrics = {"free_disk_bytes": int(usage.free), "free_inodes": int(vfs.f_favail)}
    alarms: list[dict[str, Any]] = []
    if metrics["free_disk_bytes"] < thresholds.min_free_bytes:
        alarms.append({"code": "LOW_FREE_DISK", "value": metrics["free_disk_bytes"], "threshold": thresholds.min_free_bytes})
    if metrics["free_inodes"] < thresholds.min_free_inodes:
        alarms.append({"code": "LOW_FREE_INODES", "value": metrics["free_inodes"], "threshold": thresholds.min_free_inodes})
    return metrics, alarms


def _env_ok(env: Any) -> bool:
    return bool(getattr(env, "ok", False) if not isinstance(env, Mapping) else env.get("ok"))


def _env_data(env: Any) -> Mapping[str, Any]:
    data = getattr(env, "data", None) if not isinstance(env, Mapping) else env.get("data")
    return data if isinstance(data, Mapping) else {}


def run_gamma_canary(config: CanaryConfig) -> dict[str, Any]:
    """Assert ``snapshot.fetch`` still returns a valid binary-market snapshot."""

    if not config.enabled:
        return {"enabled": False, "ok": True}
    env = config.mcp_call("snapshot.fetch", {"home": config.home, "market_id": config.market_id, "at": "now"})
    if not _env_ok(env):
        raise RuntimeError("Gamma canary snapshot.fetch failed")
    data = _env_data(env)
    probability = data.get("implied_probability", data.get("mid", data.get("price")))
    if not isinstance(probability, int | float) or not 0.0 <= float(probability) <= 1.0:
        raise RuntimeError("Gamma canary schema drift: missing valid implied probability")
    outcomes = None
    metadata = data.get("metadata_json")
    if "outcomes" in data:
        outcomes = data.get("outcomes")
    elif isinstance(metadata, Mapping):
        outcomes = metadata.get("outcomes")
    if outcomes is not None and list(outcomes) != ["Yes", "No"]:
        raise RuntimeError("Gamma canary schema drift: expected binary Yes/No outcomes")
    for key in ("instrument_id", "bid", "ask"):
        if key not in data:
            raise RuntimeError(f"Gamma canary schema drift: missing {key}")
    return {"enabled": True, "ok": True, "market_id": config.market_id}


def take_snapshot(
    config: HealthSnapshotConfig,
    *,
    now: Callable[[], datetime] | None = None,
    disk_usage: DiskUsageFn = shutil.disk_usage,
    statvfs: StatVfsFn | None = None,
) -> dict[str, Any]:
    """Collect one snapshot and append it as JSONL."""

    now = now or (lambda: datetime.now(UTC))
    db_file = db_path(config.home)
    counts = collect_db_counts(db_file)
    fs_metrics, alarms = collect_filesystem_health(config.home, thresholds=config.thresholds, disk_usage=disk_usage, statvfs=statvfs)
    canary_result = None
    if config.canary is not None:
        try:
            canary_result = run_gamma_canary(config.canary)
        except Exception as exc:  # noqa: BLE001 - sidecar records canary alarms
            canary_result = {"enabled": config.canary.enabled, "ok": False, "error": str(exc)}
            alarms.append({"code": "GAMMA_SCHEMA_CANARY", "message": str(exc)})
    snapshot = {
        "captured_at": now().isoformat().replace("+00:00", "Z"),
        "db_path": str(db_file),
        "counts": counts,
        "filesystem": fs_metrics,
        "canary": canary_result,
        "alarms": alarms,
    }
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    with config.output_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot, sort_keys=True) + "\n")
    return snapshot


def run_periodic(config: HealthSnapshotConfig, *, interval_seconds: float, iterations: int | None = None) -> None:
    completed = 0
    while iterations is None or completed < iterations:
        take_snapshot(config)
        completed += 1
        if iterations is None or completed < iterations:
            time.sleep(interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append read-only Trade Trace health snapshots as JSONL")
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--min-free-bytes", type=int, default=0)
    parser.add_argument("--min-free-inodes", type=int, default=0)
    parser.add_argument("--canary-market-id")
    args = parser.parse_args(argv)
    home = resolve_home(args.home)
    canary = CanaryConfig(home=str(home), market_id=args.canary_market_id) if args.canary_market_id else None
    config = HealthSnapshotConfig(
        home=home,
        output_path=args.output,
        thresholds=Thresholds(args.min_free_bytes, args.min_free_inodes),
        canary=canary,
    )
    run_periodic(config, interval_seconds=args.interval_seconds, iterations=args.iterations)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
