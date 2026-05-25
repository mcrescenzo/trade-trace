"""Shared self-describing tool metadata surfaces across CLI/schema/MCP/errors."""

from __future__ import annotations

import json

from trade_trace.cli import main as cli_main
from trade_trace.mcp_server import mcp_call, mcp_tool_specs


def test_decision_add_help_renders_shared_metadata(capsys):
    rc = cli_main(["decision", "add", "--help"])

    out = capsys.readouterr()
    help_text = out.out + out.err
    assert rc == 0
    assert "usage summary:" in help_text
    assert "Record a trade decision" in help_text
    assert "examples:" in help_text
    assert "tt decision add" in help_text
    assert "enum notes:" in help_text
    assert "x-decision-matrix" in help_text
    assert "next actions:" in help_text


def test_tool_schema_exposes_same_metadata_for_representative_tools(tmp_path):
    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}).ok

    for tool in ("decision.add", "report.compare", "memory.reflect", "playbook.propose_version"):
        env = mcp_call("tool.schema", {"home": str(home), "tool": tool})
        assert env.ok, env
        assert hasattr(env, "data")
        metadata = env.data["metadata"]
        assert metadata["usage_summary"]
        assert metadata["examples"]
        assert metadata["common_failures"]
        assert metadata["next_actions"]

    decision_env = mcp_call("tool.schema", {"home": str(home), "tool": "decision.add"})
    assert decision_env.ok
    assert hasattr(decision_env, "data")
    decision = decision_env.data
    assert decision["metadata"]["enum_notes"]["type"]
    catalog_env = mcp_call("tool.schema", {"home": str(home)})
    assert catalog_env.ok
    assert hasattr(catalog_env, "data")
    catalog = catalog_env.data["tools"]
    catalog_decision = next(t for t in catalog if t["name"] == "decision.add")
    assert catalog_decision["metadata"] == decision["metadata"]


def test_mcp_tool_specs_include_metadata_and_augmented_description():
    spec = next(s for s in mcp_tool_specs() if s["name"] == "decision.add")
    assert spec["metadata"]["usage_summary"].startswith("Record a trade decision")
    assert spec["metadata"]["examples"]
    assert "Usage: Record a trade decision" in spec["description"]
    assert "Example: tt decision add" in spec["description"]


def test_help_and_mcp_specs_advertise_instrument_and_decision_optional_fields(capsys):
    rc = cli_main(["instrument", "add", "--help"])
    out = capsys.readouterr()
    instrument_help = out.out + out.err
    assert rc == 0
    for flag in (
        "--external-id <string>",
        "--symbol <string>",
        "--currency-or-collateral <string>",
        "--expiration-or-resolution-at <string>",
        "--resolution-criteria-text <string>",
        "--contract-multiplier <number>",
        "--metadata-json <object>",
    ):
        assert flag in instrument_help

    rc = cli_main(["decision", "add", "--help"])
    out = capsys.readouterr()
    decision_help = out.out + out.err
    assert rc == 0
    assert "--snapshot-id <string>" in decision_help

    specs = {s["name"]: s for s in mcp_tool_specs(include_legacy=True)}
    instrument_props = specs["instrument.add"]["input_schema"]["properties"]
    decision_props = specs["decision.add"]["input_schema"]["properties"]
    assert "snapshot_id" in decision_props
    for field in (
        "external_id",
        "symbol",
        "currency_or_collateral",
        "expiration_or_resolution_at",
        "resolution_criteria_text",
        "contract_multiplier",
        "metadata_json",
    ):
        assert field in instrument_props


def test_tool_schema_self_contract_is_advertised_in_cli_and_mcp(capsys):
    rc = cli_main(["tool", "schema", "--help"])

    out = capsys.readouterr()
    help_text = out.out + out.err
    assert rc == 0
    assert "--tool <string>" in help_text
    assert "optional" in help_text

    spec = next(s for s in mcp_tool_specs() if s["name"] == "tool.schema")
    schema = spec["input_schema"]
    assert schema["required"] == []
    assert schema["properties"]["tool"]["type"] == "string"


def test_source_freshness_help_and_mcp_schema_are_self_describing(capsys):
    rc = cli_main(["source", "add", "--help"])

    out = capsys.readouterr()
    help_text = out.out + out.err
    assert rc == 0
    assert "--freshness-at <string>" in help_text
    assert "stale_sources uses this field" in help_text
    assert "--retrieved-at <string>" in help_text
    assert "does not drive report.source_quality stale_sources" in help_text

    spec = next(s for s in mcp_tool_specs(include_legacy=True) if s["name"] == "source.add")
    props = spec["input_schema"]["properties"]
    assert "stale_sources uses this field" in props["freshness_at"]["description"]
    assert "does not drive report.source_quality stale_sources" in props["retrieved_at"]["description"]


def test_report_source_quality_help_and_mcp_schema_explain_stale_basis(capsys):
    rc = cli_main(["report", "source_quality", "--help"])

    out = capsys.readouterr()
    help_text = out.out + out.err
    assert rc == 0
    assert "sources.freshness_at" in help_text
    assert "retrieved_at" in help_text
    assert "not used as a fallback" in help_text

    spec = next(s for s in mcp_tool_specs() if s["name"] == "report.source_quality")
    combined = (
        spec["description"]
        + " "
        + spec["input_schema"]["properties"]["stale_threshold_days"]["description"]
    )
    assert "sources.freshness_at" in combined
    assert "retrieved_at" in combined


def test_unknown_cli_command_error_has_next_actions(capsys):
    rc = cli_main(["decision", "nope"])

    out = capsys.readouterr()
    assert rc == 1
    body = json.loads(out.out)
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert "next_actions" in body["error"]["details"]
    assert "tool schema" in " ".join(body["error"]["details"]["next_actions"])
