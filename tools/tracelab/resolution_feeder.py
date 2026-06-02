"""Manual resolution feeder guardrails for TraceLab.

This sidecar wraps the public ``resolution.add``/``outcome.add`` path with the
operator-facing checks needed to avoid silent zero-scoring runs: only
high-confidence binary final payloads are submitted, markets without scoreable
forecasts are counted separately, and the human-entered winning outcome must be
confirmed twice before the write call is made.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trade_trace.mcp_server import mcp_call
from trade_trace.storage.database import open_database_readonly
from trade_trace.storage.paths import db_path

BINARY_LABELS = {"yes", "no", "true", "false"}
MIN_CONFIDENCE = 0.9


class ResolutionFeederError(ValueError):
    """Raised when a manual resolution payload is unsafe to submit."""


@dataclass(frozen=True)
class ManualResolution:
    instrument_id: str
    resolved_at: str
    outcome_label: str
    confidence: float | None
    confirm_outcome_label: str | None = None
    outcome_value: float | None = None
    idempotency_key: str | None = None


@dataclass
class FeederResult:
    submitted: list[dict[str, Any]] = field(default_factory=list)
    refused: list[dict[str, Any]] = field(default_factory=list)
    resolved_but_no_forecast_count: int = 0
    resolved_but_unfed_count: int = 0

    @property
    def submitted_count(self) -> int:
        return len(self.submitted)

    @property
    def refused_count(self) -> int:
        return len(self.refused)

    def health(self) -> dict[str, int]:
        return {
            "submitted": self.submitted_count,
            "refused": self.refused_count,
            "resolved_but_no_forecast": self.resolved_but_no_forecast_count,
            "resolved_but_unfed": self.resolved_but_unfed_count,
        }


def validate_resolution_payload(resolution: ManualResolution) -> None:
    """Pre-check 1 + dual-check for a human-entered manual resolution."""

    if resolution.confidence is None:
        raise ResolutionFeederError("confidence is required and must be >= 0.9")
    if resolution.confidence < MIN_CONFIDENCE:
        raise ResolutionFeederError("confidence must be >= 0.9")
    label = resolution.outcome_label.strip().lower()
    if label not in BINARY_LABELS:
        raise ResolutionFeederError(
            "outcome_label must be one of yes/no/true/false"
        )
    if resolution.confirm_outcome_label is None:
        raise ResolutionFeederError("second winning-outcome confirmation is required")
    if resolution.confirm_outcome_label.strip().lower() != label:
        raise ResolutionFeederError("winning-outcome confirmation does not match")


def scoreable_forecast_count(home: str | Path, instrument_id: str) -> int:
    """Return committed/revealed scoreable forecasts for an instrument.

    The ledger's public scoring path considers forecasts scoreable when they are
    attached to the instrument through a thesis, have supported scoring, and are
    not superseded. This read is intentionally OS-enforced read-only.
    """

    db = open_database_readonly(db_path(Path(home)))
    try:
        row = db.connection.execute(
            """
            SELECT COUNT(*)
            FROM forecasts f
            JOIN theses t ON t.id = f.thesis_id
            WHERE t.instrument_id = ?
              AND f.scoring_support = 'supported'
              AND f.scoring_state IN ('pending', 'scored')
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
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        db.close()


def resolved_but_unfed_count(home: str | Path) -> int:
    """Count scoreable final outcomes that have no forecast_scores rows."""

    db = open_database_readonly(db_path(Path(home)))
    try:
        row = db.connection.execute(
            """
            SELECT COUNT(*)
            FROM outcomes o
            WHERE o.status = 'resolved_final'
              AND o.confidence >= ?
              AND lower(trim(o.outcome_label)) IN ('yes', 'no', 'true', 'false')
              AND NOT EXISTS (
                  SELECT 1 FROM forecast_scores fs WHERE fs.outcome_id = o.id
              )
            """,
            (MIN_CONFIDENCE,),
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        db.close()


def feed_manual_resolutions(
    home: str | Path,
    resolutions: list[ManualResolution],
    *,
    actor_id: str = "agent:tracelab-resolution-feeder",
) -> FeederResult:
    """Validate and submit manual resolutions through ``resolution.add``.

    Markets with no pre-existing scoreable forecast are not submitted; they are
    counted as ``resolved_but_no_forecast`` so the run cannot look like a clean
    zero-score run. Existing resolved finals without score rows are also emitted
    as the separate ``resolved_but_unfed`` lag signal.
    """

    result = FeederResult()
    for resolution in resolutions:
        try:
            validate_resolution_payload(resolution)
        except ResolutionFeederError as exc:
            result.refused.append({"instrument_id": resolution.instrument_id, "reason": str(exc)})
            continue

        forecast_count = scoreable_forecast_count(home, resolution.instrument_id)
        if forecast_count < 1:
            result.resolved_but_no_forecast_count += 1
            result.refused.append({
                "instrument_id": resolution.instrument_id,
                "reason": "no committed/revealed scoreable forecast exists",
            })
            continue

        payload: dict[str, Any] = {
            "home": str(home),
            "instrument_id": resolution.instrument_id,
            "resolved_at": resolution.resolved_at,
            "outcome_label": resolution.outcome_label.strip().lower(),
            "status": "resolved_final",
            "confidence": resolution.confidence,
            "source": "manual",
        }
        if resolution.outcome_value is not None:
            payload["outcome_value"] = resolution.outcome_value
        if resolution.idempotency_key is not None:
            payload["idempotency_key"] = resolution.idempotency_key
        envelope = mcp_call("resolution.add", payload, actor_id=actor_id).model_dump(
            mode="json", exclude_none=True
        )
        if not envelope.get("ok"):
            result.refused.append({
                "instrument_id": resolution.instrument_id,
                "reason": envelope.get("error", {}).get("message", "resolution.add failed"),
                "envelope": envelope,
            })
        else:
            result.submitted.append(envelope["data"])

    result.resolved_but_unfed_count = resolved_but_unfed_count(home)
    return result
