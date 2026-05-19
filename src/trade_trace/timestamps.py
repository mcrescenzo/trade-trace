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

from datetime import UTC, datetime


class TimestampValidationError(ValueError):
    """Raised when a timestamp input cannot be normalized to UTC ISO 8601."""


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
