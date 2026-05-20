"""Parity checks between advertised `tool.schema` / MCP `input_schema`
and the actual runtime handler requirements per beads
trade-trace-24ie (playbook.propose_version, decision.record_adherence)
and trade-trace-4zbk (report.opportunity defaulted args).

These tests guard against drift where an `example_minimal` payload
still includes stale or now-defaulted keys, causing schema-validating
MCP clients to be forced to send dummy/alias fields that the handler
does not require — or worse, to be blocked from calling the tool with
an empty payload when the runtime supports defaults.
"""

from __future__ import annotations

from trade_trace.core import default_registry


def _schema_for(tool_name: str) -> dict:
    reg = default_registry()
    schema = reg.get(tool_name).json_schema
    assert schema is not None, f"tool {tool_name} has no json_schema"
    return schema


def test_playbook_propose_version_schema_does_not_require_stale_rules_json():
    schema = _schema_for("playbook.propose_version")

    required = schema.get("required", [])
    properties = schema.get("properties", {})

    # Runtime does not read `rules_json` — it must not appear as required
    # (or as an advertised property), otherwise schema-validating MCP
    # clients are forced to fabricate a value that the handler ignores.
    assert "rules_json" not in required, (
        "rules_json is not consumed by playbook.propose_version's runtime "
        "handler; do not advertise it as required."
    )
    assert "rules_json" not in properties, (
        "rules_json is stale; remove it from example_minimal so the "
        "derived schema stops advertising it."
    )

    # The handler reads playbook_id, provenance_reflection_node_id, and
    # idempotency_key (description / metadata / parent_version_id are
    # optional). Pin the runtime-required ones.
    for runtime_required in (
        "playbook_id",
        "provenance_reflection_node_id",
        "idempotency_key",
    ):
        assert runtime_required in required, (
            f"runtime requires {runtime_required!r} for "
            "playbook.propose_version; advertised schema must list it"
        )


def test_decision_record_adherence_schema_uses_runtime_field_names():
    schema = _schema_for("decision.record_adherence")

    required = schema.get("required", [])
    properties = schema.get("properties", {})

    # Stale aliases must not appear; runtime takes `rule_node_id` and
    # `status`, not `rule_id` / `outcome`.
    for stale in ("rule_id", "outcome"):
        assert stale not in required, (
            f"{stale!r} is a stale alias not consumed by "
            "decision.record_adherence; do not require it."
        )
        assert stale not in properties, (
            f"{stale!r} is a stale alias; remove from example_minimal so "
            "the derived schema stops advertising it."
        )

    for runtime_required in (
        "decision_id",
        "playbook_version_id",
        "rule_node_id",
        "status",
        "idempotency_key",
    ):
        assert runtime_required in required, (
            f"runtime requires {runtime_required!r} for "
            "decision.record_adherence; advertised schema must list it"
        )


def test_report_opportunity_schema_treats_defaulted_args_as_optional():
    schema = _schema_for("report.opportunity")

    required = schema.get("required", [])
    properties = schema.get("properties", {})

    # All 5 args (filter, minimum_coverage, max_records, include_labels,
    # min_sample) have runtime defaults; none should be advertised as
    # required, otherwise schema-validating MCP clients cannot pass `{}`.
    for defaulted in (
        "filter",
        "minimum_coverage",
        "max_records",
        "include_labels",
        "min_sample",
    ):
        assert defaulted not in required, (
            f"{defaulted!r} has a runtime default in report.opportunity; "
            "schema must not mark it required."
        )

    # The optional args should still be discoverable as properties so
    # agents can see what knobs exist.
    for advertised in ("filter", "minimum_coverage", "max_records"):
        assert advertised in properties, (
            f"{advertised!r} is a documented knob; advertise it in "
            "properties even though it's optional."
        )
