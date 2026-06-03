from __future__ import annotations

from trade_trace.contracts.envelope import ErrorEnvelope, SuccessEnvelope
from trade_trace.mcp_server import mcp_call, mcp_tool_specs


def _bind_args(home: str) -> dict[str, object]:
    return {
        "home": home,
        "source": "polymarket",
        "external_id": "market-bind-idempotency",
        "title": "Will the local-only market bind test pass?",
        "question": "Will the local-only market bind test pass?",
        "state": "open",
        "mechanism": "clob",
        "bound_via": "manual",
        "idempotency_key": "00000000-0000-4000-8000-000000000101",
    }


def test_market_bind_is_public_mcp_catalog_tool_and_local_only(tmp_path):
    specs = {spec["name"]: spec for spec in mcp_tool_specs()}
    assert "market.bind" in specs
    assert "market.scan.dry_run" not in specs
    assert "market.scan.promote" not in specs
    rendered = (specs["market.bind"]["description"] + " " + str(specs["market.bind"]["metadata"])).lower()
    assert "manual/local" in rendered
    assert "no network" in rendered
    assert "broker" in rendered and "wallet" in rendered and "scheduler" in rendered
    schema_props = specs["market.bind"]["input_schema"]["properties"]
    for key in ("gamma_event_id", "outcome_ids_by_label", "resolution_rule", "tick_size", "fee_rate_bps", "tradable", "accepting_orders"):
        assert key in schema_props


def test_market_bind_missing_enum_field_error_lists_allowed_values(tmp_path):
    # A missing required-enum field (source/state/mechanism) must surface the
    # allowed values, not just a bare "<field> is required" — otherwise a caller
    # has no way to discover the valid set. Regression for AX dogfood friction.
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok

    args = _bind_args(home)
    del args["source"]
    result = mcp_call("market.bind", args, actor_id="agent:test")
    assert isinstance(result, ErrorEnvelope), result
    assert result.error.code.value == "VALIDATION_ERROR"
    assert result.error.details["field"] == "source"
    assert result.error.details["allowed"] == ["kalshi", "manifold", "manual", "polymarket", "predictit"]
    assert "polymarket" in result.error.message


def test_market_bind_idempotency_replay_sets_envelope_meta(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok

    first = mcp_call("market.bind", _bind_args(home), actor_id="agent:test")
    assert isinstance(first, SuccessEnvelope), first
    assert first.meta.event_id
    assert first.meta.idempotent_replay is not True

    second = mcp_call("market.bind", _bind_args(home), actor_id="agent:test")
    assert isinstance(second, SuccessEnvelope), second
    assert second.data["id"] == first.data["id"]
    assert second.meta.event_id == first.meta.event_id
    assert second.meta.idempotent_replay is True
    assert second.data["idempotent_replay"] is True
    assert list(second.data) == [
        "id",
        "source",
        "external_id",
        "title",
        "question",
        "url",
        "state",
        "mechanism",
        "resolution_source",
        "ambiguity_kind",
        "bound_via",
        "opened_at",
        "close_at",
        "closed_for_trading_at",
        "resolving_at",
        "resolved_at",
        "voided_at",
        "ambiguous_at",
        "venue_metadata_json",
        "metadata_json",
        "created_at",
        "actor_id",
        "market_id",
        "instrument_id",
        "venue_id",
        "idempotent_replay",
    ]


def test_market_bind_duplicate_natural_key_returns_existing_without_adapter(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok
    first_args = _bind_args(home)
    first_args["idempotency_key"] = "00000000-0000-4000-8000-000000000102"
    first = mcp_call("market.bind", first_args, actor_id="agent:test")
    assert isinstance(first, SuccessEnvelope), first

    duplicate_args = _bind_args(home)
    duplicate_args["idempotency_key"] = "00000000-0000-4000-8000-000000000103"
    duplicate = mcp_call("market.bind", duplicate_args, actor_id="agent:test")
    assert isinstance(duplicate, SuccessEnvelope), duplicate
    assert duplicate.data["id"] == first.data["id"]
    assert duplicate.data["already_bound"] is True
    assert list(duplicate.data) == [
        "id",
        "source",
        "external_id",
        "title",
        "question",
        "url",
        "state",
        "mechanism",
        "resolution_source",
        "ambiguity_kind",
        "bound_via",
        "opened_at",
        "close_at",
        "closed_for_trading_at",
        "resolving_at",
        "resolved_at",
        "voided_at",
        "ambiguous_at",
        "venue_metadata_json",
        "metadata_json",
        "created_at",
        "actor_id",
        "already_bound",
        "market_id",
        "instrument_id",
        "venue_id",
    ]


def _forecast_args(home: str, market_id: str, *, idem: str) -> dict[str, object]:
    return {
        "home": home,
        "market_id": market_id,
        "rationale_body": "Folded public forecast thesis.",
        "kind": "binary",
        "yes_label": "YES",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.6},
            {"outcome_label": "NO", "probability": 0.4},
        ],
        "idempotency_key": idem,
    }


def test_market_bind_to_forecast_add_folded_path_idempotent_and_validates_mismatch(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok
    market = mcp_call("market.bind", _bind_args(home), actor_id="agent:test")
    assert isinstance(market, SuccessEnvelope), market

    first = mcp_call(
        "forecast.add",
        _forecast_args(home, market.data["market_id"], idem="00000000-0000-4000-8000-000000000201"),
        actor_id="agent:test",
    )
    assert isinstance(first, SuccessEnvelope), first
    assert first.data["thesis_id"]

    replay = mcp_call(
        "forecast.add",
        _forecast_args(home, market.data["market_id"], idem="00000000-0000-4000-8000-000000000201"),
        actor_id="agent:test",
    )
    assert isinstance(replay, SuccessEnvelope), replay
    assert replay.data["id"] == first.data["id"]
    assert replay.data["thesis_id"] == first.data["thesis_id"]
    assert replay.meta.idempotent_replay is True

    mismatch_args = _forecast_args(home, market.data["market_id"], idem="00000000-0000-4000-8000-000000000202")
    mismatch_args["instrument_id"] = "ins_different"
    mismatch = mcp_call("forecast.add", mismatch_args, actor_id="agent:test")
    assert isinstance(mismatch, ErrorEnvelope), mismatch
    assert mismatch.error.code.value == "VALIDATION_ERROR"


def test_forecast_add_folded_path_missing_body_and_missing_market_are_clean_errors(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok

    missing_body = _forecast_args(home, "mkt_missing", idem="00000000-0000-4000-8000-000000000203")
    del missing_body["rationale_body"]
    err = mcp_call("forecast.add", missing_body, actor_id="agent:test")
    assert isinstance(err, ErrorEnvelope), err
    assert err.error.code.value == "VALIDATION_ERROR"

    missing_market = _forecast_args(home, "mkt_missing", idem="00000000-0000-4000-8000-000000000204")
    err = mcp_call("forecast.add", missing_market, actor_id="agent:test")
    assert isinstance(err, ErrorEnvelope), err
    assert err.error.code.value == "NOT_FOUND"
