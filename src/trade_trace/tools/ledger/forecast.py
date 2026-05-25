"""`forecast.add` + `forecast.supersede` handlers.

Extracted from `tools/ledger/__init__.py` per bead trade-trace-9ueu.
Owns the forecast write surface — validators for binary/categorical/scalar
shapes, the shared in-transaction insert helper, the create flow with its
late-auto-score trigger, and the supersede flow which appends the lineage
edge in the same UnitOfWork. Scoring helpers live in `_scoring.py`; this
module imports them.
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
    reject_if_contains_secrets,
    require,
)
from trade_trace.tools.errors import ToolError
from trade_trace.tools.ledger._scoring import (
    _current_resolved_final_outcome,
    _emit_forecast_scored,
    _late_recorded_calc,
    _maybe_inject_late_flag,
    _score_one_forecast,
)
from trade_trace.tools.ledger._shared import examples_for

_BINARY_TOLERANCE = 1e-6


def _canonical_binary_probability(
    *, kind: str, outcomes: list[dict[str, Any]], yes_label: str | None,
) -> float | None:
    """Return the canonical PM binary YES probability for the forecast row.

    Legacy `forecast_outcomes` rows are still written during the transition,
    but m014 introduced `forecasts.probability` as the PM-native read path.
    """

    if kind != "binary":
        return None
    labels = {
        str(o.get("outcome_label") or o.get("label")).strip().lower(): float(o["probability"])
        for o in outcomes
    }
    yes_norm = yes_label.strip().lower() if yes_label else None
    if yes_norm is None:
        if "yes" in labels:
            yes_norm = "yes"
        elif "true" in labels:
            yes_norm = "true"
    return labels.get(yes_norm) if yes_norm else None


def _validate_binary_forecast(outcomes: list[dict[str, Any]]) -> None:
    if len(outcomes) != 2:
        raise ToolError(
            ErrorCode.INVARIANT_VIOLATION,
            f"binary forecast must have exactly 2 outcomes; got {len(outcomes)}",
            details={"found_count": len(outcomes)},
        )
    labels = []
    total = 0.0
    for o in outcomes:
        label = o.get("outcome_label") or o.get("label")
        prob = o.get("probability")
        if prob is None:
            raise ToolError(
                ErrorCode.INVARIANT_VIOLATION,
                "every forecast outcome requires probability",
                details={"field": "probability"},
            )
        if not (0.0 <= prob <= 1.0):
            raise ToolError(
                ErrorCode.INVARIANT_VIOLATION,
                f"probability {prob} out of [0,1]",
                details={"field": "probability", "value": prob},
            )
        labels.append(str(label).strip().lower() if label is not None else None)
        total += prob
    if labels[0] is None or labels[1] is None:
        raise ToolError(
            ErrorCode.INVARIANT_VIOLATION,
            "every forecast outcome requires outcome_label",
            details={"field": "outcome_label"},
        )
    if labels[0] == labels[1]:
        raise ToolError(
            ErrorCode.INVARIANT_VIOLATION,
            "binary forecast outcomes must have distinct labels",
            details={"found_labels": labels},
        )
    if abs(total - 1.0) > _BINARY_TOLERANCE:
        raise ToolError(
            ErrorCode.INVARIANT_VIOLATION,
            f"forecast_outcomes probabilities must sum to 1.0 within {_BINARY_TOLERANCE}",
            details={"found_sum": total},
        )


def _validate_categorical_forecast(outcomes: list[dict[str, Any]]) -> None:
    if len(outcomes) < 2:
        raise ToolError(ErrorCode.INVARIANT_VIOLATION, "categorical forecasts require at least two outcomes", details={"field": "outcomes", "found_count": len(outcomes)})
    labels: list[str] = []
    total = 0.0
    for o in outcomes:
        label = o.get("outcome_label") or o.get("label")
        if label is None or str(label).strip() == "":
            raise ToolError(ErrorCode.INVARIANT_VIOLATION, "every categorical outcome requires outcome_label", details={"field": "outcome_label"})
        try:
            prob = float(o["probability"])
        except Exception as exc:
            raise ToolError(ErrorCode.INVARIANT_VIOLATION, "every categorical outcome requires numeric probability", details={"field": "probability"}) from exc
        if not (0.0 <= prob <= 1.0):
            raise ToolError(ErrorCode.INVARIANT_VIOLATION, f"probability {prob} out of [0,1]", details={"field": "probability", "value": prob})
        labels.append(str(label).strip().lower())
        total += prob
    if len(set(labels)) != len(labels):
        raise ToolError(ErrorCode.INVARIANT_VIOLATION, "categorical forecast outcomes must have distinct labels", details={"found_labels": labels})
    if abs(total - 1.0) > _BINARY_TOLERANCE:
        raise ToolError(ErrorCode.INVARIANT_VIOLATION, f"categorical probabilities must sum to 1.0 within {_BINARY_TOLERANCE}", details={"found_sum": total})


def _validate_scalar_forecast(outcomes: list[dict[str, Any]]) -> None:
    # Backcompat schema choice: normalized scalar point forecast is stored in
    # the single forecast_outcomes.probability column (there is no wider REAL
    # prediction column yet), so supported scalar scores are on [0,1].
    if len(outcomes) != 1:
        raise ToolError(ErrorCode.INVARIANT_VIOLATION, "scalar forecasts require exactly one point-estimate outcome", details={"field": "outcomes", "found_count": len(outcomes)})
    o = outcomes[0]
    try:
        point = float(o["probability"])
    except Exception as exc:
        raise ToolError(ErrorCode.INVARIANT_VIOLATION, "scalar forecast requires numeric probability as normalized point estimate", details={"field": "probability"}) from exc
    if not (0.0 <= point <= 1.0):
        raise ToolError(ErrorCode.INVARIANT_VIOLATION, f"scalar point estimate {point} out of [0,1]", details={"field": "probability", "value": point})


def _insert_forecast_in_transaction(
    uow: UnitOfWork,
    *,
    args: dict[str, Any],
    ctx: ToolContext,
    thesis_id: str,
    forecast_id: str,
    kind: str,
    outcomes: list[dict[str, Any]],
    yes_label: str | None,
    resolution_at: str | None,
    scoring_support: str,
    seg: dict[str, Any],
    metadata_json: str,
    created_at: str,
) -> dict[str, Any]:
    """Insert a forecast row and its outcome rows using an active UoW.

    This helper intentionally does not open a database connection, start a
    transaction, commit, emit events, or perform idempotency replay checks.
    Callers own event ordering and any surrounding lineage/scoring writes.
    """

    canonical_probability = _canonical_binary_probability(
        kind=kind, outcomes=outcomes, yes_label=yes_label,
    )
    market_row = uow.conn.execute(
        """
        SELECT m.id
        FROM theses t
        JOIN markets m ON m.id = t.instrument_id
        WHERE t.id = ?
        """,
        (thesis_id,),
    ).fetchone()
    market_id = market_row[0] if market_row else args.get("market_id")
    uow.execute(
        "INSERT INTO forecasts(id, thesis_id, kind, resolution_at, yes_label, "
        "resolution_rule_text, scoring_support, scoring_state, valid_from, valid_to, "
        "agent_id, model_id, environment, run_id, metadata_json, market_id, "
        "rationale_body, falsification_criteria, probability, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            forecast_id, thesis_id, kind, resolution_at, yes_label,
            args.get("resolution_rule_text"), scoring_support,
            normalize_timestamp(args, "valid_from") or created_at,
            normalize_timestamp(args, "valid_to"),
            seg["agent_id"], seg["model_id"], seg["environment"], seg["run_id"],
            metadata_json, market_id, args.get("rationale_body"),
            args.get("falsification_criteria"), canonical_probability,
            created_at, ctx.actor_id,
        ),
    )
    for o in outcomes:
        label = o.get("outcome_label") or o.get("label")
        uow.execute(
            "INSERT INTO forecast_outcomes(id, forecast_id, outcome_label, "
            "probability, lower_bound, upper_bound) VALUES (?, ?, ?, ?, ?, ?)",
            (
                new_id("fo"), forecast_id, str(label),
                float(o["probability"]),
                o.get("lower_bound"), o.get("upper_bound"),
            ),
        )
    return {
        "id": forecast_id,
        "thesis_id": thesis_id,
        "kind": kind,
        "resolution_at": resolution_at,
        "yes_label": yes_label,
        "resolution_rule_text": args.get("resolution_rule_text"),
        "market_id": market_id,
        "probability": canonical_probability,
        "rationale_body": args.get("rationale_body"),
        "falsification_criteria": args.get("falsification_criteria"),
        "outcomes": [
            {
                "outcome_label": str(o.get("outcome_label") or o.get("label")),
                "probability": float(o["probability"]),
                "lower_bound": o.get("lower_bound"),
                "upper_bound": o.get("upper_bound"),
            }
            for o in outcomes
        ],
    }


def _forecast_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    thesis_id = require(args, "thesis_id")
    kind = args.get("kind", "binary")
    outcomes = require(args, "outcomes")
    if not isinstance(outcomes, list):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "forecast.outcomes must be a list",
            details={"field": "outcomes"},
        )
    if kind == "binary":
        _validate_binary_forecast(outcomes)
    elif kind == "categorical":
        _validate_categorical_forecast(outcomes)
    elif kind == "scalar":
        _validate_scalar_forecast(outcomes)
    else:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"unknown forecast kind {kind!r}",
            details={"field": "kind", "value": kind},
        )
    idempotency_key = args.get("idempotency_key")
    yes_label = args.get("yes_label")
    resolution_at = normalize_timestamp(args, "resolution_at")
    scoring_support = "supported"
    # Scan the one long-form forecast free-text field per bead
    # trade-trace-7j1l; yes_label is short and enum-shaped (typically
    # "yes"/"true") so it's exempt by design.
    reject_if_contains_secrets(
        args.get("resolution_rule_text"), field="resolution_rule_text",
    )
    seg = common_metadata(args)

    def _forecast_payload(fid: str) -> dict[str, Any]:
        return {
            "id": fid,
            "thesis_id": thesis_id,
            "kind": kind,
            "resolution_at": resolution_at,
            "yes_label": yes_label,
            "resolution_rule_text": args.get("resolution_rule_text"),
            "outcomes": [
                {
                    "outcome_label": str(o.get("outcome_label") or o.get("label")),
                    "probability": float(o["probability"]),
                    "lower_bound": o.get("lower_bound"),
                    "upper_bound": o.get("upper_bound"),
                }
                for o in outcomes
            ],
        }

    db = open_db_for_args(args)
    auto_scored: dict[str, Any] | None = None
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="forecast.created",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                forecast_id = replay["id"]
                emit_event(
                    uow, event_type="forecast.created",
                    subject_kind="forecast", subject_id=forecast_id,
                    payload=_forecast_payload(forecast_id),
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT created_at FROM forecasts WHERE id = ?", (forecast_id,)
                ).fetchone()
                return {"id": forecast_id, "thesis_id": thesis_id, "kind": kind,
                        "scoring_state": "pending", "created_at": row[0]}

            forecast_id = args.get("id") or new_id("fc")
            created_at = now_iso()
            # Find the head resolved_final outcome up-front; the forecast row
            # itself needs `metadata_json.late_recorded` set inline (scoring.md
            # §6 trigger #2 + dogfood-protocol §2.3 require the flag on the
            # forecast row, not just on the score row).
            instrument_id_row = uow.execute(
                "SELECT instrument_id FROM theses WHERE id = ?", (thesis_id,)
            ).fetchone()
            instrument_id = instrument_id_row[0] if instrument_id_row else None
            head_outcome = None
            if instrument_id is not None and scoring_support == "supported":
                head_outcome = _current_resolved_final_outcome(
                    uow.conn, instrument_id=instrument_id
                )
            late_recorded = False
            if head_outcome is not None:
                head_out_created = head_outcome[2]
                late_recorded, _ = _late_recorded_calc(
                    forecast_created_at=created_at,
                    outcome_created_at=head_out_created,
                    resolution_at=resolution_at,
                )

            forecast_metadata = _maybe_inject_late_flag(
                args, late_recorded=late_recorded
            )
            forecast_payload = _insert_forecast_in_transaction(
                uow,
                args=args,
                ctx=ctx,
                thesis_id=thesis_id,
                forecast_id=forecast_id,
                kind=kind,
                outcomes=outcomes,
                yes_label=yes_label,
                resolution_at=resolution_at,
                scoring_support=scoring_support,
                seg=seg,
                metadata_json=forecast_metadata,
                created_at=created_at,
            )
            emit_event(
                uow, event_type="forecast.created",
                subject_kind="forecast", subject_id=forecast_id,
                payload=forecast_payload,
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
            # Late-forecast trigger #2 per scoring.md §6.
            if head_outcome is not None:
                head_id, head_label, _head_created = head_outcome
                forecast_row = (
                    forecast_id, kind, scoring_support, yes_label, resolution_at,
                    created_at,
                )
                auto_scored = _score_one_forecast(
                    uow.conn,
                    forecast_row=forecast_row,
                    outcome_id=head_id,
                    outcome_label=head_label,
                    actor_id=ctx.actor_id,
                    scored_at=created_at,
                )
                _emit_forecast_scored(uow, auto_scored, actor_id=ctx.actor_id, ctx=ctx,
                                      scored_at=created_at)
    finally:
        db.close()
    result: dict[str, Any] = {
        "id": forecast_id, "thesis_id": thesis_id, "kind": kind,
        "scoring_state": "pending", "created_at": created_at,
    }
    if auto_scored is not None:
        result["auto_scored"] = auto_scored
    return result


def _forecast_supersede(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Append a new forecast row and emit a supersedes edge new → prior,
    all in one UnitOfWork (bead trade-trace-re4 / data-integrity fix).

    Previously the handler called `_forecast_add` in one transaction and
    then opened a second UnitOfWork for the supersedes edge + events. A
    failure between the two transactions left an orphan replacement
    forecast without the lineage edge, corrupting the forecast chain.

    The supersede path now inserts the replacement forecast row,
    forecast_outcomes, `forecast.created`, the supersedes edge, and the
    `edge.created` + `forecast.superseded` events in one transaction. A
    failure at any point rolls every row back together.

    Late auto-scoring is also performed in this same UnitOfWork when a
    `resolved_final` head outcome already exists for the thesis instrument;
    the `forecast.scored` event is emitted after the supersede events. The
    replacement forecast-row metadata keeps the historical supersede behavior
    of not pre-injecting `late_recorded` even when the score row records it.
    """

    prior_id = require(args, "prior_forecast_id")
    kind = args.get("kind", "binary")
    outcomes = require(args, "outcomes")
    if not isinstance(outcomes, list):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "forecast.outcomes must be a list",
            details={"field": "outcomes"},
        )
    if kind == "binary":
        _validate_binary_forecast(outcomes)
    elif kind == "categorical":
        _validate_categorical_forecast(outcomes)
    elif kind == "scalar":
        _validate_scalar_forecast(outcomes)
    else:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"unknown forecast kind {kind!r}",
            details={"field": "kind", "value": kind},
        )
    reject_if_contains_secrets(
        args.get("resolution_rule_text"), field="resolution_rule_text",
    )

    yes_label = args.get("yes_label")
    resolution_at = normalize_timestamp(args, "resolution_at")
    scoring_support = "supported"
    idempotency_key = args.get("idempotency_key")
    seg = common_metadata(args)

    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            prior_row = uow.execute(
                "SELECT thesis_id FROM forecasts WHERE id = ?", (prior_id,),
            ).fetchone()
            if prior_row is None:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"forecast {prior_id!r} not found",
                    details={
                        "entity_kind": "forecast",
                        "prior_forecast_id": prior_id,
                    },
                )
            thesis_id = prior_row[0]

            # Replay short-circuit per trade-trace-ug7p / data-integrity.
            # Without this, retries with the same idempotency_key would
            # insert a fresh forecast row and supersedes edge before the
            # EventWriter's replay detection in emit_event ran, corrupting
            # forecast lineage and event/relational consistency.
            replay = check_idempotency_replay(
                uow, event_type="forecast.created",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                replayed_id = replay["id"]
                emit_event(
                    uow, event_type="forecast.created",
                    subject_kind="forecast", subject_id=replayed_id,
                    payload=replay,
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key,
                    ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT created_at FROM forecasts WHERE id = ?",
                    (replayed_id,),
                ).fetchone()
                return {
                    "id": replayed_id,
                    "thesis_id": thesis_id,
                    "kind": kind,
                    "scoring_state": "pending",
                    "created_at": row[0] if row else None,
                    "supersedes_prior_forecast_id": prior_id,
                }

            new_forecast_id = args.get("id") or new_id("fc")
            created_at = now_iso()

            metadata_json = _maybe_inject_late_flag(args, late_recorded=False)

            forecast_payload = _insert_forecast_in_transaction(
                uow,
                args=args,
                ctx=ctx,
                thesis_id=thesis_id,
                forecast_id=new_forecast_id,
                kind=kind,
                outcomes=outcomes,
                yes_label=yes_label,
                resolution_at=resolution_at,
                scoring_support=scoring_support,
                seg=seg,
                metadata_json=metadata_json,
                created_at=created_at,
            )
            emit_event(
                uow, event_type="forecast.created",
                subject_kind="forecast", subject_id=new_forecast_id,
                payload=forecast_payload,
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
                ctx=ctx,
            )

            edge_id = new_id("edg")
            uow.execute(
                "INSERT INTO edges(id, source_kind, source_id, target_kind, "
                "target_id, edge_type, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    edge_id, "forecast", new_forecast_id, "forecast",
                    prior_id, "supersedes", created_at, ctx.actor_id,
                ),
            )
            emit_event(
                uow, event_type="edge.created",
                subject_kind="edge", subject_id=edge_id,
                payload={
                    "id": edge_id, "source_kind": "forecast",
                    "source_id": new_forecast_id,
                    "target_kind": "forecast", "target_id": prior_id,
                    "edge_type": "supersedes",
                },
                actor_id=ctx.actor_id, idempotency_key=None, ctx=ctx,
            )
            emit_event(
                uow, event_type="forecast.superseded",
                subject_kind="forecast", subject_id=new_forecast_id,
                payload={"prior_forecast_id": prior_id,
                         "new_forecast_id": new_forecast_id},
                actor_id=ctx.actor_id, idempotency_key=None, ctx=ctx,
            )

            # Late auto-score per trade-trace-ld6l: if a `resolved_final`
            # outcome already exists for this instrument, score the
            # replacement forecast against it inline. This matches the
            # `forecast.add` late-trigger path (scoring.md §6 trigger
            # #2); without it, the replacement forecast stayed
            # permanently `scoring_state="pending"` and reports omitted
            # it from calibration. The auto-score row carries
            # `late_recorded=true` because the outcome predates the
            # supersede.
            auto_scored: dict[str, Any] | None = None
            instrument_id_row = uow.execute(
                "SELECT instrument_id FROM theses WHERE id = ?",
                (thesis_id,),
            ).fetchone()
            instrument_id = instrument_id_row[0] if instrument_id_row else None
            if instrument_id is not None and scoring_support == "supported":
                head_outcome = _current_resolved_final_outcome(
                    uow.conn, instrument_id=instrument_id,
                )
                if head_outcome is not None:
                    head_id, head_label, _head_created = head_outcome
                    forecast_row = (
                        new_forecast_id, kind, scoring_support, yes_label,
                        resolution_at, created_at,
                    )
                    auto_scored = _score_one_forecast(
                        uow.conn,
                        forecast_row=forecast_row,
                        outcome_id=head_id,
                        outcome_label=head_label,
                        actor_id=ctx.actor_id,
                        scored_at=created_at,
                    )
                    _emit_forecast_scored(
                        uow, auto_scored, actor_id=ctx.actor_id, ctx=ctx,
                        scored_at=created_at,
                    )
    finally:
        db.close()

    result: dict[str, Any] = {
        "id": new_forecast_id,
        "thesis_id": thesis_id,
        "kind": kind,
        "scoring_state": "pending",
        "created_at": created_at,
        "supersedes_prior_forecast_id": prior_id,
    }
    if auto_scored is not None:
        result["auto_scored"] = auto_scored
    return result


def register_forecast_tools(registry: ToolRegistry) -> None:
    registry.register(
        "forecast.add", _forecast_add, is_write=True,
        **examples_for("forecast.add"),
    )
    registry.register(
        "forecast.supersede", _forecast_supersede, is_write=True,
        **examples_for("forecast.supersede"),
    )
