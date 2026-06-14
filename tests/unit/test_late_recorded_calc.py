"""Unit tests for `_late_recorded_calc` corner cases (trade-trace-nyix).

`_late_recorded_calc` is the pure helper behind the dogfood-protocol
§2.2/§2.3 late-recorded lag (`_scoring.py`). It is exercised indirectly
through the auto-score lifecycle, but its own edge cases — `resolution_at`
None, the `>=` boundary, the resolution-vs-outcome max-delta selection, and
malformed timestamps (which must be swallowed, not raised) — had no direct
unit coverage. This file pins them.
"""

from __future__ import annotations

from trade_trace.tools.ledger._scoring import _late_recorded_calc


def test_outcome_after_forecast_not_late():
    """Forecast strictly before the outcome row and no resolution_at →
    not late, no lag."""

    late, late_by = _late_recorded_calc(
        forecast_created_at="2026-06-30T00:00:00Z",
        outcome_created_at="2026-06-30T00:00:05Z",
        resolution_at=None,
    )
    assert late is False
    assert late_by is None


def test_forecast_after_outcome_is_late_with_lag():
    """Forecast created after the outcome → late, lag = the over-by delta
    in whole seconds."""

    late, late_by = _late_recorded_calc(
        forecast_created_at="2026-06-30T00:00:01Z",
        outcome_created_at="2026-06-30T00:00:00Z",
        resolution_at=None,
    )
    assert late is True
    assert late_by == 1


def test_equal_timestamps_late_boundary_zero_lag():
    """The boundary is `>=`: a forecast created at the SAME instant as the
    outcome is late, but with a zero-second lag (max(0, ...) collapses)."""

    late, late_by = _late_recorded_calc(
        forecast_created_at="2026-06-30T00:00:00Z",
        outcome_created_at="2026-06-30T00:00:00Z",
        resolution_at=None,
    )
    assert late is True
    assert late_by == 0


def test_resolution_at_none_uses_outcome_path_only():
    """resolution_at=None must not raise and only the outcome comparison
    governs lateness."""

    late, late_by = _late_recorded_calc(
        forecast_created_at="2026-06-29T23:59:59Z",
        outcome_created_at="2026-06-30T00:00:00Z",
        resolution_at=None,
    )
    assert late is False
    assert late_by is None


def test_after_resolution_but_before_outcome_is_late():
    """Forecast created before the outcome row but AFTER its own
    resolution_at → late via the resolution branch, lag = resolution
    over-by delta."""

    late, late_by = _late_recorded_calc(
        forecast_created_at="2026-06-30T00:00:00Z",
        outcome_created_at="2026-06-30T01:00:00Z",
        resolution_at="2026-06-29T00:00:00Z",
    )
    assert late is True
    # 24h after resolution_at, even though it predates the outcome row.
    assert late_by == 86400


def test_lag_is_max_of_outcome_and_resolution_deltas():
    """When both the outcome and resolution deltas apply, the lag is the
    LARGER of the two (dogfood-protocol §2.2)."""

    # Forecast is 10s after the outcome row, but 100s after resolution_at.
    late, late_by = _late_recorded_calc(
        forecast_created_at="2026-06-30T00:01:40Z",
        outcome_created_at="2026-06-30T00:01:30Z",  # +10s
        resolution_at="2026-06-30T00:00:00Z",       # +100s
    )
    assert late is True
    assert late_by == 100


def test_malformed_forecast_timestamp_swallowed():
    """A malformed forecast timestamp must be caught and reported as
    not-late rather than propagating a ValueError into the scorer."""

    late, late_by = _late_recorded_calc(
        forecast_created_at="not-a-timestamp",
        outcome_created_at="2026-06-30T00:00:00Z",
        resolution_at=None,
    )
    assert late is False
    assert late_by is None


def test_malformed_outcome_timestamp_swallowed():
    late, late_by = _late_recorded_calc(
        forecast_created_at="2026-06-30T00:00:00Z",
        outcome_created_at="garbage",
        resolution_at=None,
    )
    assert late is False
    assert late_by is None


def test_malformed_resolution_timestamp_swallowed():
    """A malformed resolution_at must not crash the calc; the whole
    computation falls back to (False, None)."""

    late, late_by = _late_recorded_calc(
        forecast_created_at="2026-06-30T00:00:01Z",
        outcome_created_at="2026-06-30T00:00:00Z",
        resolution_at="also-garbage",
    )
    assert late is False
    assert late_by is None
