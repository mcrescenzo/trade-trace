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
        ("config", "updated_at"),
        ("decisions", "created_at"),
        ("decisions", "review_by"),
        ("decision_playbook_rules", "created_at"),
        ("edges", "created_at"),
        ("events", "created_at"),
        ("forecast_scores", "scored_at"),
        ("forecasts", "created_at"),
        ("forecasts", "invalidated_at"),
        ("forecasts", "resolution_at"),
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
        ("outcomes", "created_at"),
        ("outcomes", "resolved_at"),
        ("playbooks", "created_at"),
        ("playbook_versions", "created_at"),
        ("position_events", "created_at"),
        ("positions", "closed_at"),
        ("positions", "opened_at"),
        ("positions", "resolved_at"),
        ("positions", "updated_at"),
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


def to_utc_iso8601(value: str | datetime, *, field: str = "<value>") -> str:
    """Normalize an input to canonical UTC ISO 8601 with millisecond precision.

    Truncates sub-millisecond digits (the locked decision per
    operability.md §2.1). Returns a `Z`-suffixed string.
    """

    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TimestampValidationError(
                f"{field}: not a valid ISO 8601 timestamp ({exc})"
            ) from exc
    elif isinstance(value, datetime):
        dt = value
    else:
        raise TimestampValidationError(
            f"{field}: expected str or datetime, got {type(value).__name__}"
        )

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
