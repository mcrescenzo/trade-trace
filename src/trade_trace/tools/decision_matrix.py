"""Decision required-field matrix per PRD §3.1 (trade-trace-e00).

R = required, O = optional, X = forbidden.

The matrix is the single source of truth; the dispatch path checks every
field for every decision type. Adding a field for a new decision type
requires updating this map; removing a field requires a contract version
bump per the closed-enum policy in storage/policy.py.

Design note (trade-trace-t9n5): `forecast_id` is `O` (optional) on the
non-trade decision types `watch`/`skip`/`hold`. A bot that records a real
forecast and then deliberately skips for insufficient edge can now carry the
forecast linkage on the decision row, documented in the x-decision-matrix
contract rather than relying on it being silently accepted. This complements
the instrument-level forecast-linkage check in reports/coach.py: coach no
longer flags a forecasted-then-skipped market as 'no linked forecast' even
when the skip row itself carries no forecast_id, because the *instrument* is
forecasted.
"""

from __future__ import annotations

from typing import Any, Literal

FieldKind = Literal["R", "O", "X"]
DECISION_MATRIX: dict[str, dict[str, FieldKind]] = {
    "watch": {
        "instrument_id": "R", "thesis_id": "O", "forecast_id": "O",
        "snapshot_id": "O", "side": "O",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "O", "review_by": "O",
    },
    "skip": {
        "instrument_id": "R", "thesis_id": "O", "forecast_id": "O",
        "snapshot_id": "O", "side": "O",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "R", "review_by": "X",
    },
    "paper_enter": {
        "instrument_id": "R", "thesis_id": "R", "snapshot_id": "O", "side": "R",
        "quantity": "R", "price": "R", "fees": "O", "slippage": "O",
        "reason": "O", "review_by": "X",
    },
    "paper_exit": {
        "instrument_id": "R", "thesis_id": "O", "snapshot_id": "O", "side": "R",
        "quantity": "R", "price": "R", "fees": "O", "slippage": "O",
        "reason": "O", "review_by": "X",
    },
    "actual_enter": {
        "instrument_id": "R", "thesis_id": "R", "snapshot_id": "O", "side": "R",
        "quantity": "R", "price": "R", "fees": "O", "slippage": "O",
        "reason": "O", "review_by": "X",
    },
    "actual_exit": {
        "instrument_id": "R", "thesis_id": "O", "snapshot_id": "O", "side": "R",
        "quantity": "R", "price": "R", "fees": "O", "slippage": "O",
        "reason": "O", "review_by": "X",
    },
    "add": {
        "instrument_id": "R", "thesis_id": "O", "snapshot_id": "O", "side": "R",
        "quantity": "R", "price": "R", "fees": "O", "slippage": "O",
        "reason": "O", "review_by": "X",
    },
    "reduce": {
        "instrument_id": "R", "thesis_id": "O", "snapshot_id": "O", "side": "R",
        "quantity": "R", "price": "R", "fees": "O", "slippage": "O",
        "reason": "O", "review_by": "X",
    },
    "hold": {
        "instrument_id": "R", "thesis_id": "O", "forecast_id": "O",
        "snapshot_id": "O", "side": "O",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "O", "review_by": "O",
    },
    "invalidate_thesis": {
        "instrument_id": "R", "thesis_id": "R", "snapshot_id": "O", "side": "X",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "R", "review_by": "X",
    },
    "update_thesis": {
        "instrument_id": "R", "thesis_id": "R", "snapshot_id": "O", "side": "X",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "O", "review_by": "X",
    },
    "resolved": {
        "instrument_id": "R", "thesis_id": "O", "snapshot_id": "O", "side": "X",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "O", "review_by": "X",
    },
    "review": {
        "instrument_id": "R", "thesis_id": "O", "snapshot_id": "O", "side": "X",
        "quantity": "X", "price": "X", "fees": "X", "slippage": "X",
        "reason": "O", "review_by": "R",
    },
}

MATERIAL_NON_ACTION_CATEGORIES: dict[str, dict[str, Any]] = {
    "watch": {"decision_types": ["watch"], "requires_review_by": False, "closure": "review or resolved decision after trigger/deadline"},
    "skip": {"decision_types": ["skip"], "requires_review_by": False, "closure": "terminal by default; review only when selected by supplied outcome/opportunity evidence"},
    "hold": {"decision_types": ["hold"], "requires_review_by": False, "closure": "later action, review, thesis update, or resolved decision"},
    "defer": {"decision_types": ["watch", "hold", "review"], "requires_review_by": True, "closure": "review_by checkpoint or explicit review/decision when blocker clears"},
    "review": {"decision_types": ["review"], "requires_review_by": True, "closure": "the recorded review decision is the checkpoint; follow with reflection if lessons emerge"},
    "thesis_update": {"decision_types": ["update_thesis"], "requires_review_by": False, "closure": "superseding thesis/review/reflection as applicable"},
    "thesis_invalidated": {"decision_types": ["invalidate_thesis"], "requires_review_by": False, "closure": "invalidated thesis plus review/reflection when outcome evidence exists"},
}

MATERIALITY_REASONS: list[str] = [
    "candidate_rejected", "liquidity", "source_stale", "insufficient_edge",
    "risk_limit", "playbook_block", "already_exposed", "forecast_ambiguous",
    "waiting_for_resolution", "thesis_changed", "thesis_invalidated",
    "review_obligation", "scanner_selected", "source_gap",
]

