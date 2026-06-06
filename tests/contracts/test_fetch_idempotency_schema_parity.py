"""Schema-vs-runtime parity for the adapter fetch/refresh writes (bead
trade-trace-2cmb).

`market.refresh`, `snapshot.fetch`, and `outcome.fetch` are retryable
writes whose semantic identity is NOT covered by the auto-derivation
registry (`TOOL_PRIMARY_EVENT_TYPE`), so the dispatcher cannot synthesize
an `idempotency_key` for them — a call that omits it is rejected with a
VALIDATION error whose `details.field == "idempotency_key"`.

Previously `snapshot.fetch` advertised `idempotency_key` as an *optional*
runtime-defaulted key ("Runtime-defaulted keys are optional: at,
idempotency_key.") and `outcome.fetch` did not advertise it at all, so a
schema-trusting bot calling with only `market_id` got a confusing
MISSING_IDEMPOTENCY_KEY rejection. `market.refresh` had the same gap (its
auto-derived schema advertised only `market_id`; AX dogfood 2026-06-06).
These tests pin the advertised schema so it agrees with dispatcher
enforcement: `idempotency_key` is REQUIRED.
"""

from __future__ import annotations

from trade_trace.core import default_registry
from trade_trace.events.semantic_keys import TOOL_PRIMARY_EVENT_TYPE
from trade_trace.mcp_server import mcp_call

_FETCH_WRITE_TOOLS = ("market.refresh", "snapshot.fetch", "outcome.fetch")


def _schema_for(tool_name: str) -> dict:
    reg = default_registry()
    schema = reg.get(tool_name).json_schema
    assert schema is not None, f"tool {tool_name} has no json_schema"
    return schema


def test_fetch_tools_are_outside_the_auto_derivation_registry():
    # If these ever gain auto-derivation, the schema may legitimately drop
    # idempotency_key from `required` — so this guard documents the coupling
    # that makes the "required" assertions below correct.
    for tool_name in _FETCH_WRITE_TOOLS:
        assert tool_name not in TOOL_PRIMARY_EVENT_TYPE, (
            f"{tool_name} is now auto-derivable; revisit the required-key "
            "assertions in this module."
        )


def test_fetch_schemas_advertise_idempotency_key_as_required():
    for tool_name in _FETCH_WRITE_TOOLS:
        schema = _schema_for(tool_name)
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        assert "idempotency_key" in properties, (
            f"{tool_name} runtime requires idempotency_key; advertise it."
        )
        assert "idempotency_key" in required, (
            f"{tool_name} dispatcher rejects calls without idempotency_key "
            "(no auto-derivation); the schema must mark it required so the "
            "advertised contract matches enforcement (bead trade-trace-2cmb)."
        )

        # The schema description must NOT claim idempotency_key is an
        # optional runtime-defaulted key — that was the original lie.
        description = schema.get("description", "")
        marker = "Runtime-defaulted keys are optional:"
        if marker in description:
            optional_clause = description.split(marker, 1)[1]
            assert "idempotency_key" not in optional_clause, (
                f"{tool_name} still advertises idempotency_key as a runtime-"
                "defaulted optional key in its description."
            )


def test_snapshot_fetch_keeps_at_optional():
    # `at` genuinely defaults to "now" in the handler, so it must stay
    # optional even as idempotency_key becomes required.
    schema = _schema_for("snapshot.fetch")
    assert "at" in schema.get("properties", {})
    assert "at" not in schema.get("required", [])


def test_fetch_dispatch_rejects_missing_idempotency_key_matching_schema(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    bind = mcp_call(
        "market.bind",
        {
            "home": home,
            "source": "polymarket",
            "external_id": "pm-2cmb",
            "state": "open",
            "mechanism": "clob",
            "bound_via": "manual",
        },
    )
    assert bind.ok, bind
    market_id = bind.data["id"]

    for tool_name in _FETCH_WRITE_TOOLS:
        env = mcp_call(tool_name, {"home": home, "market_id": market_id})
        assert not env.ok, (
            f"{tool_name} dispatched with only market_id should be rejected; "
            "the schema now advertises idempotency_key as required."
        )
        payload = env.model_dump(mode="json", exclude_none=True)
        assert payload["error"]["code"] == "VALIDATION_ERROR", payload
        assert payload["error"].get("details", {}).get("field") == "idempotency_key", payload
