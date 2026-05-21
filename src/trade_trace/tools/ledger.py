"""M1 manual ledger / source / resolution write tools per PRD §4.0–§4.5.

Each tool below is a pure dispatch handler: validates args, opens the DB,
writes a primary row inside a UnitOfWork, writes the matching event via
the EventWriter, and returns the new row's id (and key fields) in the
success envelope's `data` payload.

The implementation is intentionally compact — heavy validation lives in
shared helpers (`_helpers.py`, `decision_matrix.py`, the storage CHECK
constraints, the EventWriter, the timestamp normalizer, and the actor_id
grammar in contracts/grammar.py).
"""

from __future__ import annotations

import json
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
from trade_trace.tools.decision_matrix import (
    allowed_decision_types,
    decision_matrix_contract,
    validate_decision_fields,
)
from trade_trace.tools.errors import ToolError


def _idempotency_key(args: dict[str, Any]) -> str | None:
    """Extract the caller-supplied idempotency_key. Returns None for the
    `_allow_no_idempotency: true` opt-in path; EventWriter then enforces the
    at-least-once semantics."""

    return args.get("idempotency_key")


def _allow_no_idempotency(args: dict[str, Any]) -> bool:
    return bool(args.get("_allow_no_idempotency"))


_CREDENTIAL_METADATA_KEY_PARTS = (
    "api_key",
    "access_token",
    "refresh_token",
    "auth_token",
    "bearer_token",
    "secret_key",
    "client_secret",
    "password",
    "passphrase",
    "wallet_seed",
    "wallet_seed_phrase",
    "seed_phrase",
    "mnemonic",
    "private_key",
    "signing" + "_key",
    "signing_secret",
    "broker_token",
    "trading_password",
    "session_token",
    "oauth_token",
)


def _reject_credential_metadata(value: Any, *, field: str) -> None:
    """Reject explicit metadata JSON that tries to carry credentials.

    Unknown top-level credential-shaped args are ignored by schemas, but
    caller-provided metadata_json is intentionally persisted. Guard it
    recursively so explicit JSON objects or raw JSON strings cannot bypass
    the no-credentials policy.
    """

    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            for forbidden in _CREDENTIAL_METADATA_KEY_PARTS:
                if forbidden in key_text:
                    raise ToolError(
                        ErrorCode.VALIDATION_ERROR,
                        f"{field} contains credential-shaped key {key!r}; strip credentials before submitting",
                        details={"field": field, "credential_key": str(key)},
                    )
            _reject_credential_metadata(child, field=field)
        return
    if isinstance(value, list):
        for child in value:
            _reject_credential_metadata(child, field=field)
        return
    if isinstance(value, str):
        reject_if_contains_secrets(value, field=field)


def _store_metadata_json(args: dict[str, Any], key: str = "metadata_json") -> str:
    value = args.get(key)
    if value is None:
        return "{}"
    if isinstance(value, str):
        # Caller may pass a JSON string directly. If parseable, inspect the
        # decoded object too so nested credential keys cannot hide in raw JSON.
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as err:
            reject_if_contains_secrets(value, field=key)
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{key} must be valid JSON when supplied as a string",
                details={"field": key, "reason": "invalid_json"},
            ) from err
        else:
            _reject_credential_metadata(decoded, field=key)
        return value
    _reject_credential_metadata(value, field=key)
    return json.dumps(value, sort_keys=True, default=str)


def _store_tags(tags: Any) -> list[str]:
    """Normalize a tags argument into a sorted list of lowercased, trimmed,
    deduplicated strings per PRD §3.1 decision_tags."""

    if tags is None:
        return []
    if isinstance(tags, str):
        # Allow comma-separated CLI input.
        tags = [t.strip() for t in tags.split(",")]
    out = set()
    for t in tags:
        normalized = str(t).strip().lower()
        if not normalized:
            continue
        if len(normalized) > 64:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "decision tag exceeds 64-char cap",
                details={"field": "tags", "value": normalized},
            )
        out.add(normalized)
    return sorted(out)


# -- venue.add ---------------------------------------------------------------

def _venue_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    name = require(args, "name")
    kind = require(args, "kind")
    metadata_json = _store_metadata_json(args)
    idempotency_key = args.get("idempotency_key")
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="venue.created",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                venue_id = replay["id"]
                payload = {"id": venue_id, "name": name, "kind": kind,
                           "metadata_json": metadata_json}
                emit_event(
                    uow, event_type="venue.created",
                    subject_kind="venue", subject_id=venue_id,
                    payload=payload, actor_id=ctx.actor_id,
                    idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT name, kind, created_at FROM venues WHERE id = ?",
                    (venue_id,),
                ).fetchone()
                return {"id": venue_id, "name": row[0], "kind": row[1],
                        "created_at": row[2]}

            venue_id = args.get("id") or new_id("ven")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (venue_id, name, kind, metadata_json, created_at, ctx.actor_id),
            )
            payload = {"id": venue_id, "name": name, "kind": kind,
                       "metadata_json": metadata_json}
            emit_event(
                uow, event_type="venue.created",
                subject_kind="venue", subject_id=venue_id,
                payload=payload, actor_id=ctx.actor_id,
                idempotency_key=idempotency_key, ctx=ctx,
            )
    finally:
        db.close()
    return {"id": venue_id, "name": name, "kind": kind, "created_at": created_at}


# -- instrument.add ----------------------------------------------------------