# Canonical `decision.add price` convention (trade-trace-ctvb).
#
# `price` is the SIDE-NATIVE price the bot actually paid for the contract
# on the chosen `side`, NOT a normalized YES-contract price. For a `no`
# prediction-market position, `price` is the NO-contract price (which is
# `1 - yes_price`); the bot records exactly what it paid. The positions
# projection is side-aware: it complements the YES-contract mark stored in
# `snapshots.price` (`1 - yes_price`) when marking `no` positions so a flat
# `no` entry reports ~0 unrealized P&L. A generic `short` side is marked
# against the same instrument price with no complement.
PRICE_CONVENTION: dict[str, Any] = {
    "field": "price",
    "semantics": "side_native",
    "summary": (
        "`price` is the side-native price you paid for the contract on the "
        "chosen `side`, not a normalized YES-contract price."
    ),
    "by_side": {
        "yes": "YES-contract price (e.g. 0.62 to buy YES at 62c).",
        "long": "Instrument price paid to open the long.",
        "no": (
            "NO-contract price you actually paid (i.e. 1 - yes_price). "
            "Record what you paid for NO; do NOT convert to the YES price."
        ),
        "short": "Instrument price at which the short was opened (no complement).",
    },
    "marking": (
        "snapshots.price stores the YES-contract price. The positions "
        "projection marks `no` positions against the complemented mark "
        "(1 - yes_price) so a flat NO entry reports ~0 unrealized P&L; "
        "`short` positions mark against the same instrument price."
    ),
    "rebuild": (
        "The positions projection is rebuildable from position_events "
        "(journal.rebuild_projections projection=positions). Existing rows "
        "written before this convention was enforced are corrected in place "
        "by re-running the rebuild — no data migration of position_events is "
        "required because the side-native entry price was already stored."
    ),
}


def allowed_decision_types() -> list[str]:
    """Return the stable decision.type choices in matrix order."""

    return list(DECISION_MATRIX)


def price_convention() -> dict[str, Any]:
    """Expose the canonical `decision.add price` side convention.

    Surfaced on `decision.add`'s JSON schema as `x-price-convention` so
    callers learn that `price` is the side-native contract price and that
    the positions projection complements the YES mark for `no` sides
    (trade-trace-ctvb)."""

    return dict(PRICE_CONVENTION)


def material_non_action_taxonomy() -> dict[str, Any]:
    """Expose optional metadata-based material non-action taxonomy."""

    return {
        "metadata_key": "metadata_json.material_non_action",
        "categories": MATERIAL_NON_ACTION_CATEGORIES,
        "materiality_reasons": MATERIALITY_REASONS,
        "required_when_present": ["category", "materiality_reason"],
        "reason_field_required_when_present": True,
        "ordinary_absence_of_action": "No decision row and no material_non_action metadata; reports must not infer a learning case from silence.",
        "defer_encoding": "Use category=defer on decision.type watch, hold, or review; do not add a defer decision enum without migration/product approval.",
    }


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


def validate_material_non_action(decision_type: str, args: dict[str, Any]) -> None:
    """Validate optional material non-action metadata for `decision.add`."""

    from trade_trace.contracts.errors import ErrorCode
    from trade_trace.tools.errors import ToolError

    metadata = args.get("metadata_json")
    if not isinstance(metadata, dict):
        return
    marker = metadata.get("material_non_action")
    if marker is None:
        return
    if not isinstance(marker, dict):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "metadata_json.material_non_action must be an object", details={"field": "metadata_json.material_non_action", "taxonomy": material_non_action_taxonomy()})
    category = marker.get("category")
    materiality_reason = marker.get("materiality_reason")
    if category not in MATERIAL_NON_ACTION_CATEGORIES:
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"unknown material non-action category {category!r}", details={"field": "metadata_json.material_non_action.category", "value": category, "allowed_categories": list(MATERIAL_NON_ACTION_CATEGORIES), "taxonomy": material_non_action_taxonomy()})
    if materiality_reason not in MATERIALITY_REASONS:
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"unknown materiality_reason {materiality_reason!r}", details={"field": "metadata_json.material_non_action.materiality_reason", "value": materiality_reason, "allowed_materiality_reasons": MATERIALITY_REASONS, "taxonomy": material_non_action_taxonomy()})
    allowed_types = MATERIAL_NON_ACTION_CATEGORIES[category]["decision_types"]
    if decision_type not in allowed_types:
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"material non-action category {category!r} is not valid for decision.type={decision_type!r}", details={"field": "metadata_json.material_non_action.category", "category": category, "decision_type": decision_type, "allowed_decision_types_for_category": allowed_types, "taxonomy": material_non_action_taxonomy()})
    if not args.get("reason"):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "reason is required when metadata_json.material_non_action is supplied", details={"field": "reason", "violation": "required_for_material_non_action", "taxonomy": material_non_action_taxonomy()})
    if MATERIAL_NON_ACTION_CATEGORIES[category]["requires_review_by"] and not args.get("review_by"):
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"review_by is required for material non-action category {category!r}", details={"field": "review_by", "violation": "required_for_material_non_action", "category": category, "taxonomy": material_non_action_taxonomy()})


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
