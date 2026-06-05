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

import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

from trade_trace.cli import main as cli_main
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call

ROOT = Path(__file__).resolve().parents[2]


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
    for tool_name in ("decision.record_adherence", "playbook.record_adherence"):
        schema = _schema_for(tool_name)

        required = schema.get("required", [])
        properties = schema.get("properties", {})

        # Stale aliases must not appear; runtime takes `rule_node_id` and
        # `status`, not `rule_id` / `outcome`.
        for stale in ("rule_id", "outcome"):
            assert stale not in required, (
                f"{stale!r} is a stale alias not consumed by "
                f"{tool_name}; do not require it."
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
                f"{tool_name}; advertised schema must list it"
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


def test_report_opportunity_minimum_coverage_schema_matches_runtime_enum():
    schema = _schema_for("report.opportunity")
    enum = schema["properties"]["minimum_coverage"].get("enum")

    assert enum == ["sparse", "partial", "complete"], (
        "report.opportunity runtime accepts sparse/partial/complete; "
        "the advertised schema must expose exactly those values in order."
    )


def test_report_opportunity_advertised_minimum_coverage_values_cli_mcp_parity(tmp_path):
    schema = _schema_for("report.opportunity")
    advertised_values = schema["properties"]["minimum_coverage"]["enum"]
    home = tmp_path / "home"
    init = mcp_call("journal.init", {"home": str(home)}, actor_id="agent:default")
    assert init.ok, init

    for minimum_coverage in advertised_values:
        mcp_env = mcp_call(
            "report.opportunity",
            {"home": str(home), "minimum_coverage": minimum_coverage},
            actor_id="agent:default",
            request_id=f"req-mcp-{minimum_coverage}",
        ).model_dump(mode="json", exclude_none=True)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_main(
                [
                    "--actor-id",
                    "agent:default",
                    "--request-id",
                    f"req-cli-{minimum_coverage}",
                    "report",
                    "opportunity",
                    "--home",
                    str(home),
                    "--minimum-coverage",
                    minimum_coverage,
                ]
            )
        cli_env = json.loads(buf.getvalue().strip().splitlines()[-1])

        assert mcp_env["ok"], mcp_env
        assert rc == 0, cli_env
        assert cli_env["ok"], cli_env
        assert cli_env["meta"]["tool"] == mcp_env["meta"]["tool"] == "report.opportunity"
        assert cli_env["data"] == mcp_env["data"]


def test_instrument_add_schema_advertises_optional_audit_fields():
    schema = _schema_for("instrument.add")
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    for key in (
        "external_id",
        "symbol",
        "currency_or_collateral",
        "expiration_or_resolution_at",
        "resolution_criteria_text",
        "contract_multiplier",
        "metadata_json",
    ):
        assert key in properties
        assert key not in required


def test_decision_add_schema_advertises_optional_snapshot_id():
    schema = _schema_for("decision.add")
    assert "snapshot_id" in schema.get("properties", {})
    assert "snapshot_id" not in schema.get("required", [])


def test_snapshot_add_schema_advertises_optional_market_state_fields():
    schema = _schema_for("snapshot.add")
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    assert "instrument_id" in required
    assert "captured_at" in required
    for key in (
        "price",
        "source",
        "source_url",
        "bid",
        "ask",
        "mid",
        "spread",
        "volume",
        "open_interest",
        "implied_probability",
        "liquidity_depth_json",
        "metadata_json",
    ):
        assert key in properties
        assert key not in required


# trade-trace-l6ot: new-surface schema-runtime parity blocks. The
# handlers for strategy/report tools have runtime defaults and required
# inputs; the advertised JSON schemas must match so schema-validating
# clients can call the tools without surprises.


def test_strategy_create_schema_requires_name_and_slug_only():
    schema = _schema_for("strategy.create")
    required = schema.get("required", [])

    # Runtime mandates: name, slug, idempotency_key. Drift would silently
    # break schema-validating MCP clients.
    for runtime_required in ("name", "slug", "idempotency_key"):
        assert runtime_required in required, (
            f"runtime requires {runtime_required!r} for strategy.create; "
            "schema must list it (check tools/_examples.py minimal payload)."
        )


def test_strategy_show_schema_does_not_falsely_require_either_identifier():
    schema = _schema_for("strategy.show")
    required = schema.get("required", [])

    # strategy.show accepts either strategy_id OR slug; neither must be
    # advertised as schema-level required, otherwise schema-validating
    # clients are blocked from calling with just the alternative.
    for ident in ("strategy_id", "slug"):
        assert ident not in required, (
            f"{ident!r} must not be marked required on strategy.show; the "
            "handler accepts the alternative identifier."
        )


def test_strategy_update_schema_keeps_name_and_slug_off_the_write_surface():
    schema = _schema_for("strategy.update")
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    # name and slug are immutable post-create; they must not be writable
    # via strategy.update.
    for immutable in ("name", "slug"):
        assert immutable not in properties, (
            f"{immutable!r} is immutable on strategy.update; remove it from "
            "example_minimal so the derived schema stops advertising it."
        )
    for runtime_required in ("strategy_id", "idempotency_key"):
        assert runtime_required in required, (
            f"runtime requires {runtime_required!r} for strategy.update"
        )


def test_report_bootstrap_schema_keeps_filter_optional():
    """report.bootstrap accepts an empty {} payload; no runtime arg is
    required. Schema must not regress to requiring filter or as_of."""
    schema = _schema_for("report.bootstrap")
    required = schema.get("required", [])
    for defaulted in ("filter", "budgets", "as_of"):
        assert defaulted not in required, (
            f"{defaulted!r} has a runtime default in report.bootstrap; "
            "schema must not mark it required."
        )


def test_report_forecast_diagnostics_schema_keeps_filter_optional():
    schema = _schema_for("report.forecast_diagnostics")
    required = schema.get("required", [])
    for defaulted in ("filter", "min_sample"):
        assert defaulted not in required, (
            f"{defaulted!r} has a runtime default in report.forecast_diagnostics"
        )


def test_report_strategy_health_schema_keeps_status_and_min_sample_optional():
    schema = _schema_for("report.strategy_health")
    required = schema.get("required", [])
    for defaulted in ("filter", "status", "as_of", "min_sample"):
        assert defaulted not in required, (
            f"{defaulted!r} has a runtime default in report.strategy_health"
        )


def test_snapshot_add_cli_help_lists_optional_market_state_flags():
    proc = subprocess.run(
        [sys.executable, "-m", "trade_trace.cli", "snapshot", "add", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    help_text = proc.stdout

    for flag in (
        "--source",
        "--source-url",
        "--bid",
        "--ask",
        "--mid",
        "--spread",
        "--volume",
        "--open-interest",
        "--implied-probability",
        "--liquidity-depth-json",
        "--metadata-json",
    ):
        assert flag in help_text


def test_agent_critical_read_report_playbook_tools_advertise_json_schemas():
    for tool_name in (
        "memory.recall",
        "report.watchlist",
        "report.lifecycle",
        "report.work_queue",
        "agent.next_actions",
        "report.source_quality",
        "report.unscored_forecasts",
        "report.coach",
        "playbook.adherence",
    ):
        schema = _schema_for(tool_name)
        assert schema["type"] == "object"
        assert "properties" in schema


def test_memory_recall_schema_matches_runtime_required_query_and_optional_knobs():
    schema = _schema_for("memory.recall")

    assert schema.get("required", []) == ["query"]
    properties = schema.get("properties", {})
    for optional in (
        "context",
        "strategies",
        "k",
        "max_chars",
        "compact",
        "include_body",
        "include_provenance",
        "min_confidence",
        "node_types",
        "mode",
        "as_of",
    ):
        assert optional in properties
        assert optional not in schema.get("required", [])


def test_report_schemas_advertise_defaulted_args_as_optional():
    expected_optional = {
        "report.watchlist": ("filter", "mode", "stale_threshold_days"),
        "report.lifecycle": ("filter", "states", "status", "as_of", "stale_threshold_days"),
        "report.work_queue": ("filter", "as_of", "stale_threshold_days", "kinds", "kind"),
        "agent.next_actions": ("filter", "as_of", "stale_threshold_days", "kinds", "kind"),
        "report.open_positions": ("limit", "cursor", "kind", "instrument_id", "strategy_id"),
        "report.current_exposure": ("recent_limit", "include_watchlist", "include_anomalies", "kind", "instrument_id", "strategy_id"),
        "report.source_quality": ("stale_threshold_days",),
        "report.unscored_forecasts": ("filter",),
        "report.coach": ("filter", "stale_threshold_days"),
    }

    for tool_name, optional_keys in expected_optional.items():
        schema = _schema_for(tool_name)
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        for key in optional_keys:
            assert key in properties
            assert key not in required


def test_current_exposure_and_pnl_schema_discoverability_for_open_trades():
    reg = default_registry()

    current = reg.get("report.current_exposure")
    assert current.json_schema is not None
    current_text = " ".join(
        [
            current.description,
            current.json_schema.get("description", ""),
            current.metadata().get("usage_summary", ""),
            " ".join(current.metadata().get("next_actions", [])),
        ]
    ).lower()
    for phrase in (
        "recommended trader-agent entry point",
        "open trades/current exposure",
        "open_positions",
        "watchlist",
        "recent_trade_activity",
        "projection_anomalies",
        "not canonical exposure",
    ):
        assert phrase in current_text

    pnl = reg.get("report.pnl")
    assert pnl.json_schema is not None
    pnl_text = " ".join(
        [
            pnl.description,
            pnl.json_schema.get("description", ""),
            pnl.metadata().get("usage_summary", ""),
            " ".join(pnl.metadata().get("next_actions", [])),
            " ".join(pnl.metadata().get("examples", [])),
        ]
    ).lower()
    for phrase in (
        "lower-level p&l report",
        "for open trades/current exposure",
        "start with report.current_exposure",
        "report.open_positions",
        "summary.metrics.open_position_count > 0",
        "does not execute trades",
        "or prove broker portfolio truth",
    ):
        assert phrase in pnl_text


def test_playbook_adherence_schema_requires_playbook_id_only():
    schema = _schema_for("playbook.adherence")

    assert schema.get("required", []) == ["playbook_id"]
    properties = schema.get("properties", {})
    assert "playbook_id" in properties
    assert "strategy_id" in properties
    assert "strategy_id" not in schema.get("required", [])



def test_all_report_tools_advertise_argument_schema_or_explicit_no_arg_schema():
    reg = default_registry()
    report_tools = [name for name in reg.names() if name.startswith("report.")]

    assert report_tools
    for tool_name in report_tools:
        schema = _schema_for(tool_name)
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema


def test_report_playbook_adherence_schema_advertises_all_runtime_scopes():
    schema = _schema_for("report.playbook_adherence")
    properties = schema.get("properties", {})

    for key in ("filter", "playbook_id", "strategy_id"):
        assert key in properties
        assert key not in schema.get("required", [])


def test_memory_reflect_schema_advertises_canonical_and_sugar_shapes():
    schema = _schema_for("memory.reflect")
    properties = schema.get("properties", {})

    for key in (
        "target_kind",
        "target_id",
        "body",
        "target",
        "insight",
        "strength_tags",
        "weakness_tags",
        "meta_json",
    ):
        assert key in properties
    assert "derived_from" not in properties
    assert "supports" not in properties


def test_memory_link_schema_advertises_endpoint_and_edge_enums():
    """memory.link validates source_kind/target_kind against
    VALID_MEMORY_ENDPOINTS and edge_type against EDGE_TYPES at runtime, but
    the advertised schema auto-derived from example_minimal exposed them as
    bare strings — a bot reading the schema could not discover the allowed
    values without triggering a VALIDATION_ERROR (AX-051). The advertised
    enums must match the runtime allowlists exactly."""
    from trade_trace.tools.memory import EDGE_TYPES, VALID_MEMORY_ENDPOINTS

    schema = _schema_for("memory.link")
    properties = schema.get("properties", {})

    for key in (
        "source_kind",
        "source_id",
        "target_kind",
        "target_id",
        "edge_type",
        "idempotency_key",
    ):
        assert key in properties, f"memory.link schema omits {key}"
        assert key in schema.get("required", []), f"memory.link {key} not required"

    assert properties["source_kind"]["enum"] == list(VALID_MEMORY_ENDPOINTS)
    assert properties["target_kind"]["enum"] == list(VALID_MEMORY_ENDPOINTS)
    assert properties["edge_type"]["enum"] == list(EDGE_TYPES)


def test_playbook_read_and_write_schemas_advertise_runtime_optional_fields():
    assert "limit" in _schema_for("playbook.list")["properties"]
    assert _schema_for("playbook.show")["required"] == ["playbook_id"]
    assert _schema_for("playbook.list_versions")["required"] == ["playbook_id"]

    propose = _schema_for("playbook.propose_version")
    for key in ("description", "metadata_json", "parent_version_id"):
        assert key in propose["properties"]
        assert key not in propose["required"]

    adherence = _schema_for("decision.record_adherence")
    assert adherence["properties"]["status"]["enum"] == [
        "considered",
        "followed",
        "overridden",
        "not_applicable",
    ]
    for key in ("reason", "metadata_json"):
        assert key in adherence["properties"]
        assert key not in adherence["required"]


def test_snapshot_and_source_schemas_advertise_persisted_agent_run_fields():
    for tool_name in ("snapshot.add", "source.add"):
        schema = _schema_for(tool_name)
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for key in ("agent_id", "model_id", "environment", "run_id"):
            assert key in properties
            assert key not in required


def test_strategy_list_accepts_documented_all_alias_at_runtime(tmp_path):
    from trade_trace.mcp_server import mcp_call

    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}).ok
    assert mcp_call(
        "strategy.create",
        {
            "home": home,
            "name": "Active strategy",
            "slug": "active-strategy",
            "idempotency_key": "00000000-0000-4000-8000-active-strategy",
        },
    ).ok
    archived = mcp_call(
        "strategy.create",
        {
            "home": home,
            "name": "Archived strategy",
            "slug": "archived-strategy",
            "idempotency_key": "00000000-0000-4000-8000-archived-strategy",
        },
    )
    assert archived.ok
    archived_id = archived.model_dump(mode="json", exclude_none=True)["data"]["id"]
    assert mcp_call(
        "strategy.update",
        {
            "home": home,
            "strategy_id": archived_id,
            "status": "archived",
            "idempotency_key": "00000000-0000-4000-8000-archive-strategy",
        },
    ).ok

    all_env = mcp_call("strategy.list", {"home": home, "status": "all"})
    both_env = mcp_call("strategy.list", {"home": home, "status": "both"})
    assert all_env.ok, all_env
    assert both_env.ok, both_env
    all_slugs = {item["slug"] for item in all_env.model_dump(mode="json", exclude_none=True)["data"]["items"]}
    both_slugs = {item["slug"] for item in both_env.model_dump(mode="json", exclude_none=True)["data"]["items"]}
    assert {"active-strategy", "archived-strategy"}.issubset(all_slugs)
    assert all_slugs == both_slugs
