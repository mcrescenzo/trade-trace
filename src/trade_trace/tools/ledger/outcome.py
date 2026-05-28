"""`outcome.add` (alias `resolve.record`) and `resolve.pending` handlers.

Extracted from `tools/ledger/__init__.py` per bead trade-trace-mit5.
`outcome.add` writes the outcome row, emits `outcome.recorded`, and on
`status='resolved_final'` calls the auto-scoring helpers in `_scoring.py`
to score any pending forecasts for the instrument. `resolve.pending`
lists forecasts past their resolution_at without a final outcome.
"""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    common_metadata,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    open_db_for_args,
    require,
    store_metadata_json,
)
from trade_trace.tools.errors import ToolError
from trade_trace.tools.ledger._finality import (
    finality_uncertain_for_outcome as _finality_uncertain_for_outcome,
)
from trade_trace.tools.ledger._finality import (
    is_auto_scoreable_final as _is_auto_scoreable_final,
)
from trade_trace.tools.ledger._scoring import (
    _autoscore_pending_forecasts,
    _emit_forecast_scored,
)
from trade_trace.tools.ledger._shared import examples_for

_OUTCOME_STATUSES = {
    "resolved_final", "resolved_provisional", "proposed", "provisional",
    "disputed", "ambiguous", "void", "cancelled",
    "imported_redeemed", "imported_settled",
}
def _outcome_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    instrument_id = require(args, "instrument_id")
    resolved_at = normalize_timestamp(args, "resolved_at", required=True)
    outcome_label = require(args, "outcome_label")
    status = require(args, "status")
    if status not in _OUTCOME_STATUSES:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"status must be one of {sorted(_OUTCOME_STATUSES)!r}",
            details={"field": "status", "value": status, "allowed": sorted(_OUTCOME_STATUSES)},
        )
    idempotency_key = args.get("idempotency_key")
    seg = common_metadata(args)
    metadata_json = store_metadata_json(args)

    def _payload(oid: str) -> dict[str, Any]:
        return {
            "id": oid,
            "instrument_id": instrument_id,
            "resolved_at": resolved_at,
            "outcome_label": outcome_label,
            "outcome_value": args.get("outcome_value"),
            "status": status,
            "source": args.get("source", "manual"),
            "confidence": args.get("confidence"),
        }

    db = open_db_for_args(args)
    auto_scored: list[dict[str, Any]] = []
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="outcome.recorded",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                outcome_id = replay["id"]
                emit_event(
                    uow, event_type="outcome.recorded",
                    subject_kind="outcome", subject_id=outcome_id,
                    payload=_payload(outcome_id),
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    """
                    SELECT instrument_id, resolved_at, outcome_label, status, confidence, created_at
                    FROM outcomes WHERE id = ?
                    """,
                    (outcome_id,),
                ).fetchone()
                row_instrument_id, row_resolved_at, row_label, row_status, row_confidence, row_created_at = row
                return {"id": outcome_id, "instrument_id": row_instrument_id,
                        "status": row_status, "resolved_at": row_resolved_at,
                        "auto_scored_forecasts": [],
                        "auto_scoreable": _is_auto_scoreable_final(
                            status=row_status, confidence=row_confidence, outcome_label=row_label,
                        ),
                        "finality_uncertain": _finality_uncertain_for_outcome(
                            status=row_status, confidence=row_confidence, outcome_label=row_label,
                        ),
                        "created_at": row_created_at}

            outcome_id = args.get("id") or new_id("out")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, "
                "outcome_value, status, source, confidence, agent_id, model_id, "
                "environment, run_id, metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    outcome_id, instrument_id, resolved_at, outcome_label,
                    args.get("outcome_value"), status,
                    args.get("source", "manual"), args.get("confidence"),
                    seg["agent_id"], seg["model_id"], seg["environment"], seg["run_id"],
                    metadata_json, created_at, ctx.actor_id,
                ),
            )
            emit_event(
                uow, event_type="outcome.recorded",
                subject_kind="outcome", subject_id=outcome_id,
                payload=_payload(outcome_id),
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
            # Auto-scoring per scoring.md §6 / §5 hard invariant, hardened for
            # PM finality: only final, high-confidence, label-mapped outcomes.
            if _is_auto_scoreable_final(
                status=status, confidence=args.get("confidence"), outcome_label=outcome_label,
            ):
                auto_scored = _autoscore_pending_forecasts(
                    uow.conn,
                    instrument_id=instrument_id,
                    outcome_id=outcome_id,
                    outcome_label=outcome_label,
                    actor_id=ctx.actor_id,
                    created_at=created_at,
                )
                for score in auto_scored:
                    _emit_forecast_scored(
                        uow, score, actor_id=ctx.actor_id, ctx=ctx,
                        scored_at=created_at,
                    )
    finally:
        db.close()
    return {"id": outcome_id, "instrument_id": instrument_id, "status": status,
            "resolved_at": resolved_at, "auto_scored_forecasts": auto_scored,
            "auto_scoreable": _is_auto_scoreable_final(status=status, confidence=args.get("confidence"), outcome_label=outcome_label),
            "finality_uncertain": _finality_uncertain_for_outcome(status=status, confidence=args.get("confidence"), outcome_label=outcome_label),
            "created_at": created_at}


def _resolve_pending(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """List forecasts past their resolution_at without a `resolved_final`
    outcome row. Deterministic ordering per PRD §4.4 / kyr acceptance:
    ORDER BY resolution_at ASC, forecast_id ASC."""

    limit = int(args.get("limit", 100))
    if limit < 1 or limit > 1000:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "limit must be between 1 and 1000",
            details={"field": "limit", "value": limit},
        )
    db = open_db_for_args(args)
    try:
        cur = db.connection.execute(
            """
            SELECT f.id, f.thesis_id, f.kind, f.resolution_at, t.instrument_id
            FROM forecasts f
            JOIN theses t ON t.id = f.thesis_id
            WHERE f.resolution_at IS NOT NULL
              AND f.scoring_state = 'pending'
            ORDER BY f.resolution_at ASC, f.id ASC
            """,
        )
        items = []
        for row in cur.fetchall():
            safe_final = db.connection.execute(
                """
                SELECT status, confidence, outcome_label
                FROM outcomes
                WHERE instrument_id = ? AND status = 'resolved_final'
                ORDER BY resolved_at DESC, created_at DESC, id DESC
                """,
                (row[4],),
            ).fetchall()
            if any(
                _is_auto_scoreable_final(status=r[0], confidence=r[1], outcome_label=r[2])
                for r in safe_final
            ):
                continue
            items.append({
                "forecast_id": row[0],
                "thesis_id": row[1],
                "kind": row[2],
                "resolution_at": row[3],
                "instrument_id": row[4],
            })
            if len(items) >= limit:
                break
    finally:
        db.close()
    return {"items": items, "count": len(items), "truncated": len(items) == limit}


def register_outcome_tools(registry: ToolRegistry) -> None:
    registry.register(
        "outcome.add", _outcome_add, is_write=True,
        **examples_for("outcome.add"),
    )
    # resolve.record is an alias for outcome.add (PRD §4.4).
    registry.register(
        "resolve.record", _outcome_add, is_write=True,
        **examples_for("outcome.add"),
    )
    registry.register("resolve.pending", _resolve_pending)
