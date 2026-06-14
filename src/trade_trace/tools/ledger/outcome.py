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
    db_for_args,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    require,
    store_metadata_json,
)
from trade_trace.tools.errors import ToolError
from trade_trace.tools.ledger._finality import (
    auto_score_block_reason as _auto_score_block_reason,
)
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

# Advertise the status enum (and the auto-score-gating confidence field) in the
# MCP tool.schema. Without an explicit schema the registration auto-derives from
# example_minimal, exposing status as a bare string even though the runtime
# rejects out-of-enum values with a self-documenting error — the AX-051 class
# (cf. memory.link). Also surfaces confidence in properties, not just
# example_rich, closing the AX-030 discoverability residual. AX-054.
_OUTCOME_ADD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "instrument_id": {"type": "string"},
        "resolved_at": {"type": "string"},
        "outcome_label": {"type": "string", "description": "Resolved outcome label; a binary label (yes/no/true/false) is required for a resolved_final outcome to auto-score a pending binary forecast."},
        "status": {"type": "string", "enum": sorted(_OUTCOME_STATUSES), "description": "Resolution status; must be one of the documented enum. Only resolved_final auto-scores pending forecasts."},
        "outcome_value": {"type": "number"},
        "confidence": {"type": "number", "description": "Caller's certainty in the outcome (0..1). REQUIRED >= 0.9 (with a binary outcome_label and status=resolved_final) for a resolved outcome to auto-score a pending binary forecast; omit it and the write succeeds but scores nothing (see auto_score_skipped_reason on the result)."},
        "settlement_price": {"type": "number"},
        "resolution_source_url": {"type": "string"},
        "source": {"type": "string"},
        "metadata_json": {"type": "object"},
        "idempotency_key": {"type": "string"},
        "agent_id": {"type": "string"},
        "model_id": {"type": "string"},
        "run_id": {"type": "string"},
        "environment": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["instrument_id", "resolved_at", "outcome_label", "status", "idempotency_key"],
}


def _outcome_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    instrument_id = require(args, "instrument_id")
    resolved_at = normalize_timestamp(args, "resolved_at", required=True)
    # Normalize the outcome_label at write time so a whitespace-padded or
    # whitespace-only label cannot be persisted. is_auto_scoreable_final()
    # already strips before comparing, but the raw (un-stripped) string would
    # otherwise land in the append-only outcomes row, leaving a label like
    # " yes " or "   " that no later reader can match cleanly (trade-trace-1k5d).
    outcome_label = require(args, "outcome_label").strip()
    if not outcome_label:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "outcome_label must not be empty or whitespace-only",
            details={"field": "outcome_label"},
        )
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

    auto_scored: list[dict[str, Any]] = []
    with db_for_args(args) as db:
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
                        "auto_score_skipped_reason": _auto_score_block_reason(
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
    return {"id": outcome_id, "instrument_id": instrument_id, "status": status,
            "resolved_at": resolved_at, "auto_scored_forecasts": auto_scored,
            "auto_scoreable": _is_auto_scoreable_final(status=status, confidence=args.get("confidence"), outcome_label=outcome_label),
            "auto_score_skipped_reason": _auto_score_block_reason(status=status, confidence=args.get("confidence"), outcome_label=outcome_label),
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
    # PRD §4.4: resolve.pending lists forecasts whose resolution_at has
    # ALREADY PASSED ("past their resolution_at") and remain unscored. A
    # future-dated forecast is not yet resolvable, so it must not leak into
    # this work queue. Bind the cutoff to now_iso() (which honors the
    # CLOCK_OVERRIDE used by tests) rather than SQL strftime('now'), so the
    # filter stays deterministic under a frozen clock.
    now = now_iso()
    with db_for_args(args) as db:
        # NOTE: forecasts.scoring_state is append-only (the m003/m014
        # trigger forbids UPDATE), so it never leaves 'pending' on disk;
        # the logical state is projected at read time by
        # derive_scoring_state(). A `WHERE f.scoring_state = 'pending'`
        # clause here would be a no-op that filters nothing while implying
        # already-scored forecasts are excluded (trade-trace-2b0z). We
        # instead exclude logically-scored forecasts with an accurate
        # NOT EXISTS over forecast_scores: a non-NULL score against an
        # outcome that has not itself been superseded == logically
        # 'scored' per derive_scoring_state(). Forecasts that are
        # logically pending/failed/superseded-outcome remain in the list.
        cur = db.connection.execute(
            """
            SELECT f.id, f.thesis_id, f.kind, f.resolution_at, t.instrument_id
            FROM forecasts f
            JOIN theses t ON t.id = f.thesis_id
            WHERE f.resolution_at IS NOT NULL
              AND f.resolution_at <= ?
              AND NOT EXISTS (
                SELECT 1 FROM forecast_scores fs
                WHERE fs.forecast_id = f.id
                  AND fs.score IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM edges e
                    WHERE e.source_kind = 'outcome' AND e.target_kind = 'outcome'
                      AND e.edge_type = 'supersedes' AND e.target_id = fs.outcome_id
                  )
              )
            ORDER BY f.resolution_at ASC, f.id ASC
            """,
            (now,),
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
    return {"items": items, "count": len(items), "truncated": len(items) == limit}


def register_outcome_tools(registry: ToolRegistry) -> None:
    registry.register(
        "outcome.add", _outcome_add, is_write=True,
        json_schema=_OUTCOME_ADD_SCHEMA,
        **examples_for("outcome.add"),
    )
    # resolve.record is an alias for outcome.add (PRD §4.4).
    registry.register(
        "resolve.record", _outcome_add, is_write=True,
        json_schema=_OUTCOME_ADD_SCHEMA,
        **examples_for("outcome.add"),
    )
    registry.register("resolve.pending", _resolve_pending)
