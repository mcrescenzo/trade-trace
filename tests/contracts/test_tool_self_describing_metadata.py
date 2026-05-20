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


def test_unknown_cli_command_error_has_next_actions(capsys):
    rc = cli_main(["decision", "nope"])

    out = capsys.readouterr()
    assert rc == 1
    body = json.loads(out.out)
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert "next_actions" in body["error"]["details"]
    assert "tool schema" in " ".join(body["error"]["details"]["next_actions"])
