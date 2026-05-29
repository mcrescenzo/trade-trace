"""Resolution-criteria interpretation as a first-class field (trade-trace-4kec.12).

`forecast.interpret_resolution` records the agent's READING of how a market will
resolve, at forecast time. `report.resolution_misreads` (in reports/) later
compares that reading to the actual resolution source, surfacing
"right about the world, wrong about the contract" as a distinct error class.
Append-only and idempotent.
"""

from __future__ import annotations

import json
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    open_db_for_args,
    require,
    store_metadata_json,
)
from trade_trace.tools.errors import ToolError

_EVENT = "forecast.resolution_interpreted"

# Interpreted source uses the same taxonomy markets resolve under, so the
# misread diagnostic compares like-for-like (market_bind._ALLOWED_RESOLUTION_SOURCES).
_ALLOWED_RESOLUTION_SOURCES = {"market_contract", "oracle_feed", "manual_review", "arbitration"}

_SELECT = (
    "SELECT id, forecast_id, instrument_id, interpreted_resolution_source, "
    "interpreted_yes_condition, expected_outcome_label, as_of, run_id, "
    "metadata_json, idempotency_key, created_at, actor_id "
    "FROM resolution_interpretations"
)


def _row_to_response(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "forecast_id": row[1],
        "instrument_id": row[2],
        "interpreted_resolution_source": row[3],
        "interpreted_yes_condition": row[4],
        "expected_outcome_label": row[5],
        "as_of": row[6],
        "run_id": row[7],
        "metadata": json.loads(row[8]),
        "idempotency_key": row[9],
        "created_at": row[10],
        "actor_id": row[11],
        "record_kind": "resolution_interpretation",
    }


def _response(conn: Any, interp_id: str) -> dict[str, Any]:
    row = conn.execute(f"{_SELECT} WHERE id = ?", (interp_id,)).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "resolution interpretation not found", details={"id": interp_id})
    return _row_to_response(row)


def _interpret_resolution(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    forecast_id = require(args, "forecast_id")
    interpreted_yes_condition = require(args, "interpreted_yes_condition")
    if not isinstance(interpreted_yes_condition, str) or not interpreted_yes_condition.strip():
        raise ToolError(ErrorCode.VALIDATION_ERROR, "interpreted_yes_condition must be a non-empty string", details={"field": "interpreted_yes_condition"})
    as_of = normalize_timestamp(args, "as_of", required=True)
    if as_of is None:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "as_of is required", details={"field": "as_of"})
    interpreted_source = args.get("interpreted_resolution_source")
    if interpreted_source is not None and interpreted_source not in _ALLOWED_RESOLUTION_SOURCES:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"interpreted_resolution_source must be one of {sorted(_ALLOWED_RESOLUTION_SOURCES)}",
            details={"field": "interpreted_resolution_source", "allowed": sorted(_ALLOWED_RESOLUTION_SOURCES)},
        )
    metadata_json = store_metadata_json(args, "metadata_json")
    idempotency_key = args.get("idempotency_key")

    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            conn = uow.conn
            row = conn.execute(
                "SELECT t.instrument_id FROM forecasts f JOIN theses t ON t.id = f.thesis_id WHERE f.id = ?",
                (forecast_id,),
            ).fetchone()
            if row is None:
                raise ToolError(ErrorCode.NOT_FOUND, "forecast_id not found", details={"forecast_id": forecast_id})
            instrument_id = row[0]
            replay = check_idempotency_replay(uow, event_type=_EVENT, actor_id=ctx.actor_id, idempotency_key=idempotency_key)
            if replay is not None:
                return _response(conn, replay["id"])
            existing = conn.execute(
                "SELECT id FROM resolution_interpretations WHERE forecast_id = ?", (forecast_id,)
            ).fetchone()
            if existing is not None:
                # One interpretation per forecast (the reading at forecast time).
                return _response(conn, existing[0])
            interp_id = args.get("id") or new_id("resint")
            created_at = now_iso()
            expected_label = args.get("expected_outcome_label")
            run_id = args.get("run_id")
            uow.execute(
                "INSERT INTO resolution_interpretations(id, forecast_id, instrument_id, interpreted_resolution_source, interpreted_yes_condition, expected_outcome_label, as_of, run_id, metadata_json, idempotency_key, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (interp_id, forecast_id, instrument_id, interpreted_source, interpreted_yes_condition, expected_label, as_of, run_id, metadata_json, idempotency_key, created_at, ctx.actor_id),
            )
            emit_event(
                uow, event_type=_EVENT, subject_kind="forecast", subject_id=forecast_id,
                payload={"id": interp_id, "forecast_id": forecast_id, "instrument_id": instrument_id, "interpreted_resolution_source": interpreted_source, "expected_outcome_label": expected_label, "as_of": as_of},
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
            return _response(conn, interp_id)
    finally:
        db.close()


def _get_interpretation(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    forecast_id = require(args, "forecast_id")
    db = open_db_for_args(args)
    try:
        row = db.connection.execute(f"{_SELECT} WHERE forecast_id = ?", (forecast_id,)).fetchone()
        if row is None:
            raise ToolError(ErrorCode.NOT_FOUND, "no resolution interpretation for forecast", details={"forecast_id": forecast_id})
        return _row_to_response(row)
    finally:
        db.close()


def register_resolution_interpretation_tools(registry: ToolRegistry) -> None:
    registry.register(
        "forecast.interpret_resolution",
        _interpret_resolution,
        is_write=True,
        description=(
            "Record the agent's reading of how a market will resolve, at forecast "
            "time (interpreted resolution source + YES condition). Later checked by "
            "report.resolution_misreads against the actual resolution source so "
            "'right about the world, wrong about the contract' is measurable. "
            "Append-only, idempotent; one interpretation per forecast."
        ),
        example_minimal={
            "forecast_id": "fc_FORECAST_ID_HERE",
            "interpreted_yes_condition": "Resolves YES if the AP calls the race for the candidate before Jan 20.",
            "interpreted_resolution_source": "oracle_feed",
            "as_of": "2027-01-02T00:00:00Z",
        },
        json_schema={
            "type": "object",
            "properties": {
                "forecast_id": {"type": "string"},
                "interpreted_yes_condition": {"type": "string", "description": "The agent's reading of what makes this resolve YES."},
                "interpreted_resolution_source": {"type": "string", "enum": sorted(_ALLOWED_RESOLUTION_SOURCES), "description": "The resolution-source category the agent believes will resolve it (same taxonomy as market.bind: market_contract/oracle_feed/manual_review/arbitration)."},
                "expected_outcome_label": {"type": "string", "description": "Optional: the outcome label the agent expects under its reading."},
                "as_of": {"type": "string"},
                "run_id": {"type": "string"},
                "metadata_json": {"type": "object"},
                "idempotency_key": {"type": "string"},
                "home": {"type": "string"},
            },
            "required": ["forecast_id", "interpreted_yes_condition", "as_of"],
        },
    )
    registry.register(
        "forecast.resolution_interpretation",
        _get_interpretation,
        description="Read the agent's recorded resolution-criteria interpretation for a forecast.",
        json_schema={"type": "object", "properties": {"forecast_id": {"type": "string"}, "home": {"type": "string"}}, "required": ["forecast_id"]},
    )


__all__ = ["register_resolution_interpretation_tools"]