def _instrument_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    venue_id = require(args, "venue_id")
    asset_class = require(args, "asset_class")
    title = require(args, "title")
    # Scan long-form instrument free-text per bead trade-trace-7j1l.
    # Narrow enum / id fields (asset_class, currency_or_collateral,
    # external_id, symbol) are exempt: they pass through to controlled
    # vocabularies and rejecting common identifiers would break ledger
    # flow. resolution_criteria_text is the one true free-text field.
    reject_if_contains_secrets(title, field="title")
    reject_if_contains_secrets(
        args.get("resolution_criteria_text"), field="resolution_criteria_text",
    )
    idempotency_key = args.get("idempotency_key")
    expiration = normalize_timestamp(args, "expiration_or_resolution_at")
    metadata_json = _store_metadata_json(args)
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            payload_common = {
                "venue_id": venue_id,
                "external_id": args.get("external_id"),
                "symbol": args.get("symbol"),
                "title": title,
                "asset_class": asset_class,
                "currency_or_collateral": args.get("currency_or_collateral"),
                "expiration_or_resolution_at": expiration,
                "resolution_criteria_text": args.get("resolution_criteria_text"),
                "contract_multiplier": args.get("contract_multiplier"),
                "metadata_json": metadata_json,
            }
            replay = check_idempotency_replay(
                uow, event_type="instrument.created",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                inst_id = replay["id"]
                payload = {"id": inst_id, **payload_common}
                emit_event(
                    uow, event_type="instrument.created",
                    subject_kind="instrument", subject_id=inst_id,
                    payload=payload, actor_id=ctx.actor_id,
                    idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT created_at FROM instruments WHERE id = ?", (inst_id,)
                ).fetchone()
                return {
                    "id": inst_id, "venue_id": venue_id,
                    "asset_class": asset_class, "title": title,
                    "created_at": row[0],
                }

            inst_id = args.get("id") or new_id("ins")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO instruments(id, venue_id, external_id, symbol, title, "
                "asset_class, currency_or_collateral, expiration_or_resolution_at, "
                "resolution_criteria_text, contract_multiplier, metadata_json, "
                "created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    inst_id,
                    venue_id,
                    args.get("external_id"),
                    args.get("symbol"),
                    title,
                    asset_class,
                    args.get("currency_or_collateral"),
                    expiration,
                    args.get("resolution_criteria_text"),
                    args.get("contract_multiplier"),
                    metadata_json,
                    created_at,
                    ctx.actor_id,
                ),
            )
            payload = {"id": inst_id, **payload_common}
            emit_event(
                uow, event_type="instrument.created",
                subject_kind="instrument", subject_id=inst_id,
                payload=payload, actor_id=ctx.actor_id,
                idempotency_key=idempotency_key, ctx=ctx,
            )
    finally:
        db.close()
    return {
        "id": inst_id,
        "venue_id": venue_id,
        "asset_class": asset_class,
        "title": title,
        "created_at": created_at,
    }


# -- snapshot.add ------------------------------------------------------------

def _snapshot_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    instrument_id = require(args, "instrument_id")
    captured_at = normalize_timestamp(args, "captured_at", required=True)
    idempotency_key = args.get("idempotency_key")
    source = args.get("source", "manual")
    liquidity_depth_json = _store_metadata_json(args, "liquidity_depth_json")
    metadata_json = _store_metadata_json(args)
    payload_common = {
        "instrument_id": instrument_id,
        "captured_at": captured_at,
        "source": source,
        "source_url": args.get("source_url"),
        "price": args.get("price"),
        "bid": args.get("bid"),
        "ask": args.get("ask"),
        "mid": args.get("mid"),
        "spread": args.get("spread"),
        "volume": args.get("volume"),
        "open_interest": args.get("open_interest"),
        "implied_probability": args.get("implied_probability"),
        "liquidity_depth_json": liquidity_depth_json,
        "metadata_json": metadata_json,
    }
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="snapshot.added",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                snap_id = replay["id"]
                emit_event(
                    uow, event_type="snapshot.added",
                    subject_kind="snapshot", subject_id=snap_id,
                    payload={"id": snap_id, **payload_common},
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                )
                return {"id": snap_id, "instrument_id": instrument_id,
                        "captured_at": captured_at}

            snap_id = args.get("id") or new_id("snp")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO snapshots(id, instrument_id, captured_at, source, source_url, "
                "price, bid, ask, mid, spread, volume, open_interest, implied_probability, "
                "liquidity_depth_json, metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snap_id, instrument_id, captured_at, source,
                    args.get("source_url"), args.get("price"), args.get("bid"),
                    args.get("ask"), args.get("mid"), args.get("spread"),
                    args.get("volume"), args.get("open_interest"),
                    args.get("implied_probability"),
                    liquidity_depth_json, metadata_json, created_at, ctx.actor_id,
                ),
            )
            emit_event(
                uow, event_type="snapshot.added",
                subject_kind="snapshot", subject_id=snap_id,
                payload={"id": snap_id, **payload_common},
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
    finally:
        db.close()
    return {"id": snap_id, "instrument_id": instrument_id, "captured_at": captured_at}


# -- thesis.add --------------------------------------------------------------

def _thesis_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    instrument_id = require(args, "instrument_id")
    side = require(args, "side")
    body = require(args, "body")
    reject_if_contains_secrets(body, field="body")
    # Long-form thesis free-text fields per bead trade-trace-7j1l;
    # narrow enum-shaped columns (side, confidence_label, …) are
    # exempt by design (see docs/architecture/security.md §6.5).
    for field in ("falsification_criteria", "exit_triggers", "risk_notes",
                  "invalidation_condition", "risk_unit_label"):
        reject_if_contains_secrets(args.get(field), field=field)
    parent = args.get("parent_thesis_id")
    version = args.get("version", 1)
    idempotency_key = args.get("idempotency_key")
    time_horizon_at = normalize_timestamp(args, "time_horizon_at")
    valid_to = normalize_timestamp(args, "valid_to")
    seg = common_metadata(args)
    metadata_json = _store_metadata_json(args)

    def _payload(tid: str, valid_from: str) -> dict[str, Any]:
        return {
            "id": tid,
            "instrument_id": instrument_id,
            "version": version,
            "parent_thesis_id": parent,
            "side": side,
            "time_horizon_at": time_horizon_at,
            "confidence_label": args.get("confidence_label"),
            "body": body,
            "falsification_criteria": args.get("falsification_criteria"),
            "exit_triggers": args.get("exit_triggers"),
            "risk_notes": args.get("risk_notes"),
            "strategy_id": args.get("strategy_id"),
            "valid_from": valid_from,
            "valid_to": valid_to,
            "metadata_json": metadata_json,
        }

    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="thesis.created",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                thesis_id = replay["id"]
                row = uow.conn.execute(
                    "SELECT valid_from, created_at FROM theses WHERE id = ?",
                    (thesis_id,),
                ).fetchone()
                emit_event(
                    uow, event_type="thesis.created",
                    subject_kind="thesis", subject_id=thesis_id,
                    payload=_payload(thesis_id, row[0]),
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                )
                return {"id": thesis_id, "instrument_id": instrument_id,
                        "version": version, "side": side, "created_at": row[1]}

            thesis_id = args.get("id") or new_id("th")
            created_at = now_iso()
            valid_from = normalize_timestamp(args, "valid_from") or created_at
            uow.execute(
                "INSERT INTO theses(id, instrument_id, version, parent_thesis_id, side, "
                "time_horizon_at, confidence_label, body, falsification_criteria, "
                "exit_triggers, risk_notes, strategy_id, valid_from, valid_to, "
                "agent_id, model_id, environment, run_id, metadata_json, "
                "created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    thesis_id, instrument_id, version, parent, side,
                    time_horizon_at, args.get("confidence_label"), body,
                    args.get("falsification_criteria"), args.get("exit_triggers"),
                    args.get("risk_notes"), args.get("strategy_id"),
                    valid_from, valid_to,
                    seg["agent_id"], seg["model_id"], seg["environment"], seg["run_id"],
                    metadata_json, created_at, ctx.actor_id,
                ),
            )
            emit_event(
                uow, event_type="thesis.created",
                subject_kind="thesis", subject_id=thesis_id,
                payload=_payload(thesis_id, valid_from),
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
            # Emit a `supersedes` edge if parent thesis specified.
            if parent:
                edge_id = new_id("edg")
                uow.execute(
                    "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
                    "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (edge_id, "thesis", thesis_id, "thesis", parent,
                     "supersedes", created_at, ctx.actor_id),
                )
                emit_event(
                    uow, event_type="edge.created",
                    subject_kind="edge", subject_id=edge_id,
                    payload={
                        "id": edge_id, "source_kind": "thesis", "source_id": thesis_id,
                        "target_kind": "thesis", "target_id": parent,
                        "edge_type": "supersedes",
                    },
                    actor_id=ctx.actor_id, idempotency_key=None, ctx=ctx,
                )
    finally:
        db.close()
    return {"id": thesis_id, "instrument_id": instrument_id, "version": version,
            "side": side, "created_at": created_at}


