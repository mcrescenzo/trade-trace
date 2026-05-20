"""Decision required-field matrix per PRD §3.1 (trade-trace-e00).

R = required, O = optional, X = forbidden.

The matrix is the single source of truth; the dispatch path checks every
field for every decision type. Adding a field for a new decision type
requires updating this map; removing a field requires a contract version
bump per the closed-enum policy in storage/policy.py.
"""

from __future__ import annotations

from typing import Any, Literal

FieldKind = Literal["R", "O", "X"]
DECISION_MATRIX: dict[str, dict[str, FieldKind]] = {
    "watch": {
        "instrument_id": "R", "thesis_id": "O", "side": "O",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "O", "review_by": "O",
    },
    "skip": {
        "instrument_id": "R", "thesis_id": "O", "side": "O",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "R", "review_by": "X",
    },
    "paper_enter": {
        "instrument_id": "R", "thesis_id": "R", "side": "R",
        "quantity": "R", "price": "R", "fees": "O", "slippage": "O",
        "reason": "O", "review_by": "X",
    },
    "paper_exit": {
        "instrument_id": "R", "thesis_id": "O", "side": "R",
        "quantity": "R", "price": "R", "fees": "O", "slippage": "O",
        "reason": "O", "review_by": "X",
    },
    "actual_enter": {
        "instrument_id": "R", "thesis_id": "R", "side": "R",
        "quantity": "R", "price": "R", "fees": "O", "slippage": "O",
        "reason": "O", "review_by": "X",
    },
    "actual_exit": {
        "instrument_id": "R", "thesis_id": "O", "side": "R",
        "quantity": "R", "price": "R", "fees": "O", "slippage": "O",
        "reason": "O", "review_by": "X",
    },
    "add": {
        "instrument_id": "R", "thesis_id": "O", "side": "R",
        "quantity": "R", "price": "R", "fees": "O", "slippage": "O",
        "reason": "O", "review_by": "X",
    },
    "reduce": {
        "instrument_id": "R", "thesis_id": "O", "side": "R",
        "quantity": "R", "price": "R", "fees": "O", "slippage": "O",
        "reason": "O", "review_by": "X",
    },
    "hold": {
        "instrument_id": "R", "thesis_id": "O", "side": "O",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "O", "review_by": "X",
    },
    "invalidate_thesis": {
        "instrument_id": "R", "thesis_id": "R", "side": "X",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "R", "review_by": "X",
    },
    "update_thesis": {
        "instrument_id": "R", "thesis_id": "R", "side": "X",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "O", "review_by": "X",
    },
    "resolved": {
        "instrument_id": "R", "thesis_id": "O", "side": "X",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "O", "review_by": "X",
    },
    "review": {
        "instrument_id": "R", "thesis_id": "O", "side": "X",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "O", "review_by": "R",
    },
}


def allowed_decision_types() -> list[str]:
    """Return the stable decision.type choices in matrix order."""

    return list(DECISION_MATRIX)


def decision_matrix_contract() -> dict[str, dict[str, list[str]]]:
    """Expose the runtime R/O/X matrix in agent-friendly terms.

    This is derived from DECISION_MATRIX so schema/help surfaces cannot drift
    from runtime validation.
    """

    return {
        decision_type: {
            "required": [field for field, kind in spec.items() if kind == "R"],
            "optional": [field for field, kind in spec.items() if kind == "O"],
            "forbidden": [field for field, kind in spec.items() if kind == "X"],
        }
        for decision_type, spec in DECISION_MATRIX.items()
    }


def _corrected_payload_hint(decision_type: str, args: dict[str, Any]) -> dict[str, Any]:
    """Return a safe, non-persisted payload shape for repairing validation.

    The hint keeps caller-supplied values for allowed fields, drops forbidden
    fields, and inserts placeholders only for required fields that are missing.
    """

    spec = DECISION_MATRIX[decision_type]
    hint: dict[str, Any] = {"type": decision_type}
    for field, kind in spec.items():
        if kind == "X":
            continue
        value = args.get(field)
        if value is not None and value != "":
            hint[field] = value
        elif kind == "R":
            hint[field] = f"<{field}>"
    if args.get("idempotency_key"):
        hint["idempotency_key"] = args["idempotency_key"]
    return hint


def _matrix_details(decision_type: str, args: dict[str, Any]) -> dict[str, Any]:
    contract = decision_matrix_contract()[decision_type]
    return {
        "decision_type": decision_type,
        "required_fields": contract["required"],
        "optional_fields": contract["optional"],
        "forbidden_fields": contract["forbidden"],
        "allowed_decision_types": allowed_decision_types(),
        "corrected_payload_hint": _corrected_payload_hint(decision_type, args),
    }


def validate_decision_fields(decision_type: str, args: dict) -> None:
    """Enforce the required-field matrix for `decision.add`. Raises
    ToolError(VALIDATION_ERROR) on the first violation with `details.field`
    set and `details.decision_type` echoed back.
    """

    from trade_trace.contracts.errors import ErrorCode
    from trade_trace.tools.errors import ToolError

    if decision_type not in DECISION_MATRIX:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"unknown decision type {decision_type!r}",
            details={
                "field": "type",
                "value": decision_type,
                "allowed_decision_types": allowed_decision_types(),
                "decision_matrix": decision_matrix_contract(),
                "recovery": "Choose one of allowed_decision_types, then include that type's required_fields and omit forbidden_fields.",
            },
        )

    spec = DECISION_MATRIX[decision_type]
    for col, kind in spec.items():
        value = args.get(col)
        if kind == "R" and (value is None or value == ""):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{col} is required for decision.type={decision_type!r}",
                details={
                    "field": col,
                    "violation": "required_missing",
                    **_matrix_details(decision_type, args),
                    "recovery": f"Add {col!r} or choose a decision type where it is optional/forbidden.",
                },
            )
        if kind == "X" and value is not None and value != "":
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{col} is forbidden for decision.type={decision_type!r}",
                details={
                    "field": col,
                    "violation": "forbidden_present",
                    "value": value,
                    **_matrix_details(decision_type, args),
                    "recovery": f"Remove {col!r} or choose a decision type where it is allowed.",
                },
            )
