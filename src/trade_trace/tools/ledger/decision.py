"""`decision.add` handler.

Extracted from `tools/ledger/__init__.py` per bead trade-trace-v841.
The runtime decision matrix (`tools/decision_matrix.py`) enforces
per-`type` required/forbidden fields; this handler validates risk-unit
P1 columns, writes the `decisions` row, emits `decision.created`, and
for `paper_enter` appends the linked `position_events.open` row and
refreshes positions.
"""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.projections import rebuild_positions
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    common_metadata,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    open_db_for_args,
    reject_if_contains_secrets,
    require,
    store_metadata_json,
)
from trade_trace.tools.decision_matrix import (
    validate_decision_fields,
    validate_material_non_action,
)
from trade_trace.tools.errors import ToolError
from trade_trace.tools.ledger._shared import _store_tags


def _decision_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    decision_type = require(args, "type")
    validate_decision_fields(decision_type, args)
    validate_material_non_action(decision_type, args)
    reject_if_contains_secrets(args.get("reason"), field="reason")
    tags = _store_tags(args.get("tags"))
    seg = common_metadata(args)
    idempotency_key = args.get("idempotency_key")
    review_by = normalize_timestamp(args, "review_by")
    metadata_json = store_metadata_json(args)
    # Risk-unit P1 columns per bead trade-trace-8z2 / risk-units.md §3.2.
    # Validate in the tool layer before SQLite triggers so callers receive a
    # clean VALIDATION_ERROR envelope with field details instead of a raw
    # constraint string. Migration 004 keeps the DB invariant as defense in
    # depth for direct/imported writes.
    def _optional_float(field: str) -> float | None:
        value = args.get(field)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{field} must be numeric",
                details={"field": field, "value": value},
            ) from exc

    declared_risk_amount = _optional_float("declared_risk_amount")
    declared_risk_unit = args.get("declared_risk_unit")
    expected_edge = _optional_float("expected_edge")
    expected_edge_after_costs = _optional_float("expected_edge_after_costs")
    cost_basis_estimate = _optional_float("cost_basis_estimate")
    risk_reward_estimate = _optional_float("risk_reward_estimate")
    if declared_risk_amount is not None and declared_risk_amount < 0:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "declared_risk_amount must be >= 0 (risk-units.md §3.5)",
            details={"field": "declared_risk_amount"},
        )
    if (expected_edge is not None and expected_edge_after_costs is not None
            and expected_edge_after_costs > expected_edge + 1e-9):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "expected_edge_after_costs must be <= expected_edge + 1e-9 (risk-units.md §3.5)",
            details={"field": "expected_edge_after_costs"},
        )

    def _paper_enter_quantity_delta() -> float:
        quantity = float(require(args, "quantity"))
        side = require(args, "side")
        return -quantity if side in {"no", "short"} else quantity

    def _linked_position_ids(conn, decision_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT id, position_id FROM position_events WHERE decision_id = ? "
            "AND event_type = 'open' ORDER BY created_at ASC, id ASC LIMIT 1",
            (decision_id,),
        ).fetchone()
        if row is None:
            return {}
        return {"position_event_id": row[0], "position_id": row[1]}

    def _response(conn, decision_id: str, created_at_value: str, review_by_value: str | None) -> dict[str, Any]:
        data = {"id": decision_id, "type": decision_type,
                "instrument_id": args.get("instrument_id"),
                "snapshot_id": args.get("snapshot_id"), "tags": tags,
                "created_at": created_at_value, "review_by": review_by_value}
        if decision_type == "paper_enter":
            data.update(_linked_position_ids(conn, decision_id))
        return data

    def _payload(did: str) -> dict[str, Any]:
        return {
            "id": did,
            "instrument_id": args.get("instrument_id"),
            "thesis_id": args.get("thesis_id"),
            "forecast_id": args.get("forecast_id"),
            "snapshot_id": args.get("snapshot_id"),
            "type": decision_type,
            "side": args.get("side"),
            "quantity": args.get("quantity"),
            "price": args.get("price"),
            "fees": args.get("fees"),
            "slippage": args.get("slippage"),
            "reason": args.get("reason"),
            "playbook_version_id": args.get("playbook_version_id"),
            "review_by": review_by,
            "strategy_id": args.get("strategy_id"),
            "tags": tags,
            "declared_risk_amount": declared_risk_amount,
            "declared_risk_unit": declared_risk_unit,
            "expected_edge": expected_edge,
            "expected_edge_after_costs": expected_edge_after_costs,
            "cost_basis_estimate": cost_basis_estimate,
            "risk_reward_estimate": risk_reward_estimate,
        }

    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="decision.created",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                decision_id = replay["id"]
                emit_event(
                    uow, event_type="decision.created",
                    subject_kind="decision", subject_id=decision_id,
                    payload=_payload(decision_id),
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT created_at, review_by FROM decisions WHERE id = ?",
                    (decision_id,),
                ).fetchone()
                return _response(uow.conn, decision_id, row[0], row[1])

            decision_id = args.get("id") or new_id("dec")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO decisions(id, instrument_id, thesis_id, forecast_id, "
                "snapshot_id, type, side, quantity, price, fees, slippage, reason, "
                "playbook_version_id, review_by, strategy_id, "
                "declared_risk_amount, declared_risk_unit, expected_edge, "
                "expected_edge_after_costs, cost_basis_estimate, "
                "risk_reward_estimate, agent_id, model_id, "
                "environment, run_id, metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_id, args.get("instrument_id"), args.get("thesis_id"),
                    args.get("forecast_id"), args.get("snapshot_id"), decision_type,
                    args.get("side"), args.get("quantity"), args.get("price"),
                    args.get("fees"), args.get("slippage"), args.get("reason"),
                    args.get("playbook_version_id"), review_by, args.get("strategy_id"),
                    declared_risk_amount, declared_risk_unit, expected_edge,
                    expected_edge_after_costs, cost_basis_estimate,
                    risk_reward_estimate,
                    seg["agent_id"], seg["model_id"], seg["environment"], seg["run_id"],
                    metadata_json, created_at, ctx.actor_id,
                ),
            )
            for tag in tags:
                uow.execute(
                    "INSERT INTO decision_tags(decision_id, tag) VALUES (?, ?)",
                    (decision_id, tag),
                )
            emit_event(
                uow, event_type="decision.created",
                subject_kind="decision", subject_id=decision_id,
                payload=_payload(decision_id),
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
            if decision_type == "paper_enter":
                position_id = new_id("pos")
                position_event_id = new_id("pev")
                uow.execute(
                    "INSERT INTO position_events(id, position_id, instrument_id, decision_id, "
                    "event_type, quantity_delta, price, fees, slippage, metadata_json, "
                    "created_at, actor_id, initial_risk_amount) "
                    "VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, '{}', ?, ?, ?)",
                    (
                        position_event_id, position_id, args.get("instrument_id"), decision_id,
                        _paper_enter_quantity_delta(), args.get("price"), args.get("fees"),
                        args.get("slippage"), created_at, ctx.actor_id, declared_risk_amount,
                    ),
                )
                rebuild_positions(uow.conn)
                result = _response(uow.conn, decision_id, created_at, review_by)
            else:
                result = _response(uow.conn, decision_id, created_at, review_by)
    finally:
        db.close()
    return result
