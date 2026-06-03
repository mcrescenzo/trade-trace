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
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.projections import rebuild_positions
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    common_metadata,
    db_for_args,
    emit_event,
    new_id,
    normalize_timestamp,
    now_iso,
    reject_if_contains_secrets,
    require,
    store_metadata_json,
)
from trade_trace.tools.decision_matrix import (
    allowed_decision_types,
    decision_matrix_contract,
    material_non_action_taxonomy,
    validate_decision_fields,
    validate_material_non_action,
)
from trade_trace.tools.errors import ToolError
from trade_trace.tools.ledger._shared import _store_tags, examples_for


def _decision_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    # 'type' is the field name (not 'decision_type'); a bare "type is required"
    # leaves a caller guessing both the name and the valid values. List them.
    if args.get("type") is None:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "type is required; one of " + ", ".join(allowed_decision_types()),
            details={"field": "type", "allowed_decision_types": allowed_decision_types()},
        )
    decision_type = require(args, "type")
    # Ergonomics: forecast.add returns forecast_id (its thesis_id is easy to
    # miss), but paper_enter and friends require thesis_id. If the caller gave
    # forecast_id but no thesis_id, derive the thesis from the forecast so they
    # do not have to look it up separately.
    if not args.get("thesis_id") and args.get("forecast_id"):
        with db_for_args(args) as _db:
            row = _db.connection.execute(
                "SELECT thesis_id FROM forecasts WHERE id = ?",
                (args["forecast_id"],),
            ).fetchone()
        if row and row[0]:
            args["thesis_id"] = row[0]
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

    with db_for_args(args) as db:
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
    return result


# Hand-crafted JSON schema for decision.add per bead trade-trace-hsnz.
# Auto-derivation from example_minimal=actual_enter forced `quantity`/`price`
# as required, but the decision matrix marks them X (forbidden) for `watch`
# and `skip`. Required set here is the intersection across all matrix rows:
# every row has `instrument_id` R, and `type` discriminates the row, so
# `type`, `instrument_id`, and `idempotency_key` are the only schema-level
# required fields. The runtime decision matrix in `decision_matrix.py`
# enforces per-type R/X constraints uniformly and returns a typed
# VALIDATION_ERROR envelope on violation.
_DECISION_MATRIX_CONTRACT = decision_matrix_contract()

_DECISION_ADD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": allowed_decision_types(),
            "description": "Decision discriminator. See x-decision-matrix for per-type required/optional/forbidden fields.",
        },
        "instrument_id": {"type": "string"},
        "thesis_id": {"type": "string"},
        "forecast_id": {"type": "string"},
        "snapshot_id": {"type": "string"},
        "side": {"type": "string"},
        "quantity": {"type": "number"},
        "price": {"type": "number"},
        "fees": {"type": "number"},
        "slippage": {"type": "number"},
        "reason": {"type": "string"},
        "review_by": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "metadata_json": {"type": "object"},
        "agent_id": {"type": "string"},
        "model_id": {"type": "string"},
        "environment": {"type": "string"},
        "run_id": {"type": "string"},
        "strategy_id": {"type": "string"},
        "position_id": {"type": "string"},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["type", "instrument_id", "idempotency_key"],
    "description": (
        "decision.add — runtime decision matrix in decision_matrix.py "
        "enforces per-`type` required/forbidden fields and returns a "
        "VALIDATION_ERROR envelope on violation. Use x-decision-matrix "
        "for per-type required/optional/forbidden fields. For `paper_enter`, "
        "the tool appends one linked position_events.open row, refreshes "
        "positions, and returns position_id/position_event_id; actual_* and "
        "paper_exit remain journal records only for projection purposes."
    ),
    "x-decision-matrix": _DECISION_MATRIX_CONTRACT,
    "x-material-non-action-taxonomy": material_non_action_taxonomy(),
    "x-decision-examples": {
        "skip": {
            "type": "skip",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "reason": "Spread too wide for planned edge.",
            "idempotency_key": "00000000-0000-4000-8000-000000000000",
        },
        "watch": {
            "type": "watch",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "reason": "Waiting for liquidity to improve.",
            "review_by": "2026-05-22T14:30:00Z",
            "idempotency_key": "00000000-0000-4000-8000-000000000000",
        },
        "actual_enter": {
            "type": "actual_enter",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "thesis_id": "th_THESIS_ID_HERE",
            "side": "yes",
            "quantity": 100,
            "price": 0.62,
            "idempotency_key": "00000000-0000-4000-8000-000000000000",
        },
        "actual_exit": {
            "type": "actual_exit",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "side": "yes",
            "quantity": 100,
            "price": 0.78,
            "idempotency_key": "00000000-0000-4000-8000-000000000000",
        },
    },
}


def register_decision_tools(registry: ToolRegistry) -> None:
    registry.register(
        "decision.add",
        _decision_add,
        is_write=True,
        json_schema=_DECISION_ADD_SCHEMA,
        description=(
            "decision.add type choices: " + ", ".join(allowed_decision_types()) +
            ". Per-type required/optional/forbidden fields are exposed in "
            "tool.schema json_schema.x-decision-matrix."
        ),
        usage_summary="Record a trade decision against an instrument; choose type and include only fields allowed by the decision matrix.",
        examples=("tt decision add --instrument-id ins_... --type enter --side long --thesis-id th_... --idempotency-key <uuid>",),
        enum_notes={"type": "Allowed values and per-type field requirements live in json_schema.x-decision-matrix.", "side": "Use long/short only for directional decision types."},
        common_failures=("Missing a field required by the selected decision type.", "Providing a forbidden field for the selected decision type."),
        next_actions=("Inspect `tt tool schema --tool decision.add` before retrying validation failures.",),
        **examples_for("decision.add"),
    )