# -- forecast.add ------------------------------------------------------------

_BINARY_TOLERANCE = 1e-6


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

    uow.execute(
        "INSERT INTO forecasts(id, thesis_id, kind, resolution_at, yes_label, "
        "resolution_rule_text, scoring_support, scoring_state, valid_from, valid_to, "
        "agent_id, model_id, environment, run_id, metadata_json, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            forecast_id, thesis_id, kind, resolution_at, yes_label,
            args.get("resolution_rule_text"), scoring_support,
            normalize_timestamp(args, "valid_from") or created_at,
            normalize_timestamp(args, "valid_to"),
            seg["agent_id"], seg["model_id"], seg["environment"], seg["run_id"],
            metadata_json, created_at, ctx.actor_id,
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


def _emit_forecast_scored(
    uow: UnitOfWork,
    scored: dict[str, Any],
    *,
    actor_id: str,
    ctx: ToolContext,
    scored_at: str,
) -> None:
    """Emit one `forecast.scored` event per score row written by the auto
    scorer. Used by `_forecast_add` and `_outcome_add` to mirror the score
    persistence into the events log."""

    emit_event(
        uow,
        event_type="forecast.scored",
        subject_kind="forecast",
        subject_id=scored["forecast_id"],
        payload={
            "forecast_id": scored["forecast_id"],
            "score_id": scored["score_id"],
            "outcome_id": _lookup_outcome_id_from_score(uow.conn, scored["score_id"]),
            "metric": scored.get("metric", "brier_binary"),
            "score": scored.get("score"),
            "scored_at": scored_at,
            "failure_reason": scored.get("failure_reason"),
        },
        actor_id=actor_id,
        idempotency_key=None,
        ctx=ctx,
    )


def _lookup_outcome_id_from_score(conn, score_id: str) -> str | None:
    row = conn.execute(
        "SELECT outcome_id FROM forecast_scores WHERE id = ?", (score_id,)
    ).fetchone()
    return row[0] if row else None


def _maybe_inject_late_flag(args: dict[str, Any], *, late_recorded: bool) -> str:
    """Return the metadata_json string for the forecast row, optionally
    injecting `late_recorded: true` so the flag travels with the forecast
    itself (not just the score row) per dogfood-protocol §2.3.
    """

    raw = args.get("metadata_json")
    if isinstance(raw, str):
        try:
            obj = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            obj = {}
    elif isinstance(raw, dict):
        obj = dict(raw)
    else:
        obj = {}
    if late_recorded:
        obj["late_recorded"] = True
    return json.dumps(obj, sort_keys=True, default=str)


# -- decision.add ------------------------------------------------------------

def _decision_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    decision_type = require(args, "type")
    validate_decision_fields(decision_type, args)
    reject_if_contains_secrets(args.get("reason"), field="reason")
    tags = _store_tags(args.get("tags"))
    seg = common_metadata(args)
    idempotency_key = args.get("idempotency_key")
    review_by = normalize_timestamp(args, "review_by")
    metadata_json = _store_metadata_json(args)
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
                return {"id": decision_id, "type": decision_type,
                        "instrument_id": args.get("instrument_id"),
                        "snapshot_id": args.get("snapshot_id"),
                        "tags": tags, "created_at": row[0],
                        "review_by": row[1]}

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
    finally:
        db.close()
    return {"id": decision_id, "type": decision_type,
            "instrument_id": args.get("instrument_id"),
            "snapshot_id": args.get("snapshot_id"), "tags": tags,
            "created_at": created_at, "review_by": review_by}


# -- outcome.add / resolve.record ------------------------------------------

def _outcome_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    instrument_id = require(args, "instrument_id")
    resolved_at = normalize_timestamp(args, "resolved_at", required=True)
    outcome_label = require(args, "outcome_label")
    status = require(args, "status")
    idempotency_key = args.get("idempotency_key")
    seg = common_metadata(args)
    metadata_json = _store_metadata_json(args)

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
                    "SELECT created_at FROM outcomes WHERE id = ?", (outcome_id,)
                ).fetchone()
                return {"id": outcome_id, "instrument_id": instrument_id,
                        "status": status, "resolved_at": resolved_at,
                        "auto_scored_forecasts": [],
                        "created_at": row[0]}

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
            # Auto-scoring per scoring.md §6 / §5 hard invariant.
            if status == "resolved_final":
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
            "created_at": created_at}


