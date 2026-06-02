"""Forecast scoring helpers extracted from the monolithic
`tools/ledger.py` per bead trade-trace-ji9c.

Implements scoring.md §3 (single-probability form), §3.2 (yes_label
heuristic), §4.2 (scoring_state transitions), §4.4 (failure_reason
enum), §5.1 (supersession appends a fresh score row), and §6
(late-recorded trigger #2).

Imported by `ledger/forecast.py` (late-forecast trigger #2 inside
`forecast.add`), `ledger/outcome.py` (auto-score on
`status='resolved_final'`), and read-only by `journal.repair` /
`journal.rescan_scoring` via re-export from `ledger/__init__.py`.
"""

from __future__ import annotations

import json
from typing import Any

from trade_trace.contracts.tool_registry import ToolContext
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import emit_event, new_id
from trade_trace.tools.ledger._finality import is_auto_scoreable_final

# Probability sums must be within this tolerance of 1.0 to satisfy the
# binary / categorical validators (PRD §4.3).
_BINARY_TOLERANCE = 1e-6


def _emit_forecast_scored(
    uow: UnitOfWork,
    scored: dict[str, Any],
    *,
    actor_id: str,
    ctx: ToolContext,
    scored_at: str,
) -> None:
    """Emit one `forecast.scored` event per score row written by the auto
    scorer. Used by `forecast.add` and `outcome.add` to mirror the score
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
          AND NOT (
            EXISTS (
              SELECT 1 FROM events e
              WHERE e.subject_id = f.id
                AND e.event_type = 'forecast.blind_committed'
            )
            AND NOT EXISTS (
              SELECT 1 FROM forecast_independence_locks fil
              WHERE fil.forecast_id = f.id
                AND fil.independence_proven = 1
            )
          )
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
    late-forecast path in `forecast.add` calls this directly because the
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
    legacy_has_null_label = any(r[1] is None for r in rows)
    labels = {r[1].strip().lower(): (r[0], r[2]) for r in rows if r[1] is not None}

    yes_norm = yes_label.strip().lower() if yes_label else None
    canonical_row = conn.execute(
        "SELECT probability FROM forecasts WHERE id = ?", (forecast_id,),
    ).fetchone()
    canonical_probability = canonical_row[0] if canonical_row else None
    if kind == "binary" and canonical_probability is not None and yes_norm is None:
        if resolved_label_norm in {"yes", "true"}:
            yes_norm = resolved_label_norm
        elif resolved_label_norm in {"no", "false"}:
            yes_norm = "yes" if resolved_label_norm == "no" else "true"
    if kind == "binary" and canonical_probability is None and yes_norm is None:
        # Heuristic per scoring.md §3.2.
        if "yes" in labels:
            yes_norm = "yes"
        elif "true" in labels:
            yes_norm = "true"
        elif resolved_label_norm in labels and len(labels) == 2:
            yes_norm = resolved_label_norm

    failure_reason: str | None = None
    score: float | None = None
    if legacy_has_null_label:
        failure_reason = "yes_label_ambiguous"
    elif kind == "binary" and yes_norm is None:
        failure_reason = "yes_label_ambiguous"
    elif kind == "binary" and canonical_probability is not None:
        if labels and resolved_label_norm not in labels:
            failure_reason = "label_mismatch"
        else:
            p_yes = float(canonical_probability)
            y = 1.0 if resolved_label_norm == yes_norm else 0.0
            score = (p_yes - y) ** 2
    elif kind == "binary" and len(rows) != 2:
        failure_reason = "yes_label_ambiguous"
    elif kind == "binary" and yes_norm not in labels:
        failure_reason = "yes_label_ambiguous"
    elif kind == "binary" and resolved_label_norm not in labels:
        failure_reason = "label_mismatch"
    elif kind == "binary":
        p_yes = labels[yes_norm][1]
        y = 1.0 if resolved_label_norm == yes_norm else 0.0
        score = (p_yes - y) ** 2
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
        SELECT o.id, o.outcome_label, o.created_at, o.status, o.confidence
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
        """,
        (instrument_id,),
    )
    for row in cur.fetchall():
        if is_auto_scoreable_final(status=row[3], confidence=row[4], outcome_label=row[1]):
            return (row[0], row[1], row[2])
    return None


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
