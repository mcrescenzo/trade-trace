"""First-class abstention / no-bet records (trade-trace-4kec.8).

Recording a "considered and passed" decision against a market keeps the
calibration denominator honest: without abstentions, calibration is
survivorship-biased toward the forecasts the agent chose to commit. Records are
append-only and idempotent like every other journal write.
"""

from __future__ import annotations

import json
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    db_for_args,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    require,
    store_metadata_json,
)
from trade_trace.tools.errors import ToolError

_EVENT = "abstention.recorded"


def _row_to_response(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "instrument_id": row[1],
        "thesis_id": row[2],
        "reason": row[3],
        "considered_probability": row[4],
        "as_of": row[5],
        "run_id": row[6],
        "metadata": json.loads(row[7]),
        "idempotency_key": row[8],
        "created_at": row[9],
        "actor_id": row[10],
        "record_kind": "abstention",
    }


_SELECT = (
    "SELECT id, instrument_id, thesis_id, reason, considered_probability, "
    "as_of, run_id, metadata_json, idempotency_key, created_at, actor_id "
    "FROM abstentions"
)


def _response(conn: Any, abstention_id: str) -> dict[str, Any]:
    row = conn.execute(f"{_SELECT} WHERE id = ?", (abstention_id,)).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "abstention not found", details={"id": abstention_id})
    return _row_to_response(row)


def _abstention_record(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    instrument_id = require(args, "instrument_id")
    reason = require(args, "reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ToolError(ErrorCode.VALIDATION_ERROR, "reason must be a non-empty string", details={"field": "reason"})
    considered_probability = args.get("considered_probability")
    if considered_probability is not None:
        if isinstance(considered_probability, bool) or not isinstance(considered_probability, (int, float)):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "considered_probability must be a number in [0, 1]", details={"field": "considered_probability"})
        if not (0.0 <= float(considered_probability) <= 1.0):
            raise ToolError(ErrorCode.VALIDATION_ERROR, "considered_probability must be in [0, 1]", details={"field": "considered_probability"})
        considered_probability = float(considered_probability)
    as_of = normalize_timestamp(args, "as_of", required=True)
    if as_of is None:  # normalize_timestamp(required=True) narrows at runtime.
        raise ToolError(ErrorCode.VALIDATION_ERROR, "as_of is required", details={"field": "as_of"})
    metadata_json = store_metadata_json(args, "metadata_json")
    idempotency_key = args.get("idempotency_key")
    thesis_id = args.get("thesis_id")
    run_id = args.get("run_id")

    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            if uow.conn.execute("SELECT 1 FROM instruments WHERE id = ?", (instrument_id,)).fetchone() is None:
                raise ToolError(ErrorCode.VALIDATION_ERROR, "abstention references missing instrument", details={"field": "instrument_id", "id": instrument_id})
            if thesis_id and uow.conn.execute("SELECT 1 FROM theses WHERE id = ?", (thesis_id,)).fetchone() is None:
                raise ToolError(ErrorCode.VALIDATION_ERROR, "abstention references missing thesis", details={"field": "thesis_id", "id": thesis_id})
            replay = check_idempotency_replay(uow, event_type=_EVENT, actor_id=ctx.actor_id, idempotency_key=idempotency_key)
            if replay is not None:
                return _response(uow.conn, replay["id"])
            abstention_id = args.get("id") or new_id("abst")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO abstentions(id, instrument_id, thesis_id, reason, considered_probability, as_of, run_id, metadata_json, idempotency_key, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (abstention_id, instrument_id, thesis_id, reason, considered_probability, as_of, run_id, metadata_json, idempotency_key, created_at, ctx.actor_id),
            )
            payload = {
                "id": abstention_id,
                "instrument_id": instrument_id,
                "thesis_id": thesis_id,
                "reason": reason,
                "considered_probability": considered_probability,
                "as_of": as_of,
                "run_id": run_id,
                "idempotency_key": idempotency_key,
            }
            emit_event(uow, event_type=_EVENT, subject_kind="abstention", subject_id=abstention_id, payload=payload, actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx)
            return _response(uow.conn, abstention_id)


def _abstention_get(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    abstention_id = require(args, "id")
    with db_for_args(args) as db:
        return _response(db.connection, abstention_id)


def _abstention_list(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    limit = min(int(args.get("limit", 50)), 200)
    with db_for_args(args) as db:
        where = []
        params: list[Any] = []
        for field in ("instrument_id", "thesis_id", "run_id"):
            if args.get(field):
                where.append(f"{field} = ?")
                params.append(args[field])
        sql = _SELECT
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        rows = db.connection.execute(sql, (*params, limit)).fetchall()
        return {"records": [_row_to_response(row) for row in rows], "count": len(rows), "record_kind": "abstention"}


def register_abstention_tools(registry: ToolRegistry) -> None:
    registry.register(
        "abstention.record",
        _abstention_record,
        is_write=True,
        description=(
            "Record a first-class abstention (considered-and-passed) against a "
            "market with a reason, so the calibration denominator reflects "
            "declined forecasts and is not survivorship-biased. Append-only and "
            "idempotent; this is a journal record, not trade activity."
        ),
        example_minimal={
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "reason": "spread too wide vs my edge",
            "as_of": "2027-01-05T00:00:00Z",
        },
        example_rich={
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "thesis_id": "th_THESIS_ID_HERE",
            "reason": "resolution criteria too ambiguous to forecast",
            "considered_probability": 0.55,
            "as_of": "2027-01-05T00:00:00Z",
            "run_id": "run_42",
            "metadata_json": {"tags": ["ambiguous_rules"]},
        },
        json_schema={
            "type": "object",
            "properties": {
                "instrument_id": {"type": "string"},
                "thesis_id": {"type": "string"},
                "reason": {"type": "string", "description": "Why the agent considered and declined to forecast/bet."},
                "considered_probability": {"type": "number", "minimum": 0, "maximum": 1, "description": "Optional probability the agent considered before passing."},
                "as_of": {"type": "string"},
                "run_id": {"type": "string"},
                "metadata_json": {"type": "object"},
                "idempotency_key": {"type": "string"},
                "home": {"type": "string"},
            },
            "required": ["instrument_id", "reason", "as_of"],
        },
    )
    registry.register(
        "abstention.get",
        _abstention_get,
        description="Read one abstention (considered-and-passed) record by id.",
        json_schema={"type": "object", "properties": {"id": {"type": "string"}, "home": {"type": "string"}}, "required": ["id"]},
    )
    registry.register(
        "abstention.list",
        _abstention_list,
        description="List abstention records, optionally filtered by instrument_id, thesis_id, or run_id.",
        json_schema={"type": "object", "properties": {"instrument_id": {"type": "string"}, "thesis_id": {"type": "string"}, "run_id": {"type": "string"}, "limit": {"type": "integer"}, "home": {"type": "string"}}},
    )


__all__ = ["register_abstention_tools"]
