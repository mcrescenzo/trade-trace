import pytest

from trade_trace.adapters.polymarket.retry import RETRY_MAX_SECONDS, retry_after_delay
from trade_trace.tools.adapter_polymarket import _snapshot_from_raw


def test_retry_after_delay_clamps_large_retry_after_to_max() -> None:
    assert retry_after_delay("120", 4.0) == float(RETRY_MAX_SECONDS)


def test_retry_after_delay_preserves_no_invalid_and_reasonable_values() -> None:
    assert retry_after_delay(None, 4.0) == 4.0
    assert retry_after_delay("not-a-number", 4.0) == 4.0
    assert retry_after_delay("10", 4.0) == 10.0
    assert retry_after_delay("2", 4.0) == 4.0


def test_snapshot_preserves_zero_implied_probability() -> None:
    """A legitimate impliedProbability=0.0 (resolved-NO / dead YES contract)
    must be preserved, not silently replaced by the book mid (trade-trace-ph4n).
    With bestBid=0.00/bestAsk=0.02 the mid is 0.01; the old `... or mid` chain
    overwrote the real 0.0 with 0.01."""
    snap = _snapshot_from_raw({"bestBid": "0.00", "bestAsk": "0.02", "impliedProbability": 0.0})
    assert snap["mid"] == 0.01
    assert snap["implied_probability"] == 0.0


def test_snapshot_still_falls_back_to_mid_when_implied_probability_absent() -> None:
    """When impliedProbability is genuinely absent, fall back to the mid so the
    sentinel guard does not regress the existing default (trade-trace-ph4n)."""
    snap = _snapshot_from_raw({"bestBid": "0.40", "bestAsk": "0.44"})
    assert snap["mid"] == pytest.approx(0.42)
    assert snap["implied_probability"] == pytest.approx(0.42)


def test_snapshot_preserves_zero_price() -> None:
    """A legitimate price=0.0 must not be skipped past to a later, non-zero
    field in the price/lastTradePrice/last/mid chain (trade-trace-ph4n). The
    old `raw.get("price") or raw.get("lastTradePrice") or ...` chain returned
    0.05 (lastTradePrice) because 0.0 is falsy."""
    snap = _snapshot_from_raw({"price": 0.0, "lastTradePrice": "0.05"})
    assert snap["price"] == 0.0
    assert snap["mid"] == 0.0
    assert snap["implied_probability"] == 0.0
