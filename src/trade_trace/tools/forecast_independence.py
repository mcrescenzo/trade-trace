"""Pre-commit forecast independence lock (trade-trace-4kec.9).

Two-step write path that proves a forecast was made BLIND to the market price:

1. `forecast.commit_blind` — assert a snapshot-less forecast is committed blind;
   emits an immutable `forecast.blind_committed` event (the ordering anchor T1).
2. `forecast.reveal_snapshot` — bind the market snapshot afterward, recording an
   append-only lock whose `reveal_seq > blind_commit_seq` proves the snapshot was
   revealed only after the forecast was committed.

`forecast.independence` reads the proof. This supersedes the frozen
`forecast.anchor_to_snapshot`, which linked a snapshot after the fact and proved
nothing about blindness.
"""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    db_for_args,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    require,
    store_metadata_json,
)
from trade_trace.tools.errors import ToolError

_BLIND_EVENT = "forecast.blind_committed"
_REVEAL_EVENT = "forecast.independence_revealed"


def _blind_commit_row(conn: Any, forecast_id: str) -> tuple[int, str] | None:
    """Return (event_seq, committed_at) of the forecast's blind-commit event."""

    row = conn.execute(
        "SELECT id, created_at FROM events "
        "WHERE subject_id = ? AND event_type = ? "
        "ORDER BY id ASC LIMIT 1",
        (forecast_id, _BLIND_EVENT),
    ).fetchone()
    return (int(row[0]), row[1]) if row is not None else None


def _has_snapshot_anchor(conn: Any, forecast_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM forecast_snapshot_anchor WHERE forecast_id = ?",
        (forecast_id,),
    ).fetchone() is not None


def _forecast_commit_blind(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    forecast_id = require(args, "forecast_id")
    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            conn = uow.conn
            if conn.execute("SELECT 1 FROM forecasts WHERE id = ?", (forecast_id,)).fetchone() is None:
                raise ToolError(ErrorCode.NOT_FOUND, "forecast_id not found", details={"forecast_id": forecast_id})
            if _has_snapshot_anchor(conn, forecast_id):
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    "forecast already has a market snapshot anchor; it was not committed blind",
                    details={"forecast_id": forecast_id},
                )
            existing = _blind_commit_row(conn, forecast_id)
            if existing is not None:
                return {
                    "forecast_id": forecast_id,
                    "blind_committed_at": existing[1],
                    "blind_commit_seq": existing[0],
                    "already_committed": True,
                }
            committed_at = normalize_timestamp(args, "as_of") or now_iso()
            emit_event(
                uow,
                event_type=_BLIND_EVENT,
                subject_kind="forecast",
                subject_id=forecast_id,
                payload={"forecast_id": forecast_id, "blind_committed_at": committed_at},
                actor_id=ctx.actor_id,
                idempotency_key=args.get("idempotency_key"),
                ctx=ctx,
            )
            committed = _blind_commit_row(conn, forecast_id)
            assert committed is not None  # just emitted
            return {
                "forecast_id": forecast_id,
                "blind_committed_at": committed[1],
                "blind_commit_seq": committed[0],
                "already_committed": False,
            }


def _lock_response(conn: Any, forecast_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, forecast_id, snapshot_id, blind_committed_at, blind_commit_seq, "
        "revealed_at, reveal_seq, independence_proven, created_at, actor_id "
        "FROM forecast_independence_locks WHERE forecast_id = ?",
        (forecast_id,),
    ).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "no independence lock for forecast", details={"forecast_id": forecast_id})
    return {
        "id": row[0],
        "forecast_id": row[1],
        "snapshot_id": row[2],
        "blind_committed_at": row[3],
        "blind_commit_seq": row[4],
        "revealed_at": row[5],
        "reveal_seq": row[6],
        "independence_proven": bool(row[7]),
        "created_at": row[8],
        "actor_id": row[9],
        "record_kind": "forecast_independence_lock",
    }