def _autoscore_pending_forecasts(
    conn,
    *,
    instrument_id: str,
    outcome_id: str,
    outcome_label: str,
    actor_id: str,
    created_at: str,
) -> list[dict[str, Any]]:
    """Brier-score every supported binary forecast linked to this outcome's
    instrument when an outcome.recorded with status=resolved_final lands.

    Implements scoring.md §3 (single-probability form), §3.2 (yes_label
    heuristic), §4.2 (scoring_state transitions), §4.4 (failure_reason
    enum), and §5.1 (outcome supersession appends a fresh score row).
    Late-recorded forecasts are flagged per dogfood-protocol §2.3.

    Idempotency contract for the same outcome: a forecast already scored
    against THIS `outcome_id` is skipped, so re-firing the trigger does
    not double-write. A different `outcome_id` (e.g. a supersession of
    the prior outcome) appends a fresh row per §5.1.
    """

    cur = conn.execute(
        """
        SELECT f.id, f.kind, f.scoring_support, f.yes_label, f.resolution_at, f.created_at
        FROM forecasts f
        JOIN theses t ON t.id = f.thesis_id
        WHERE t.instrument_id = ?
          AND f.scoring_support = 'supported'
        """,
        (instrument_id,),
    )
    forecasts = cur.fetchall()
    results = []
    for fc in forecasts:
        forecast_id = fc[0]
        # Skip if THIS forecast already has a score against THIS outcome.
        existing = conn.execute(
            "SELECT 1 FROM forecast_scores WHERE forecast_id = ? AND outcome_id = ?",
            (forecast_id, outcome_id),
        ).fetchone()
        if existing is not None:
            continue
        scored = _score_one_forecast(
            conn,
            forecast_row=fc,
            outcome_id=outcome_id,
            outcome_label=outcome_label,
            actor_id=actor_id,
            scored_at=created_at,
        )
        results.append(scored)
    return results


def _score_one_forecast(
    conn,
    *,
    forecast_row: tuple,
    outcome_id: str,
    outcome_label: str,
    actor_id: str,
    scored_at: str,
) -> dict[str, Any]:
    """Compute one Brier score against a specific outcome and persist a
    `forecast_scores` row. Returns a summary dict with `forecast_id`,
    `score_id`, `score`, `failure_reason`, and `late_recorded`.

    Caller is responsible for skipping forecasts that are already scored
    against this outcome (`_autoscore_pending_forecasts` does this; the
    late-forecast path in `_forecast_add` calls this directly because the
    forecast is brand new and definitionally unscored)."""

    forecast_id = forecast_row[0]
    kind = forecast_row[1]
    yes_label = forecast_row[3]
    resolution_at = forecast_row[4]
    fcreated_at = forecast_row[5]
    resolved_label_norm = outcome_label.strip().lower()
    metric = "brier_binary"

    outcomes_cur = conn.execute(
        "SELECT id, outcome_label, probability FROM forecast_outcomes WHERE forecast_id = ?",
        (forecast_id,),
    )
    rows = outcomes_cur.fetchall()
    labels = {r[1].strip().lower(): (r[0], r[2]) for r in rows}

    yes_norm = yes_label.strip().lower() if yes_label else None
    if kind == "binary" and yes_norm is None:
        # Heuristic per scoring.md §3.2.
        if "yes" in labels:
            yes_norm = "yes"
        elif "true" in labels:
            yes_norm = "true"
        elif resolved_label_norm in labels and len(labels) == 2:
            yes_norm = resolved_label_norm

    failure_reason: str | None = None
    score: float | None = None
    if kind == "binary" and len(rows) != 2:
        failure_reason = "yes_label_ambiguous"
    elif kind == "binary" and (yes_norm is None or yes_norm not in labels):
        failure_reason = "yes_label_ambiguous"
    elif kind in ("binary", "categorical") and resolved_label_norm not in labels:
        failure_reason = "label_mismatch"
    elif kind == "binary":
        p_yes = labels[yes_norm][1]
        y = 1.0 if resolved_label_norm == yes_norm else 0.0
        score = (p_yes - y) ** 2
    elif kind == "categorical":
        metric = "brier_multiclass"
        score = sum((float(prob) - (1.0 if label == resolved_label_norm else 0.0)) ** 2
                    for label, (_oid, prob) in labels.items())
    elif kind == "scalar":
        metric = "squared_error_scalar"
        try:
            outcome_row = conn.execute("SELECT outcome_value FROM outcomes WHERE id = ?", (outcome_id,)).fetchone()
            raw_truth = outcome_row[0] if outcome_row and outcome_row[0] is not None else outcome_label
            truth = float(raw_truth)
            point = float(rows[0][2])
        except Exception:
            failure_reason = "scalar_value_invalid"
        else:
            score = (point - truth) ** 2
    else:
        failure_reason = "unsupported_kind"

    late_recorded, late_by_seconds = _late_recorded_calc(
        forecast_created_at=fcreated_at,
        outcome_created_at=scored_at,
        resolution_at=resolution_at,
    )

    metadata: dict[str, Any] = {"outcome_id": outcome_id}
    if failure_reason:
        metadata["failure_reason"] = failure_reason
    if late_recorded:
        metadata["late_recorded"] = True
        if late_by_seconds is not None:
            metadata["late_recorded_by_seconds"] = late_by_seconds

    score_id = new_id("fs")
    conn.execute(
        "INSERT INTO forecast_scores(id, forecast_id, outcome_id, metric, score, "
        "scored_at, actor_id, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            score_id, forecast_id, outcome_id,
            metric,
            score,
            scored_at,
            actor_id,
            json.dumps(metadata, sort_keys=True),
        ),
    )
    return {
        "forecast_id": forecast_id,
        "score_id": score_id,
        "score": score,
        "failure_reason": failure_reason,
        "late_recorded": late_recorded,
        "metric": metric,
    }


