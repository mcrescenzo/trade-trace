"""Injectable UTC clock per operability.md §2.2.

The system clock is the source of "now." For test determinism, the clock is
injectable: tests fake `now` to verify time-passing signals (`watch.stale`,
`report.unscored_forecasts`) and bi-temporal validity filters.

`now` is read at most once per tool call and cached for the duration of the
transaction; this ensures a single call's reads of `time_horizon_at <= now`
and `valid_to > now` see the same `now`. (The per-call caching lives in the
core dispatcher; this module supplies the underlying source.)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Anything that returns a tz-aware UTC datetime when called."""

    def now(self) -> datetime: ...


class SystemClock:
    """Wall-clock UTC source. The default for production callers."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Test-friendly clock that returns a fixed datetime."""

    def __init__(self, fixed: datetime) -> None:
        if fixed.tzinfo is None or fixed.tzinfo.utcoffset(fixed) is None:
            raise ValueError("FixedClock requires a tz-aware UTC datetime")
        self._fixed = fixed.astimezone(UTC)

    def now(self) -> datetime:
        return self._fixed

    def advance(self, *, seconds: float = 0, days: float = 0) -> None:
        from datetime import timedelta

        self._fixed = self._fixed + timedelta(seconds=seconds, days=days)


# Process-global `_DEFAULT_CLOCK` / `default_clock()` / `set_default_clock()`
# were removed per bead trade-trace-xeq / DEBT-CRT-001: nothing in the
# runtime referenced them and the deterministic-clock injection point
# the rest of the codebase actually uses is the `CLOCK_OVERRIDE`
# ContextVar in `trade_trace.tools._helpers`. Keeping a second
# process-global injection surface invited per-test bleed and
# disagreed with the per-call ContextVar pattern.
#
# Clock / SystemClock / FixedClock above stay — Clock is the protocol
# consumers type against and FixedClock is used by tests that need a
# stationary instant. Production code passes a Clock explicitly to
# callers that need it; nothing reads from a module-global.
