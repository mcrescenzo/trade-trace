from __future__ import annotations

from trade_trace.mcp_server import mcp_call, mcp_tool_specs
from trade_trace.contracts.envelope import SuccessEnvelope


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