def _late_recorded_calc(
    *,
    forecast_created_at: str,
    outcome_created_at: str,
    resolution_at: str | None,
) -> tuple[bool, int | None]:
    """Return `(late_recorded, late_by_seconds)` per dogfood-protocol §2.2/§2.3.

    Late = forecast row was created at or after the outcome row, OR after
    the forecast's own resolution_at. `late_by_seconds` is positive when
    late (max of the two over-by deltas, 0 otherwise)."""

    try:
        from datetime import datetime as _dt
        fc_ts = _dt.fromisoformat(forecast_created_at.replace("Z", "+00:00"))
        out_ts = _dt.fromisoformat(outcome_created_at.replace("Z", "+00:00"))
        deltas = []
        late = fc_ts >= out_ts
        if late:
            deltas.append(int((fc_ts - out_ts).total_seconds()))
        if resolution_at:
            res_ts = _dt.fromisoformat(resolution_at.replace("Z", "+00:00"))
            if fc_ts > res_ts:
                late = True
                deltas.append(int((fc_ts - res_ts).total_seconds()))
        late_by = max(deltas) if deltas else None
        return late, late_by
    except Exception:
        return False, None


def _current_resolved_final_outcome(
    conn, *, instrument_id: str
) -> tuple[str, str, str] | None:
    """Return `(outcome_id, outcome_label, created_at)` for the head
    `resolved_final` outcome on this instrument, or None.

    "Head" = the most recent `resolved_final` row that is NOT the target of
    a `supersedes` edge from a newer `outcome` (scoring.md §5: hard
    invariant excludes superseded resolved_final outcomes from auto-score).
    """

    cur = conn.execute(
        """
        SELECT o.id, o.outcome_label, o.created_at
        FROM outcomes o
        WHERE o.instrument_id = ?
          AND o.status = 'resolved_final'
          AND NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE e.source_kind = 'outcome'
              AND e.target_kind = 'outcome'
              AND e.edge_type = 'supersedes'
              AND e.target_id = o.id
          )
        ORDER BY o.resolved_at DESC, o.created_at DESC
        LIMIT 1
        """,
        (instrument_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return (row[0], row[1], row[2])


def derive_scoring_state(conn, forecast_id: str) -> str:
    """Read-time projection of scoring_state per scoring.md §4.2.

    Persisted `forecasts.scoring_state` stays `pending` because the
    append-only trigger forbids UPDATE; the current logical state is
    derived from `forecast_scores` + supersedes edges. The mapping:

    - `superseded`: a `supersedes` edge with this forecast as the target.
    - `scored`: latest `forecast_scores` row pointing to a non-superseded
      outcome has a non-NULL score.
    - `failed`: latest such row has score IS NULL and a failure_reason.
    - `pending`: no qualifying score row.
    """

    sup = conn.execute(
        """
        SELECT 1 FROM edges
        WHERE source_kind = 'forecast' AND target_kind = 'forecast'
          AND edge_type = 'supersedes' AND target_id = ?
        LIMIT 1
        """,
        (forecast_id,),
    ).fetchone()
    if sup is not None:
        return "superseded"

    row = conn.execute(
        """
        SELECT fs.score, fs.metadata_json
        FROM forecast_scores fs
        WHERE fs.forecast_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE e.source_kind = 'outcome' AND e.target_kind = 'outcome'
              AND e.edge_type = 'supersedes' AND e.target_id = fs.outcome_id
          )
        ORDER BY fs.scored_at DESC, fs.id DESC
        LIMIT 1
        """,
        (forecast_id,),
    ).fetchone()
    if row is None:
        return "pending"
    score, metadata_json = row
    if score is not None:
        return "scored"
    try:
        meta = json.loads(metadata_json or "{}")
    except json.JSONDecodeError:
        meta = {}
    if meta.get("failure_reason"):
        return "failed"
    return "pending"


# -- source.add + source.attach_to_* ---------------------------------------

def _source_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            return _source_add_in_uow(args, ctx, uow)
    finally:
        db.close()


def _source_add_in_uow(args: dict[str, Any], ctx: ToolContext, uow: UnitOfWork) -> dict[str, Any]:
    """Create a source row using an existing transaction."""

    kind = require(args, "kind")
    reject_if_contains_secrets(args.get("title"), field="title")
    reject_if_contains_secrets(args.get("note"), field="note")
    reject_if_contains_secrets(args.get("excerpt"), field="excerpt")
    reject_if_contains_secrets(args.get("extracted_text"), field="extracted_text")
    reject_if_contains_secrets(args.get("summary"), field="summary")
    idempotency_key = args.get("idempotency_key")
    stance = args.get("stance", "neutral")
    storage_kind = args.get("storage_kind", "inline_text")
    redaction_status = args.get("redaction_status", "none")
    freshness_at = normalize_timestamp(args, "freshness_at")
    captured_at = normalize_timestamp(args, "captured_at")
    retrieved_at = normalize_timestamp(args, "retrieved_at")
    metadata_json = _store_metadata_json(args)

    def _payload(sid: str) -> dict[str, Any]:
        return {
            "id": sid, "kind": kind, "ref": args.get("ref"),
            "title": args.get("title"), "note": args.get("note"),
            "stance": stance, "freshness_at": freshness_at,
            "content_hash": args.get("content_hash"),
            "captured_at": captured_at, "uri": args.get("uri"),
            "media_type": args.get("media_type"),
            "storage_kind": storage_kind,
            "retrieved_at": retrieved_at,
            "source_author": args.get("source_author"),
            "publisher": args.get("publisher"),
            "excerpt": args.get("excerpt"),
            "extracted_text": args.get("extracted_text"),
            "summary": args.get("summary"),
            "hash_algorithm": args.get("hash_algorithm"),
            "redaction_status": redaction_status,
            "license_or_terms_note": args.get("license_or_terms_note"),
            "metadata_json": metadata_json,
        }

    replay = check_idempotency_replay(
        uow, event_type="source.added",
        actor_id=ctx.actor_id, idempotency_key=idempotency_key,
    )
    if replay is not None:
        source_id = replay["id"]
        emit_event(
            uow, event_type="source.added",
            subject_kind="source", subject_id=source_id,
            payload=_payload(source_id),
            actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
        )
        row = uow.conn.execute(
            "SELECT created_at FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        return {"id": source_id, "kind": kind, "stance": stance,
                "created_at": row[0]}

    source_id = args.get("id") or new_id("src")
    created_at = now_iso()
    uow.execute(
        "INSERT INTO sources(id, kind, ref, title, note, stance, freshness_at, "
        "content_hash, captured_at, uri, media_type, storage_kind, retrieved_at, "
        "source_author, publisher, excerpt, extracted_text, summary, "
        "hash_algorithm, redaction_status, license_or_terms_note, metadata_json, "
        "created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            source_id, kind, args.get("ref"), args.get("title"),
            args.get("note"), stance, freshness_at,
            args.get("content_hash"), captured_at, args.get("uri"),
            args.get("media_type"), storage_kind, retrieved_at,
            args.get("source_author"), args.get("publisher"),
            args.get("excerpt"), args.get("extracted_text"),
            args.get("summary"), args.get("hash_algorithm"),
            redaction_status, args.get("license_or_terms_note"),
            metadata_json, created_at, ctx.actor_id,
        ),
    )
    emit_event(
        uow, event_type="source.added",
        subject_kind="source", subject_id=source_id,
        payload=_payload(source_id),
        actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
    )
    return {"id": source_id, "kind": kind, "stance": stance,
            "created_at": created_at}


_SOURCE_ATTACH_TARGETS: dict[str, dict[str, Any]] = {
    "thesis": {
        "table": "theses",
        "tool": "source.attach_to_thesis",
        "json_schema": None,
        "example_key": "source.attach_to_thesis",
    },
    "decision": {
        "table": "decisions",
        "tool": "source.attach_to_decision",
        "json_schema": None,
        "example_key": "source.attach_to_decision",
    },
    "forecast": {
        "table": "forecasts",
        "tool": "source.attach_to_forecast",
        "json_schema": None,
        "example_key": "source.attach_to_forecast",
    },
    "memory_node": {
        "table": "memory_nodes",
        "tool": "source.attach_to_memory_node",
        "json_schema": None,
        "example_key": "source.attach_to_memory_node",
    },
}
"""Single source of truth for public source.attach_to_* target metadata.

Per bead trade-trace-l9q, each source.attach_to_<target> validates the
target row exists before writing the edge. The memory_node attacher
became functional with M3 (bead e86 + bead s3f). Bead trade-trace-4v31
keeps the public tool names separate while driving both validation and
registration from this mapping; no generic public source.attach endpoint
is registered.
"""


def _make_source_attacher(target_kind: str):
    """Build a `source.attach_to_<target>` handler. Edge type is derived from
    the source's `stance` column per PRD §4.5."""

    def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        source_id = require(args, "source_id")
        target_id = require(args, "target_id")
        idempotency_key = args.get("idempotency_key")
        metadata_json = _store_metadata_json(args)
        db = open_db_for_args(args)
        try:
            stance_row = db.connection.execute(
                "SELECT stance FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
            if stance_row is None:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"source {source_id!r} not found",
                    details={
                        "entity_kind": "source",
                        "source_id": source_id,
                    },
                )
            # Target validation per bead trade-trace-l9q: refuse to attach
            # a source to a row that does not exist. Without this guard the
            # edge would point to a phantom id and the agent would see a
            # successful write that produced an orphan edge.
            target_meta = _SOURCE_ATTACH_TARGETS.get(target_kind)
            if target_meta is None:
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    f"unsupported target_kind {target_kind!r}",
                    details={
                        "field": "target_kind",
                        "value": target_kind,
                        "allowed": sorted(_SOURCE_ATTACH_TARGETS),
                    },
                )
            target_table = target_meta["table"]
            target_row = db.connection.execute(
                f"SELECT 1 FROM {target_table} WHERE id = ?", (target_id,)
            ).fetchone()
            if target_row is None:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"{target_kind} {target_id!r} not found",
                    details={
                        "entity_kind": target_kind,
                        "target_id": target_id,
                    },
                )
            stance = stance_row[0]
            edge_type = stance if stance in ("supports", "contradicts") else "about"
            with UnitOfWork(db.connection) as uow:
                replay = check_idempotency_replay(
                    uow, event_type="source.attached",
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key,
                )
                if replay is not None:
                    edge_id = replay["id"]
                    emit_event(
                        uow, event_type="source.attached",
                        subject_kind="edge", subject_id=edge_id,
                        payload={
                            "id": edge_id, "source_id": source_id,
                            "target_kind": target_kind, "target_id": target_id,
                            "edge_type": edge_type,
                        },
                        actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                    )
                    row = uow.conn.execute(
                        "SELECT created_at FROM edges WHERE id = ?", (edge_id,)
                    ).fetchone()
                    return {"id": edge_id, "source_id": source_id,
                            "target_kind": target_kind, "target_id": target_id,
                            "edge_type": edge_type, "created_at": row[0]}

                edge_id = args.get("id") or new_id("edg")
                created_at = now_iso()
                uow.execute(
                    "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
                    "edge_type, metadata_json, created_at, actor_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        edge_id, "source", source_id, target_kind, target_id, edge_type,
                        metadata_json, created_at, ctx.actor_id,
                    ),
                )
                emit_event(
                    uow, event_type="source.attached",
                    subject_kind="edge", subject_id=edge_id,
                    payload={
                        "id": edge_id, "source_id": source_id,
                        "target_kind": target_kind, "target_id": target_id,
                        "edge_type": edge_type,
                    },
                    actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
                )
        finally:
            db.close()
        return {"id": edge_id, "source_id": source_id, "target_kind": target_kind,
                "target_id": target_id, "edge_type": edge_type, "created_at": created_at}

    return _handler


