from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from trade_trace.timestamps import (
    parse_report_timestamp_lenient_naive_as_utc,
    parse_report_timestamp_lenient_preserve_naive_offset,
    parse_report_timestamp_lenient_utc_naive_as_utc,
    parse_report_timestamp_strict_utc_naive_as_utc,
    parse_report_timestamp_utc_or_none,
)

NAIVE_TEXT = "2026-05-18T14:32:11.123456"
Z_TEXT = "2026-05-18T14:32:11.123456Z"
OFFSET_TEXT = "2026-05-18T19:32:11.123456+05:00"
INVALID_TEXT = "not a timestamp"
OFFSET = timezone(timedelta(hours=5))


def test_lenient_preserve_naive_offset_missing_and_invalid_return_none() -> None:
    assert parse_report_timestamp_lenient_preserve_naive_offset(None) is None
    assert parse_report_timestamp_lenient_preserve_naive_offset("") is None
    assert parse_report_timestamp_lenient_preserve_naive_offset(INVALID_TEXT) is None


def test_lenient_preserve_naive_offset_preserves_naive_and_offsets() -> None:
    assert parse_report_timestamp_lenient_preserve_naive_offset(NAIVE_TEXT) == datetime(
        2026, 5, 18, 14, 32, 11, 123456
    )
    assert parse_report_timestamp_lenient_preserve_naive_offset(Z_TEXT) == datetime(
        2026, 5, 18, 14, 32, 11, 123456, tzinfo=UTC
    )
    parsed = parse_report_timestamp_lenient_preserve_naive_offset(OFFSET_TEXT)
    assert parsed == datetime(2026, 5, 18, 19, 32, 11, 123456, tzinfo=OFFSET)
    assert parsed.utcoffset() == timedelta(hours=5)


def test_lenient_naive_as_utc_missing_and_invalid_return_none() -> None:
    assert parse_report_timestamp_lenient_naive_as_utc(None) is None
    assert parse_report_timestamp_lenient_naive_as_utc("") is None
    assert parse_report_timestamp_lenient_naive_as_utc(INVALID_TEXT) is None


def test_lenient_naive_as_utc_attaches_utc_and_preserves_offsets() -> None:
    assert parse_report_timestamp_lenient_naive_as_utc(NAIVE_TEXT) == datetime(
        2026, 5, 18, 14, 32, 11, 123456, tzinfo=UTC
    )
    assert parse_report_timestamp_lenient_naive_as_utc(Z_TEXT) == datetime(
        2026, 5, 18, 14, 32, 11, 123456, tzinfo=UTC
    )
    parsed = parse_report_timestamp_lenient_naive_as_utc(OFFSET_TEXT)
    assert parsed == datetime(2026, 5, 18, 19, 32, 11, 123456, tzinfo=OFFSET)
    assert parsed.utcoffset() == timedelta(hours=5)


def test_lenient_utc_naive_as_utc_missing_and_invalid_return_none() -> None:
    assert parse_report_timestamp_lenient_utc_naive_as_utc(None) is None
    assert parse_report_timestamp_lenient_utc_naive_as_utc("") is None
    assert parse_report_timestamp_lenient_utc_naive_as_utc(INVALID_TEXT) is None


def test_lenient_utc_naive_as_utc_attaches_utc_and_normalizes_offsets() -> None:
    assert parse_report_timestamp_lenient_utc_naive_as_utc(NAIVE_TEXT) == datetime(
        2026, 5, 18, 14, 32, 11, 123456, tzinfo=UTC
    )
    assert parse_report_timestamp_lenient_utc_naive_as_utc(Z_TEXT) == datetime(
        2026, 5, 18, 14, 32, 11, 123456, tzinfo=UTC
    )
    # Unlike the preserve-offset variants, a non-UTC offset is normalized to UTC.
    parsed = parse_report_timestamp_lenient_utc_naive_as_utc(OFFSET_TEXT)
    assert parsed == datetime(2026, 5, 18, 14, 32, 11, 123456, tzinfo=UTC)
    assert parsed.utcoffset() == timedelta(0)


def test_strict_utc_naive_as_utc_missing_and_invalid_raise_value_error() -> None:
    for value in (None, "", INVALID_TEXT):
        with pytest.raises(ValueError):
            parse_report_timestamp_strict_utc_naive_as_utc(value)


def test_strict_utc_naive_as_utc_attaches_or_normalizes_to_utc() -> None:
    assert parse_report_timestamp_strict_utc_naive_as_utc(NAIVE_TEXT) == datetime(
        2026, 5, 18, 14, 32, 11, 123456, tzinfo=UTC
    )
    assert parse_report_timestamp_strict_utc_naive_as_utc(Z_TEXT) == datetime(
        2026, 5, 18, 14, 32, 11, 123456, tzinfo=UTC
    )
    assert parse_report_timestamp_strict_utc_naive_as_utc(OFFSET_TEXT) == datetime(
        2026, 5, 18, 14, 32, 11, 123456, tzinfo=UTC
    )


def test_utc_or_none_missing_invalid_and_naive_return_none() -> None:
    assert parse_report_timestamp_utc_or_none(None) is None
    assert parse_report_timestamp_utc_or_none("") is None
    assert parse_report_timestamp_utc_or_none(INVALID_TEXT) is None
    assert parse_report_timestamp_utc_or_none(NAIVE_TEXT) is None


def test_utc_or_none_uses_canonical_to_utc_iso8601_semantics() -> None:
    assert parse_report_timestamp_utc_or_none(Z_TEXT) == datetime(
        2026, 5, 18, 14, 32, 11, 123000, tzinfo=UTC
    )
    assert parse_report_timestamp_utc_or_none(OFFSET_TEXT) == datetime(
        2026, 5, 18, 14, 32, 11, 123000, tzinfo=UTC
    )
