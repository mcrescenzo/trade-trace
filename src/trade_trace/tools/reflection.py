"""reflection.prompt_for_outcome per bead trade-trace-wnj.

Build a deterministic prompt packet for the agent to consult before
writing a reflection on a resolved outcome. The tool does NO LLM call
and NO network IO — every field is derived from the journal. The
returned packet's JSON form is byte-identical across calls with the
same inputs and same fixture state (the deterministic invariant
verified by the wnj acceptance tests).

Usage from an agent:

    packet = reflection.prompt_for_outcome(outcome_id, ...)
    # ... agent reasons ...
    memory.reflect(target_kind="outcome", target_id=outcome_id, body=...)
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.tools._helpers import open_db_for_args, require
from trade_trace.tools.errors import ToolError


def _packet_for(
    conn: sqlite3.Connection,
    *,
    outcome_id: str,
    include_forecast: bool,
    include_thesis: bool,
    include_prior_reflections: bool,
    as_of: str | None,
) -> dict[str, Any]:
    """Construct the deterministic packet. Every field is sorted by id
    so the JSON output is byte-stable across runs."""

    outcome_row = conn.execute(
        "SELECT id, instrument_id, resolved_at, outcome_label, "
        "outcome_value, status FROM outcomes WHERE id = ?",
        (outcome_id,),
    ).fetchone()
    if outcome_row is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"outcome {outcome_id!r} not found",
            details={"entity_kind": "outcome", "outcome_id": outcome_id},
        )
    instrument_id = outcome_row[1]
    outcome_label = outcome_row[3].strip().lower() if outcome_row[3] else None

    forecast_row = None
    forecast_outcomes: list[dict[str, Any]] = []
    calibration_delta = None
    if include_forecast:
        # Per trade-trace-vzmq: prefer the forecast linked to THIS
        # outcome via `forecast_scores`, not the earliest forecast on
        # the same instrument. Multi-forecast instruments (e.g., a
        # re-forecast after a forecast.supersede) would otherwise
        # return the wrong forecast for a later resolution.
        forecast_row = conn.execute(
            """
            SELECT f.id, f.thesis_id, f.kind, f.yes_label,
                   f.resolution_at, f.created_at, f.scoring_state,
                   t.instrument_id
            FROM forecasts f
            JOIN theses t ON t.id = f.thesis_id
            JOIN forecast_scores fs ON fs.forecast_id = f.id
            WHERE fs.outcome_id = ?
            ORDER BY fs.scored_at, fs.id
            LIMIT 1
            """,
            (outcome_id,),
        ).fetchone()
        if forecast_row is None:
            # Fallback: the outcome has no scored forecast yet (e.g.,
            # an unsupported scoring path or a manual outcome). Fall
            # back to the earliest forecast on the same instrument
            # to preserve the pre-vzmq behavior for those cases.
            forecast_row = conn.execute(
                """
                SELECT f.id, f.thesis_id, f.kind, f.yes_label,
                       f.resolution_at, f.created_at, f.scoring_state,
                       t.instrument_id
                FROM forecasts f
                JOIN theses t ON t.id = f.thesis_id
                WHERE t.instrument_id = ?
                ORDER BY f.created_at, f.id
                LIMIT 1
                """,
                (instrument_id,),
            ).fetchone()
        if forecast_row is not None:
            fid = forecast_row[0]
            cur = conn.execute(
                "SELECT outcome_label, probability FROM forecast_outcomes "
                "WHERE forecast_id = ? ORDER BY outcome_label",
                (fid,),
            )
            forecast_outcomes = [
                {"outcome_label": r[0], "probability": r[1]}
                for r in cur.fetchall()
            ]
            # Calibration delta: |p_realized - p_predicted| on the
            # winning label, computed once and serialized.
            for fo in forecast_outcomes:
                if fo["outcome_label"].strip().lower() == outcome_label:
                    realized = 1.0 if outcome_row[5] == "resolved_final" else None
                    if realized is not None:
                        calibration_delta = round(
                            abs(realized - fo["probability"]), 6,
                        )
                    break

    thesis_row = None
    if include_thesis:
        # Per trade-trace-vzmq: the thesis is the one the originating
        # forecast actually referenced (forecast.thesis_id), not just
        # the earliest thesis on the instrument. Fall back to the
        # earliest-on-instrument behavior only when there's no
        # originating forecast (include_forecast=False or no scored
        # forecast for this outcome).
        if forecast_row is not None:
            thesis_id = forecast_row[1]
            thesis_row = conn.execute(
                """
                SELECT t.id, t.side, t.body, t.confidence_label, t.created_at
                FROM theses t
                WHERE t.id = ?
                """,
                (thesis_id,),
            ).fetchone()
        if thesis_row is None:
            thesis_row = conn.execute(
                """
                SELECT t.id, t.side, t.body, t.confidence_label, t.created_at
                FROM theses t
                WHERE t.instrument_id = ?
                ORDER BY t.created_at, t.id
                LIMIT 1
                """,
                (instrument_id,),
            ).fetchone()

    prior_reflections: list[dict[str, Any]] = []
    if include_prior_reflections:
        sql = """
            SELECT n.id, n.body, n.created_at, n.importance
            FROM memory_nodes n
            JOIN edges e ON e.source_kind = 'memory_node'
                        AND e.source_id = n.id
                        AND e.edge_type = 'about'
            WHERE n.node_type = 'reflection'
              AND (e.target_kind = 'instrument' AND e.target_id = ?
                   OR e.target_kind = 'outcome' AND e.target_id IN (
                       SELECT id FROM outcomes WHERE instrument_id = ?
                   ))
        """
        params: list[Any] = [instrument_id, instrument_id]
        if as_of is not None:
            sql += " AND n.valid_from <= ? AND (n.valid_to IS NULL OR ? < n.valid_to) AND (n.invalidated_at IS NULL OR n.invalidated_at > ?)"
            params.extend([as_of, as_of, as_of])
        sql += " ORDER BY n.created_at, n.id LIMIT 50"
        cur = conn.execute(sql, tuple(params))
        prior_reflections = [
            {"id": r[0], "body": r[1],
             "created_at": r[2], "importance": r[3]}
            for r in cur.fetchall()
        ]

    packet: dict[str, Any] = {
        "outcome": {
            "id": outcome_row[0], "instrument_id": instrument_id,
            "resolved_at": outcome_row[2], "outcome_label": outcome_row[3],
            "outcome_value": outcome_row[4], "status": outcome_row[5],
        },
        "forecast": None,
        "thesis": None,
        "prior_reflections": prior_reflections,
        "calibration_delta": calibration_delta,
        "as_of": as_of,
        "flags": {
            "include_forecast": include_forecast,
            "include_thesis": include_thesis,
            "include_prior_reflections": include_prior_reflections,
        },
    }
    if include_forecast and forecast_row is not None:
        packet["forecast"] = {
            "id": forecast_row[0], "thesis_id": forecast_row[1],
            "kind": forecast_row[2], "yes_label": forecast_row[3],
            "resolution_at": forecast_row[4],
            "created_at": forecast_row[5],
            "scoring_state": forecast_row[6],
            "outcomes": forecast_outcomes,
        }
    if include_thesis and thesis_row is not None:
        packet["thesis"] = {
            "id": thesis_row[0], "side": thesis_row[1], "body": thesis_row[2],
            "confidence_label": thesis_row[3], "created_at": thesis_row[4],
        }
    packet_json = json.dumps(packet, sort_keys=True, default=str)
    packet["packet_sha256"] = hashlib.sha256(packet_json.encode("utf-8")).hexdigest()
    return packet


def _reflection_prompt_for_outcome(
    args: dict[str, Any], ctx: ToolContext,
) -> dict[str, Any]:
    """`reflection.prompt_for_outcome` — deterministic packet builder.

    NO LLM invocation. NO network. Every field is derived from the
    journal under a bi-temporal `as_of` filter on prior reflections
    (matching memory.recall semantics).
    """

    outcome_id = require(args, "outcome_id")
    include_forecast = args.get("include_forecast", True)
    include_thesis = args.get("include_thesis", True)
    include_prior_reflections = args.get("include_prior_reflections", True)
    as_of = args.get("as_of")
    for name, value in (
        ("include_forecast", include_forecast),
        ("include_thesis", include_thesis),
        ("include_prior_reflections", include_prior_reflections),
    ):
        if not isinstance(value, bool):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{name} must be bool",
                details={"field": name, "value": value},
            )
    db = open_db_for_args(args)
    try:
        packet = _packet_for(
            db.connection,
            outcome_id=outcome_id,
            include_forecast=include_forecast,
            include_thesis=include_thesis,
            include_prior_reflections=include_prior_reflections,
            as_of=as_of,
        )
    finally:
        db.close()
    return packet


def register_reflection_tools(registry: ToolRegistry) -> None:
    registry.register(
        "reflection.prompt_for_outcome",
        _reflection_prompt_for_outcome,
        description=(
            "Deterministic prompt packet for outcome reflection. Bundles "
            "the resolved outcome row, the originating forecast and "
            "thesis (optional), prior reflections on the same instrument "
            "or outcome (optional, bi-temporal filtered), and the "
            "calibration_delta. NO LLM, NO network. Packet's "
            "packet_sha256 field hashes the JSON for replay-equality "
            "verification. Consumer writes back via memory.reflect."
        ),
    )
