"""Decision required-field matrix per PRD §3.1 (trade-trace-e00).

R = required, O = optional, X = forbidden.

The matrix is the single source of truth; the dispatch path checks every
field for every decision type. Adding a field for a new decision type
requires updating this map; removing a field requires a contract version
bump per the closed-enum policy in storage/policy.py.
"""

from __future__ import annotations

from typing import Literal

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
            details={"field": "type", "value": decision_type},
        )

    spec = DECISION_MATRIX[decision_type]
    for col, kind in spec.items():
        value = args.get(col)
        if kind == "R" and (value is None or value == ""):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{col} is required for decision.type={decision_type!r}",
                details={"field": col, "decision_type": decision_type},
            )
        if kind == "X" and value is not None and value != "":
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{col} is forbidden for decision.type={decision_type!r}",
                details={"field": col, "decision_type": decision_type, "value": value},
            )
