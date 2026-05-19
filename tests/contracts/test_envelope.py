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


def test_meta_hints_propagate_known_and_unknown_keys(tmp_path):
    """Per bead trade-trace-30u: a handler that writes to
    `ctx.meta_hints` lands its keys on the envelope's Meta. Standard
    keys (declared on the Meta model) map to typed fields; custom
    keys propagate through Meta's `extra='allow'` config so a future
    tool/provider can surface metadata without a schema change."""

    from pathlib import Path

    from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
    from trade_trace.core import default_registry, dispatch
    from trade_trace.mcp_server import mcp_call

    registry = default_registry()

    def _custom_handler(args: dict, ctx: ToolContext) -> dict:
        # One known Meta field and one ad-hoc key.
        ctx.meta_hints["bin_policy"] = "test-policy-x"
        ctx.meta_hints["custom_test_key"] = {"k": 1, "v": [2, 3]}
        return {"ok_payload": True}

    # Register on a copy so the global registry isn't mutated.
    registry.register(
        "report.test_meta_hints_30u",
        _custom_handler,
        description="bead trade-trace-30u contract test handler",
    )
    try:
        env = dispatch("report.test_meta_hints_30u", {"home": str(tmp_path)},
                       actor_id="cli:test", request_id="r-30u",
                       registry=registry)
        dumped = env.model_dump(mode="json", exclude_none=True)
    finally:
        # Remove the handler so other tests don't see it.
        registry.by_name.pop("report.test_meta_hints_30u", None)

    assert dumped["ok"] is True
    meta = dumped["meta"]
    # Known key landed on the typed field.
    assert meta["bin_policy"] == "test-policy-x"
    # Custom key propagated through Meta's extra='allow' surface
    # instead of being silently dropped.
    assert meta["custom_test_key"] == {"k": 1, "v": [2, 3]}


def test_meta_extra_allows_custom_keys_at_construction():
    """Direct construction proves the extensibility contract: Meta
    accepts unknown keys without raising (bead trade-trace-30u)."""

    meta = Meta(
        tool="journal.status", actor_id="cli:user", request_id="r",
        custom_provider_metric=42,  # type: ignore[call-arg]
    )
    dumped = meta.model_dump(mode="json", exclude_none=True)
    assert dumped["custom_provider_metric"] == 42


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
