"""UTC timestamp normalization per docs/architecture/operability.md §2.1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from trade_trace.clock import FixedClock, SystemClock
from trade_trace.timestamps import (
    TimestampValidationError,
    is_canonical_utc_iso8601,
    to_utc_iso8601,
)


def test_normalize_utc_string_preserves_milliseconds():
    assert to_utc_iso8601("2026-05-18T14:32:11.123Z") == "2026-05-18T14:32:11.123Z"


def test_normalize_non_utc_offset_converts_to_utc():
    # `+05:00` at 19:32 local → 14:32 UTC
    assert to_utc_iso8601("2026-05-18T19:32:11.123+05:00") == "2026-05-18T14:32:11.123Z"


def test_naive_timestamp_rejected():
    with pytest.raises(TimestampValidationError):
        to_utc_iso8601("2026-05-18T14:32:11.123")


def test_sub_millisecond_truncated_not_rounded():
    # Truncation is the locked decision; .123999 must become .123, not .124
    assert to_utc_iso8601("2026-05-18T14:32:11.123999Z") == "2026-05-18T14:32:11.123Z"
    # And the edge case at the .999999 boundary
    assert to_utc_iso8601("2026-05-18T14:32:11.999999Z") == "2026-05-18T14:32:11.999Z"


def test_datetime_input_normalized():
    dt = datetime(2026, 5, 18, 14, 32, 11, 123999, tzinfo=timezone(timedelta(hours=2)))
    assert to_utc_iso8601(dt) == "2026-05-18T12:32:11.123Z"


def test_invalid_string_raises():
    with pytest.raises(TimestampValidationError):
        to_utc_iso8601("not a timestamp")


def test_canonical_storage_predicate_matches_helper_output():
    assert is_canonical_utc_iso8601(to_utc_iso8601("2026-05-18T14:32:11.123999Z"))
    assert not is_canonical_utc_iso8601("2026-05-18T14:32:11Z")
    assert not is_canonical_utc_iso8601("2026-05-18T14:32:11.123+00:00")
    assert not is_canonical_utc_iso8601("2026-05-18T14:32:11.123")


def test_system_clock_returns_aware_datetime():
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_fixed_clock_requires_aware_datetime():
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 5, 18, 14, 0, 0))


def test_fixed_clock_advance():
    clock = FixedClock(datetime(2026, 5, 18, 14, 0, 0, tzinfo=UTC))
    initial = clock.now()
    clock.advance(seconds=60)
    assert (clock.now() - initial).total_seconds() == 60
