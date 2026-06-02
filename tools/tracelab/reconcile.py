"""Reconcile env-gated dispatch JSONL traces against a read-only SQLite journal."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from trade_trace.replay_fingerprint import (
    ALGORITHM,
    DOMAIN,
    SCHEMA,
    VERSION,
    compute_replay_fingerprint,
)

EXPECTED_VALIDATION_PATTERN_KINDS = {"condition_id_hex64", "recoverable"}
SEEDED_ADAPTER_ERROR_REASONS = {"seeded_adapter_protocol_error", "seeded"}


def _connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    uri = f"{Path(db_path).resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _valid_replay_fingerprint_metadata(fp: dict[str, Any]) -> bool:
    return (
        fp.get("schema") == SCHEMA
        and fp.get("version") == VERSION
        and fp.get("domain") == DOMAIN
        and fp.get("algorithm") == ALGORITHM
    )


def _load_trace(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
    return records


def _count_table(conn: sqlite3.Connection, table: str, where: str, params: tuple[Any, ...]) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", params).fetchone()
    except sqlite3.Error:
        return 0
    return int(row["c"] if row is not None else 0)


def _events_by_request(conn: sqlite3.Connection, request_id: str) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT id, event_type, actor_id, idempotency_key, request_id FROM events WHERE request_id = ? ORDER BY id",
            (request_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def _events_by_fingerprint(conn: sqlite3.Connection, fp: dict[str, Any], secret: str | bytes | None, actor_id: str) -> list[dict[str, Any]]:
    if secret is None or not _valid_replay_fingerprint_metadata(fp) or not fp.get("event_type") or not fp.get("digest"):
        return []
    try:
        rows = conn.execute(
            "SELECT id, event_type, actor_id, idempotency_key, request_id FROM events "
            "WHERE event_type = ? AND actor_id = ? AND idempotency_key IS NOT NULL ORDER BY id",
            (fp["event_type"], actor_id),
        ).fetchall()
    except sqlite3.Error:
        return []
    matched: list[dict[str, Any]] = []
    for row in rows:
        computed = compute_replay_fingerprint(
            secret=secret,
            event_type=row["event_type"],
            actor_id=row["actor_id"],
            idempotency_key=row["idempotency_key"],
        )
        if computed["digest"] == fp["digest"]:
            clean = dict(row)
            clean.pop("idempotency_key", None)
            matched.append(clean)
    return matched


def reconcile(trace_path: str | Path, db_path: str | Path, *, replay_secret: str | bytes | None = None) -> dict[str, Any]:
    """Return a deterministic dispatch-to-journal reconciliation summary.

    Raw idempotency keys are read from SQLite only to recompute HMACs and are
    never included in the returned report.
    """

    records = _load_trace(trace_path)
    buckets: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    with _connect_readonly(db_path) as conn:
        for rec in records:
            request_id = str(rec.get("request_id") or "")
            tool = str(rec.get("tool") or "")
            events = _events_by_request(conn, request_id) if request_id else []
            for event in events:
                event.pop("idempotency_key", None)
            recall_rows = _count_table(conn, "memory_recall_events", "recall_id = ?", (request_id,)) if tool == "memory.recall" else 0
            bucket = "unclassified"
            prior_events: list[dict[str, Any]] = []
            if rec.get("dry_run"):
                bucket = "dry_run_zero_rows"
            elif rec.get("error_code") == "VALIDATION_ERROR" and rec.get("details", {}).get("pattern_kind"):
                bucket = "expected_validation_error_pattern"
            elif rec.get("error_code") == "ADAPTER_PROTOCOL_ERROR":
                reason = str(rec.get("details", {}).get("reason") or "")
                bucket = "seeded_adapter_protocol_error_excluded" if reason in SEEDED_ADAPTER_ERROR_REASONS else "adapter_protocol_error_flagged"
            elif tool == "memory.recall" and not events and recall_rows >= 1:
                bucket = "memory_recall_zero_events"
            elif events:
                bucket = "request_id_events"
            else:
                fp = rec.get("replay_fingerprint") if isinstance(rec.get("replay_fingerprint"), dict) else None
                prior_events = _events_by_fingerprint(conn, fp or {}, replay_secret, str(rec.get("actor_id") or ""))
                if prior_events:
                    bucket = "idempotent_replay_zero_new_rows"
                elif rec.get("ok") and not events:
                    bucket = "zero_events_unmapped"
            buckets[bucket] = buckets.get(bucket, 0) + 1
            items.append({
                "request_id": request_id,
                "tool": tool,
                "bucket": bucket,
                "event_count": len(events),
                "events": events,
                "prior_events": prior_events,
                "memory_recall_event_count": recall_rows,
            })
    return {"trace_count": len(records), "buckets": dict(sorted(buckets.items())), "items": items}