def _forecast_reveal_snapshot(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    forecast_id = require(args, "forecast_id")
    snapshot_id = require(args, "snapshot_id")
    metadata_json = store_metadata_json(args, "metadata_json")
    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            conn = uow.conn
            if conn.execute("SELECT 1 FROM forecasts WHERE id = ?", (forecast_id,)).fetchone() is None:
                raise ToolError(ErrorCode.NOT_FOUND, "forecast_id not found", details={"forecast_id": forecast_id})
            if conn.execute("SELECT 1 FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone() is None:
                raise ToolError(ErrorCode.NOT_FOUND, "snapshot_id not found", details={"snapshot_id": snapshot_id})
            commit = _blind_commit_row(conn, forecast_id)
            if commit is None:
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    "forecast was not committed blind; call forecast.commit_blind first",
                    details={"forecast_id": forecast_id},
                )
            if conn.execute(
                "SELECT 1 FROM forecast_independence_locks WHERE forecast_id = ?",
                (forecast_id,),
            ).fetchone() is not None:
                # Idempotent: a snapshot was already revealed for this forecast.
                return _lock_response(conn, forecast_id)
            blind_commit_seq, blind_committed_at = commit
            revealed_at = normalize_timestamp(args, "as_of") or now_iso()
            emit_event(
                uow,
                event_type=_REVEAL_EVENT,
                subject_kind="forecast",
                subject_id=forecast_id,
                payload={"forecast_id": forecast_id, "snapshot_id": snapshot_id, "revealed_at": revealed_at},
                actor_id=ctx.actor_id,
                idempotency_key=args.get("idempotency_key"),
                ctx=ctx,
            )
            reveal_row = conn.execute(
                "SELECT id FROM events WHERE subject_id = ? AND event_type = ? "
                "ORDER BY id DESC LIMIT 1",
                (forecast_id, _REVEAL_EVENT),
            ).fetchone()
            reveal_seq = int(reveal_row[0])
            # Temporal independence is enforced at write time: the reveal event
            # must be strictly after the blind-commit event in the immutable log.
            independence_proven = 1 if reveal_seq > blind_commit_seq else 0
            if not independence_proven:
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    "could not prove temporal independence: reveal did not follow the blind commit",
                    details={"forecast_id": forecast_id, "blind_commit_seq": blind_commit_seq, "reveal_seq": reveal_seq},
                )
            lock_id = args.get("id") or new_id("filock")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO forecast_independence_locks(id, forecast_id, snapshot_id, blind_committed_at, blind_commit_seq, revealed_at, reveal_seq, independence_proven, run_id, metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (lock_id, forecast_id, snapshot_id, blind_committed_at, blind_commit_seq, revealed_at, reveal_seq, independence_proven, args.get("run_id"), metadata_json, created_at, ctx.actor_id),
            )
            return _lock_response(conn, forecast_id)


def _forecast_independence(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    forecast_id = require(args, "forecast_id")
    with db_for_args(args) as db:
        conn = db.connection
        if conn.execute("SELECT 1 FROM forecasts WHERE id = ?", (forecast_id,)).fetchone() is None:
            raise ToolError(ErrorCode.NOT_FOUND, "forecast_id not found", details={"forecast_id": forecast_id})
        lock = conn.execute(
            "SELECT 1 FROM forecast_independence_locks WHERE forecast_id = ?",
            (forecast_id,),
        ).fetchone()
        if lock is not None:
            return {"status": "revealed", **_lock_response(conn, forecast_id)}
        commit = _blind_commit_row(conn, forecast_id)
        if commit is not None:
            return {
                "status": "blind_committed",
                "forecast_id": forecast_id,
                "blind_committed_at": commit[1],
                "blind_commit_seq": commit[0],
                "independence_proven": False,
            }
        return {"status": "no_blind_commit", "forecast_id": forecast_id, "independence_proven": False}


def register_forecast_independence_tools(registry: ToolRegistry) -> None:
    registry.register(
        "forecast.commit_blind",
        _forecast_commit_blind,
        is_write=True,
        description=(
            "Mark a snapshot-less forecast as committed BLIND to the market price, "
            "emitting an immutable ordering anchor. Pair with forecast.reveal_snapshot "
            "to prove the forecast preceded the market snapshot. Supersedes "
            "forecast.anchor_to_snapshot, which proved nothing about blindness."
        ),
        example_minimal={"forecast_id": "fc_FORECAST_ID_HERE"},
        json_schema={
            "type": "object",
            "properties": {
                "forecast_id": {"type": "string"},
                "as_of": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "home": {"type": "string"},
            },
            "required": ["forecast_id"],
        },
    )
    registry.register(
        "forecast.reveal_snapshot",
        _forecast_reveal_snapshot,
        is_write=True,
        description=(
            "Reveal/bind a market snapshot to a previously blind-committed forecast, "
            "recording an append-only independence lock whose reveal_seq > "
            "blind_commit_seq proves the snapshot was seen only after the forecast. "
            "Refuses if the forecast was not committed blind."
        ),
        example_minimal={"forecast_id": "fc_FORECAST_ID_HERE", "snapshot_id": "snp_SNAPSHOT_ID_HERE"},
        json_schema={
            "type": "object",
            "properties": {
                "forecast_id": {"type": "string"},
                "snapshot_id": {"type": "string"},
                "as_of": {"type": "string"},
                "run_id": {"type": "string"},
                "metadata_json": {"type": "object"},
                "idempotency_key": {"type": "string"},
                "home": {"type": "string"},
            },
            "required": ["forecast_id", "snapshot_id"],
        },
    )
    registry.register(
        "forecast.independence",
        _forecast_independence,
        description=(
            "Read the independence proof for a forecast: revealed (with the lock and "
            "proven flag), blind_committed (awaiting reveal), or no_blind_commit."
        ),
        json_schema={"type": "object", "properties": {"forecast_id": {"type": "string"}, "home": {"type": "string"}}, "required": ["forecast_id"]},
    )


__all__ = ["register_forecast_independence_tools"]
