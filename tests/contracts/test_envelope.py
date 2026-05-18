"""Envelope shape per docs/architecture/contracts.md §3-§4."""

from __future__ import annotations

from trade_trace.contracts.envelope import ErrorBody, ErrorEnvelope, Meta, SuccessEnvelope
from trade_trace.contracts.errors import ErrorCode


def _meta() -> Meta:
    return Meta(tool="journal.status", actor_id="cli:user", request_id="req-1")


def test_success_envelope_round_trips():
    env = SuccessEnvelope(data={"package_version": "0.0.1"}, meta=_meta())
    dumped = env.model_dump(mode="json", exclude_none=True)
    assert dumped["ok"] is True
    assert dumped["data"] == {"package_version": "0.0.1"}
    assert dumped["meta"]["tool"] == "journal.status"
    assert dumped["meta"]["contract_version"] == "1.0"
    assert "event_id" not in dumped["meta"]


def test_error_envelope_shape():
    env = ErrorEnvelope(
        error=ErrorBody(
            code=ErrorCode.VALIDATION_ERROR,
            message="quantity is forbidden for type=skip",
            details={"field": "quantity"},
        ),
        meta=_meta(),
    )
    dumped = env.model_dump(mode="json", exclude_none=True)
    assert dumped["ok"] is False
    assert dumped["error"]["code"] == "VALIDATION_ERROR"
    assert dumped["error"]["details"] == {"field": "quantity"}


def test_error_codes_match_contract_list():
    expected = {
        "VALIDATION_ERROR",
        "NOT_FOUND",
        "IDEMPOTENCY_CONFLICT",
        "UNSUPPORTED_CAPABILITY",
        "STORAGE_ERROR",
        "SCORING_UNSUPPORTED",
        "SCORING_NOT_READY",
        "INVARIANT_VIOLATION",
        "MARKET_NOT_RESOLVED",
        "MARKET_AMBIGUOUS",
    }
    assert {code.value for code in ErrorCode} == expected