def _source_attach_to_memory_node_in_uow(args: dict[str, Any], ctx: ToolContext, uow: UnitOfWork) -> dict[str, Any]:
    """Attach a source to a memory_node using an existing transaction."""

    source_id = require(args, "source_id")
    target_id = require(args, "target_id")
    idempotency_key = args.get("idempotency_key")
    metadata_json = _store_metadata_json(args)
    stance_row = uow.conn.execute(
        "SELECT stance FROM sources WHERE id = ?", (source_id,),
    ).fetchone()
    if stance_row is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"source {source_id!r} not found",
            details={"entity_kind": "source", "source_id": source_id},
        )
    target_row = uow.conn.execute(
        "SELECT 1 FROM memory_nodes WHERE id = ?", (target_id,),
    ).fetchone()
    if target_row is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"memory_node {target_id!r} not found",
            details={"entity_kind": "memory_node", "target_id": target_id},
        )
    stance = stance_row[0]
    edge_type = stance if stance in ("supports", "contradicts") else "about"
    replay = check_idempotency_replay(
        uow, event_type="source.attached",
        actor_id=ctx.actor_id, idempotency_key=idempotency_key,
    )
    if replay is not None:
        edge_id = replay["id"]
        emit_event(
            uow, event_type="source.attached",
            subject_kind="edge", subject_id=edge_id,
            payload={
                "id": edge_id, "source_id": source_id,
                "target_kind": "memory_node", "target_id": target_id,
                "edge_type": edge_type,
            },
            actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
        )
        row = uow.conn.execute(
            "SELECT created_at FROM edges WHERE id = ?", (edge_id,),
        ).fetchone()
        return {"id": edge_id, "source_id": source_id, "target_kind": "memory_node",
                "target_id": target_id, "edge_type": edge_type, "created_at": row[0]}

    edge_id = args.get("id") or new_id("edg")
    created_at = now_iso()
    uow.execute(
        "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
        "edge_type, metadata_json, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (edge_id, "source", source_id, "memory_node", target_id, edge_type,
         metadata_json, created_at, ctx.actor_id),
    )
    emit_event(
        uow, event_type="source.attached",
        subject_kind="edge", subject_id=edge_id,
        payload={
            "id": edge_id, "source_id": source_id,
            "target_kind": "memory_node", "target_id": target_id,
            "edge_type": edge_type,
        },
        actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
    )
    return {"id": edge_id, "source_id": source_id, "target_kind": "memory_node",
            "target_id": target_id, "edge_type": edge_type, "created_at": created_at}


