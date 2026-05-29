"""UTC timestamp validation/normalization per operability.md §2.1.

Rules (locked):

- All `*_at` columns are UTC ISO 8601 timestamps.
- Inputs without an offset are rejected with `ValidationError`.
- Inputs with a non-UTC offset are normalized to UTC at write time and stored
  as `Z`-suffixed strings (e.g. `"2026-05-18T14:32:11.123Z"`).
- Sub-second precision is preserved up to milliseconds; sub-millisecond digits
  are truncated (locked: truncate, not error). Idempotency comparison uses the
  truncated form.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

_CANONICAL_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)

# Storage policy for bead trade-trace-wmz:
#
# SQLite keeps timestamp columns as TEXT without broad CHECK/table rebuilds.
# Existing append-only journals may already contain historical TEXT values, and
# retrofitting CHECK constraints across those tables would require invasive
# rebuild/copy migrations.  The bounded invariant is therefore API-only for the
# columns listed below: public write paths must normalize through
# `to_utc_iso8601`/`normalize_timestamp`/`now_iso` before INSERT, and schema
# audit tests fail if a new timestamp-shaped TEXT column appears without being
# explicitly added to this governed set.
TIMESTAMP_API_GOVERNED_COLUMNS: frozenset[tuple[str, str]] = frozenset(
    {
        ("abstentions", "as_of"),
        ("abstentions", "created_at"),
        ("account_snapshots", "as_of"),
        ("account_snapshots", "captured_at"),
        ("account_snapshots", "effective_at"),
        ("account_snapshots", "imported_at"),
        ("account_snapshots", "retrieved_at"),
        ("autonomous_incident_records", "as_of"),
        ("autonomous_incident_records", "occurred_at"),
        ("autonomous_incident_records", "recorded_at"),
        ("autonomous_run_records", "as_of"),
        ("autonomous_run_records", "ended_at"),
        ("autonomous_run_records", "recorded_at"),
        ("autonomous_run_records", "started_at"),
        ("approval_waiver_records", "created_at"),
        ("approval_waiver_records", "decision_at"),
        ("approval_waiver_records", "expires_at"),
        ("approval_waiver_records", "revoked_at"),
        ("config", "updated_at"),
        ("decisions", "created_at"),
        ("decisions", "review_by"),
        ("decision_playbook_rules", "created_at"),
        ("edges", "created_at"),
        ("events", "created_at"),
        ("external_execution_receipts", "as_of"),
        ("external_execution_receipts", "imported_at"),
        ("external_execution_receipts", "retrieved_at"),
        ("forecast_scores", "scored_at"),
        ("forecasts", "created_at"),
        ("forecasts", "invalidated_at"),
        ("forecasts", "resolution_at"),
        ("forecasts", "updated_rationale_at"),
        ("forecasts", "valid_from"),
        ("forecasts", "valid_to"),
        ("forecast_snapshot_anchor", "created_at"),
        ("instruments", "created_at"),
        ("instruments", "expiration_or_resolution_at"),
        ("markets", "ambiguous_at"),
        ("markets", "close_at"),
        ("markets", "closed_for_trading_at"),
        ("markets", "created_at"),
        ("markets", "opened_at"),
        ("markets", "resolved_at"),
        ("markets", "resolving_at"),
        ("markets", "voided_at"),
        ("memory_nodes", "created_at"),
        ("memory_nodes", "invalidated_at"),
        ("memory_nodes", "valid_from"),
        ("memory_nodes", "valid_to"),
        ("memory_node_embeddings", "created_at"),
        ("memory_node_stats", "last_recalled_at"),
        ("memory_recall_events", "as_of"),
        ("memory_recall_events", "created_at"),
        ("outbox", "exported_at"),
        ("paper_fill_records", "recorded_at"),
        ("outcomes", "created_at"),
        ("outcomes", "resolved_at"),
        ("playbooks", "created_at"),
        ("playbook_versions", "created_at"),
        ("position_events", "created_at"),
        ("positions", "closed_at"),
        ("positions", "opened_at"),
        ("positions", "resolved_at"),
        ("positions", "updated_at"),
        ("reconciliation_records", "as_of"),
        ("reconciliation_records", "imported_at"),
        ("reconciliation_records", "recorded_at"),
        ("replay_evaluation_artifacts", "as_of"),
        ("replay_evaluation_artifacts", "evaluated_at"),
        ("replay_evaluation_artifacts", "imported_at"),
        ("pretrade_intents", "as_of"),
        ("pretrade_intents", "created_at"),
        ("risk_check_receipts", "as_of"),
        ("risk_check_receipts", "created_at"),
        ("risk_policy_versions", "created_at"),
        ("signals", "created_at"),
        ("signals", "expires_at"),
        ("snapshots", "captured_at"),
        ("snapshots", "created_at"),
        ("sources", "captured_at"),
        ("sources", "created_at"),
        ("sources", "freshness_at"),
        ("sources", "retrieved_at"),
        ("strategies", "created_at"),
        ("strategies", "updated_at"),
        ("theses", "created_at"),
        ("theses", "invalidated_at"),
        ("theses", "time_horizon_at"),
        ("theses", "valid_from"),
        ("theses", "valid_to"),
        ("venues", "created_at"),
    }
)


class TimestampValidationError(ValueError):
    """Raised when a timestamp input cannot be normalized to UTC ISO 8601."""


def is_canonical_utc_iso8601(value: str) -> bool:
    """Return True for the canonical storage form emitted by to_utc_iso8601."""

    return bool(_CANONICAL_UTC_RE.fullmatch(value))


def _parse_iso_datetime(value: str | datetime, *, field: str = "<value>") -> datetime:
    """Parse the ISO datetime surface shared by timestamp helpers."""

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TimestampValidationError(
                f"{field}: not a valid ISO 8601 timestamp ({exc})"
            ) from exc
    if isinstance(value, datetime):
        return value
    raise TimestampValidationError(
        f"{field}: expected str or datetime, got {type(value).__name__}"
    )


def to_utc_iso8601(value: str | datetime, *, field: str = "<value>") -> str:
    """Normalize an input to canonical UTC ISO 8601 with millisecond precision.

    Truncates sub-millisecond digits (the locked decision per
    operability.md §2.1). Returns a `Z`-suffixed string.
    """

    dt = _parse_iso_datetime(value, field=field)

    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise TimestampValidationError(
            f"{field}: timestamp is naive (no tz offset); supply UTC offset or 'Z'"
        )

    # Normalize to UTC and truncate to millisecond precision.
    dt_utc = dt.astimezone(UTC)
    micros = dt_utc.microsecond
    millis = micros // 1000  # truncate, do not round (locked per operability.md §2.1)
    dt_truncated = dt_utc.replace(microsecond=millis * 1000)

    iso = dt_truncated.isoformat(timespec="milliseconds")
    # `isoformat` emits `+00:00`; replace with `Z` for the canonical form.
    if iso.endswith("+00:00"):
        iso = iso[:-6] + "Z"
    return iso


def parse_report_timestamp_lenient_preserve_naive_offset(
    value: str | datetime | None,
) -> datetime | None:
    """pm_native-compatible report timestamp parsing.

    Missing/falsey and invalid inputs return None. Naive datetimes remain naive;
    aware datetimes keep their original offset, including non-UTC offsets. This
    helper deliberately does not normalize via astimezone.
    """

    if not value:
        return None
    try:
        return _parse_iso_datetime(value)
    except TimestampValidationError:
        return None


def parse_report_timestamp_lenient_naive_as_utc(
    value: str | datetime | None,
) -> datetime | None:
    """opportunity-compatible report timestamp parsing.

    Missing/falsey and invalid inputs return None. Naive datetimes are treated as
    UTC by attaching UTC tzinfo. Aware datetimes keep their original offset; this
    helper deliberately does not normalize non-UTC offsets via astimezone.
    """

    dt = parse_report_timestamp_lenient_preserve_naive_offset(value)
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=UTC)
    return dt


def parse_report_timestamp_strict_utc_naive_as_utc(
    value: str | datetime | None,
) -> datetime:
    """lifecycle/strategy_health-like strict UTC report timestamp parsing.

    Missing/falsey and invalid inputs raise ValueError. Naive datetimes are
    treated as UTC by attaching UTC tzinfo. Aware datetimes are normalized to UTC
    with astimezone(UTC).
    """

    if not value:
        raise ValueError("report timestamp is required")
    try:
        dt = _parse_iso_datetime(value)
    except TimestampValidationError as exc:
        raise ValueError(str(exc)) from exc
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_report_timestamp_utc_or_none(value: str | datetime | None) -> datetime | None:
    """source_quality-compatible canonical UTC report timestamp parsing.

    Missing/falsey, invalid, and naive inputs return None. Valid aware inputs are
    canonicalized through to_utc_iso8601, preserving its UTC normalization and
    millisecond truncation behavior, then returned as UTC-aware datetimes.
    """

    if not value:
        return None
    try:
        canonical = to_utc_iso8601(value)
    except TimestampValidationError:
        return None
    return datetime.fromisoformat(canonical.replace("Z", "+00:00"))
