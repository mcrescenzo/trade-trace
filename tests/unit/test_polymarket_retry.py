from trade_trace.adapters.polymarket.retry import RETRY_MAX_SECONDS, retry_after_delay


def test_retry_after_delay_clamps_large_retry_after_to_max() -> None:
    assert retry_after_delay("120", 4.0) == float(RETRY_MAX_SECONDS)


def test_retry_after_delay_preserves_no_invalid_and_reasonable_values() -> None:
    assert retry_after_delay(None, 4.0) == 4.0
    assert retry_after_delay("not-a-number", 4.0) == 4.0
    assert retry_after_delay("10", 4.0) == 10.0
    assert retry_after_delay("2", 4.0) == 4.0