# -- resolve.pending ---------------------------------------------------------

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
              AND NOT EXISTS (
                SELECT 1 FROM outcomes o
                WHERE o.instrument_id = t.instrument_id
                  AND o.status = 'resolved_final'
              )
            ORDER BY f.resolution_at ASC, f.id ASC
            LIMIT ?
            """,
            (limit,),
        )
        items = [
            {
                "forecast_id": row[0],
                "thesis_id": row[1],
                "kind": row[2],
                "resolution_at": row[3],
                "instrument_id": row[4],
            }
            for row in cur.fetchall()
        ]
    finally:
        db.close()
    return {"items": items, "count": len(items), "truncated": len(items) == limit}


# -- forecast.supersede ------------------------------------------------------

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


# -- registration ------------------------------------------------------------


# Hand-crafted JSON schema for decision.add per bead trade-trace-hsnz.
# Auto-derivation from example_minimal=actual_enter forced `quantity`/`price`
# as required, but the decision matrix marks them X (forbidden) for `watch`
# and `skip`. Required set here is the intersection across all matrix rows:
# every row has `instrument_id` R, and `type` discriminates the row, so
# `type`, `instrument_id`, and `idempotency_key` are the only schema-level
# required fields. The runtime decision matrix in `decision_matrix.py`
# enforces per-type R/X constraints uniformly and returns a typed
# VALIDATION_ERROR envelope on violation.
# Hand-crafted JSON schema for source.add per bead trade-trace-2ya5.
# Storage migrations 003 pin `kind` to a 10-value enum and `stance` to a
# 3-value enum; the auto-derived schema only emitted the field types as
# strings, so an agent following `tool.schema --tool source.add` saw a
# valid-looking payload that storage then rejected with a raw SQLite
# CHECK constraint error. Surfacing the enums here lets the agent pick a
# valid value up-front.
_SOURCE_ADD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": [
                "url", "pdf", "image", "tweet", "news_article",
                "research_doc", "transcript", "chart_image", "note", "other",
            ],
        },
        "stance": {
            "type": "string",
            "enum": ["supports", "contradicts", "neutral"],
        },
        "uri": {"type": "string"},
        "title": {"type": "string"},
        "note": {"type": "string"},
        "ref": {"type": "string"},
        "freshness_at": {
            "type": "string",
            "description": (
                "ISO-8601 timestamp for when the evidence itself was current. "
                "report.source_quality stale_sources uses this field versus "
                "decision.created_at; set it when you want stale-evidence checks."
            ),
        },
        "content_hash": {"type": "string"},
        "captured_at": {"type": "string"},
        "media_type": {"type": "string"},
        "storage_kind": {
            "type": "string",
            "enum": ["url", "local_path", "inline_text", "external_ref"],
        },
        "retrieved_at": {
            "type": "string",
            "description": (
                "ISO-8601 timestamp for when this source was fetched/recorded as "
                "provenance. It does not drive report.source_quality stale_sources; "
                "use freshness_at for evidence freshness."
            ),
        },
        "source_author": {"type": "string"},
        "publisher": {"type": "string"},
        "excerpt": {"type": "string"},
        "extracted_text": {"type": "string"},
        "summary": {"type": "string"},
        "redaction_status": {"type": "string"},
        "metadata_json": {"type": "object"},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["kind", "idempotency_key"],
    "description": (
        "source.add — kind and stance use storage-pinned enums "
        "(persistence.md §5.2 / migration 003). Free-text fields "
        "(title/note/excerpt/extracted_text/summary) are scanned at "
        "write time for sensitive-shaped substrings per trade-trace-sy1. "
        "freshness_at is the evidence-current timestamp used by "
        "report.source_quality stale_sources; retrieved_at is retrieval/provenance "
        "time only."
    ),
}


_INSTRUMENT_ADD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "venue_id": {"type": "string"},
        "asset_class": {"type": "string"},
        "title": {"type": "string"},
        "external_id": {"type": "string"},
        "symbol": {"type": "string"},
        "currency_or_collateral": {"type": "string"},
        "expiration_or_resolution_at": {"type": "string"},
        "resolution_criteria_text": {"type": "string"},
        "contract_multiplier": {"type": "number"},
        "metadata_json": {"type": "object"},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["venue_id", "asset_class", "title", "idempotency_key"],
    "description": (
        "instrument.add — create an instrument. Optional audit/venue fields "
        "are accepted and persisted when provided."
    ),
}


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
        "for per-type required/optional/forbidden fields."
    ),
    "x-decision-matrix": _DECISION_MATRIX_CONTRACT,
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
            "thesis_id": "thes_THESIS_ID_HERE",
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


def register_ledger_tools(registry: ToolRegistry) -> None:
    """Register all M1 manual ledger / source / resolution write tools."""

    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    registry.register("venue.add", _venue_add, is_write=True, **_examples_for("venue.add"))
    registry.register(
        "instrument.add",
        _instrument_add,
        is_write=True,
        json_schema=_INSTRUMENT_ADD_SCHEMA,
        **_examples_for("instrument.add"),
    )
    registry.register(
        "snapshot.add",
        _snapshot_add,
        is_write=True,
        optional_keys=(
            "price",
            "source",
            "source_url",
            "bid",
            "ask",
            "mid",
            "spread",
            "volume",
            "open_interest",
            "implied_probability",
            "liquidity_depth_json",
            "metadata_json",
        ),
        **_examples_for("snapshot.add"),
    )
    registry.register("thesis.add", _thesis_add, is_write=True, **_examples_for("thesis.add"))
    registry.register("forecast.add", _forecast_add, is_write=True, **_examples_for("forecast.add"))
    registry.register("forecast.supersede", _forecast_supersede, is_write=True, **_examples_for("forecast.supersede"))
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
        examples=("tt decision add --instrument-id inst_... --type enter --side long --thesis-id th_... --idempotency-key <uuid>",),
        enum_notes={"type": "Allowed values and per-type field requirements live in json_schema.x-decision-matrix.", "side": "Use long/short only for directional decision types."},
        common_failures=("Missing a field required by the selected decision type.", "Providing a forbidden field for the selected decision type."),
        next_actions=("Inspect `tt tool schema --tool decision.add` before retrying validation failures.",),
        **_examples_for("decision.add"),
    )
    registry.register("outcome.add", _outcome_add, is_write=True, **_examples_for("outcome.add"))
    # resolve.record is an alias for outcome.add (PRD §4.4).
    registry.register("resolve.record", _outcome_add, is_write=True, **_examples_for("outcome.add"))
    registry.register("resolve.pending", _resolve_pending)
    registry.register("source.add", _source_add, is_write=True, json_schema=_SOURCE_ADD_SCHEMA, **_examples_for("source.add"))
    for target_kind, target_meta in _SOURCE_ATTACH_TARGETS.items():
        tool_name = target_meta["tool"]
        example_key = target_meta["example_key"]
        json_schema = target_meta["json_schema"]
        register_kwargs = {
            "is_write": True,
            **_examples_for(example_key),
        }
        if json_schema is not None:
            register_kwargs["json_schema"] = json_schema
        registry.register(
            tool_name,
            _make_source_attacher(target_kind),
            **register_kwargs,
        )
