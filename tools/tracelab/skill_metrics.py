"""Tracelab skill and native-rail adoption extractor.

This module intentionally treats read-rail adoption as *observational trace call
counts*. B1 dispatch traces record calls to report/bootstrap-style read tools,
but replay/JSONL reconstruction drops some signals and there are no durable read
rail events. Therefore the read-rail section is trace-only and must not be read
as a looked-before-leaped or causal precedence claim.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from trade_trace.storage.database import open_database_readonly, read_snapshot

READ_RAIL_TOOLS = {
    "report.bootstrap": "bootstrap",
    "report.work_queue": "work_queue",
    "report.coach": "coach",
    "report.mistake_tripwire": "mistake_tripwire",
    "report.calibration_advisory": "calibration_advisory",
}
CAVEATS = {
    "read_rail_adoption": (
        "Observational per-actor call counts from the live B1 dispatch trace only; "
        "not a causal precedence/looked-before-leaped claim and not reproducible "
        "from post-hoc replay/JSONL reconstruction."
    ),
    "write_rail_adoption": (
        "Derived from durable forecast_independence_locks records: "
        "blind_commit_seq, reveal_seq, and independence_proven."
    ),
}


def _iter_trace_records(trace_path: Path | str | None) -> Iterable[dict[str, Any]]:
    if trace_path is None:
        return
    path = Path(trace_path)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def count_read_rail_calls(trace_path: Path | str | None) -> dict[str, Any]:
    """Count read-rail tool calls per actor from the live dispatch trace."""
    per_actor: dict[str, Counter[str]] = defaultdict(Counter)
    totals: Counter[str] = Counter()
    for rec in _iter_trace_records(trace_path):
        tool = rec.get("tool")
        rail = READ_RAIL_TOOLS.get(str(tool))
        if rail is None:
            continue
        actor = str(rec.get("actor_id") or "<unknown>")
        per_actor[actor][rail] += 1
        totals[rail] += 1

    actors = {
        actor: {rail: counts.get(rail, 0) for rail in READ_RAIL_TOOLS.values()}
        for actor, counts in sorted(per_actor.items())
    }
    for actor, counts in actors.items():
        counts["total"] = sum(counts.values())
    return {
        "kind": "observational_call_counts",
        "trace_only": True,
        "not_replay_reproducible": True,
        "not_causal_precedence_claim": True,
        "caveat": CAVEATS["read_rail_adoption"],
        "tools_counted": sorted(READ_RAIL_TOOLS),
        "per_actor": actors,
        "totals": {rail: totals.get(rail, 0) for rail in READ_RAIL_TOOLS.values()},
    }


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def derive_write_rail_adoption(conn: sqlite3.Connection) -> dict[str, Any]:
    """Summarize durable write-rail forecast independence locks per actor."""
    if not _has_table(conn, "forecast_independence_locks"):
        return {"caveat": CAVEATS["write_rail_adoption"], "per_actor": {}, "totals": {}}
    rows = conn.execute(
        """
        SELECT actor_id, forecast_id, blind_commit_seq, reveal_seq, independence_proven
        FROM forecast_independence_locks
        ORDER BY actor_id, forecast_id
        """
    ).fetchall()
    per_actor: dict[str, dict[str, Any]] = {}
    proven_total = 0
    for actor, forecast_id, blind_seq, reveal_seq, proven in rows:
        bucket = per_actor.setdefault(str(actor), {
            "lock_count": 0,
            "independence_proven_count": 0,
            "rail_following_forecast_ids": [],
            "locks": [],
        })
        lock = {
            "forecast_id": forecast_id,
            "blind_commit_seq": blind_seq,
            "reveal_seq": reveal_seq,
            "independence_proven": bool(proven),
        }
        bucket["lock_count"] += 1
        bucket["locks"].append(lock)
        if blind_seq is not None and reveal_seq is not None and bool(proven):
            bucket["independence_proven_count"] += 1
            bucket["rail_following_forecast_ids"].append(forecast_id)
            proven_total += 1
    return {
        "caveat": CAVEATS["write_rail_adoption"],
        "per_actor": per_actor,
        "totals": {"lock_count": len(rows), "independence_proven_count": proven_total},
    }


def _actors(conn: sqlite3.Connection, trace_path: Path | str | None) -> list[str]:
    actors: set[str] = set()
    for table in ("forecasts", "decisions", "forecast_scores", "resolution_interpretations", "positions", "forecast_independence_locks"):
        if _has_table(conn, table):
            info = conn.execute(f"PRAGMA table_info({table})").fetchall()
            if any(row[1] == "actor_id" for row in info):
                actors.update(str(r[0]) for r in conn.execute(f"SELECT DISTINCT actor_id FROM {table} WHERE actor_id IS NOT NULL"))
    for rec in _iter_trace_records(trace_path):
        if rec.get("actor_id"):
            actors.add(str(rec["actor_id"]))
    return sorted(actors)


def _skill_for_actor(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if _has_table(conn, "forecast_scores") and _has_table(conn, "forecasts"):
        rows = conn.execute(
            """
            SELECT fs.score FROM forecast_scores fs
            JOIN forecasts f ON f.id = fs.forecast_id
            WHERE f.actor_id = ? AND fs.score IS NOT NULL
            """, (actor,),
        ).fetchall()
        scores = [float(r[0]) for r in rows]
        metrics["calibration"] = {
            "sample_size": len(scores),
            "mean_brier_score": round(sum(scores) / len(scores), 6) if scores else None,
            "source": "public report data: forecast_scores joined to forecasts by actor",
        }
    else:
        metrics["calibration"] = {"sample_size": 0, "mean_brier_score": None, "caveat": "required public report tables absent"}

    if _has_table(conn, "decisions") and _has_table(conn, "forecasts"):
        rows = conn.execute(
            """
            SELECT d.side, d.quantity, d.price, f.probability
            FROM decisions d JOIN forecasts f ON f.id = d.forecast_id
            WHERE d.actor_id = ? AND d.forecast_id IS NOT NULL AND d.quantity IS NOT NULL
              AND d.price IS NOT NULL AND f.probability IS NOT NULL
              AND d.type IN ('paper_enter','actual_enter','add')
            """, (actor,),
        ).fetchall()
        consistent = 0
        for side, _qty, price, p_yes in rows:
            win = 1.0 - float(p_yes) if str(side or "").lower() == "no" else float(p_yes)
            consistent += int((win - float(price)) > 0)
        metrics["process_quality"] = {
            "sample_size": len(rows),
            "direction_consistency_rate": round(consistent / len(rows), 6) if rows else None,
            "source": "public report data: decisions joined to forecasts by actor",
        }
    else:
        metrics["process_quality"] = {"sample_size": 0, "direction_consistency_rate": None, "caveat": "required public report tables absent"}

    if _has_table(conn, "resolution_interpretations"):
        total = conn.execute("SELECT COUNT(*) FROM resolution_interpretations WHERE actor_id = ?", (actor,)).fetchone()[0]
        metrics["resolution_misreads"] = {"sample_size": total, "source": "public report data: resolution_interpretations by actor"}
    else:
        metrics["resolution_misreads"] = {"sample_size": 0, "caveat": "required public report table absent"}

    if _has_table(conn, "positions"):
        info = conn.execute("PRAGMA table_info(positions)").fetchall()
        if any(row[1] == "actor_id" for row in info):
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(realized_pnl),0), COALESCE(SUM(unrealized_pnl),0) FROM positions WHERE actor_id = ?",
                (actor,),
            ).fetchone()
            metrics["pnl"] = {"sample_size": row[0], "realized_pnl": round(float(row[1]), 6), "unrealized_pnl": round(float(row[2]), 6), "source": "public report data: positions by actor"}
        else:
            metrics["pnl"] = {"sample_size": 0, "caveat": "positions has no actor_id; per-actor pnl unsupported by this schema"}
    else:
        metrics["pnl"] = {"sample_size": 0, "caveat": "required public report table absent"}
    return metrics


def build_skill_metrics(db_path: Path | str, trace_path: Path | str | None = None) -> dict[str, Any]:
    db = open_database_readonly(Path(db_path))
    try:
        with read_snapshot(db.connection) as conn:
            actors = _actors(conn, trace_path)
            return {
                "schema_version": 1,
                "caveats": CAVEATS,
                "skill_metrics": {actor: _skill_for_actor(conn, actor) for actor in actors},
                "write_rail_adoption": derive_write_rail_adoption(conn),
                "read_rail_adoption": count_read_rail_calls(trace_path),
            }
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Path to Trade Trace journal SQLite DB (opened read-only)")
    parser.add_argument("--trace", type=Path, help="Path to live B1 dispatch trace JSONL")
    args = parser.parse_args(argv)
    print(json.dumps(build_skill_metrics(args.db, args.trace), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
