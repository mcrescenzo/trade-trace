"""JSONL import contract stubs per trade-trace-bwo.

The M1 commitment per PRD §4.7 / imports.md §1 is the **import-ready
write schema**: every write tool is callable from the same JSONL handler
the importer will use. Implementation of `import.validate` / `import.commit`
is P1. This test confirms (a) the contract surface exists, (b) the line
shape is documented in code, (c) every M1 write tool is reachable via the
core dispatcher with a `{tool, args}` envelope.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from tests._mcp_helpers import with_legacy_idempotency_key
from trade_trace.cli import main as cli_main
from trade_trace.core import default_registry, dispatch
from trade_trace.mcp_server import mcp_call
from trade_trace.tools.imports import (
    ImportCommitOutput,
    ImportJSONLLine,
    ImportValidateOutput,
)


def test_import_validate_registered():
    assert "import.validate" in default_registry().names()


def test_import_commit_registered():
    assert "import.commit" in default_registry().names()


def test_import_validate_reports_missing_path():
    env = mcp_call("import.validate", {"path": "/tmp/x.jsonl"}).model_dump(
        mode="json", exclude_none=True
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "NOT_FOUND"


def test_import_commit_reports_missing_path():
    env = mcp_call("import.commit", with_legacy_idempotency_key("import.commit", {"path": "/tmp/x.jsonl"})).model_dump(
        mode="json", exclude_none=True
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "NOT_FOUND"


def test_jsonl_line_schema_documents_shape():
    schema = ImportJSONLLine.model_json_schema()
    assert "tool" in schema["properties"]
    assert "args" in schema["properties"]


def test_import_validate_output_schema():
    schema = ImportValidateOutput.model_json_schema()
    for field in ("validated", "would_create", "would_replay", "errors", "warnings", "id_strategy"):
        assert field in schema["properties"]


def test_import_commit_output_schema():
    schema = ImportCommitOutput.model_json_schema()
    for field in ("validated", "committed_count", "committed_event_ids", "errors"):
        assert field in schema["properties"]


def test_import_ready_writers_registered():
    """The importer replays write tools through the shared core registry."""

    writers = set(default_registry().names())
    expected = {
        "venue.add", "instrument.add", "snapshot.add",
        "thesis.add", "forecast.add", "forecast.supersede",
        "decision.add", "resolution.add", "outcome.add", "resolve.record",
        "source.add",
        "source.attach_to_thesis", "source.attach_to_decision",
        "source.attach_to_forecast", "playbook.upsert", "playbook.create",
        "strategy.upsert", "strategy.create",
    }
    assert expected.issubset(writers)


def test_legacy_renamed_writers_remain_hidden_dispatch_aliases():
    registry = default_registry()
    public = set(registry.public_names())
    for old, canonical in {
        "outcome.add": "resolution.add",
        "strategy.create": "strategy.upsert",
        "playbook.create": "playbook.upsert",
    }.items():
        assert old in registry.names()
        assert canonical in public
        assert old not in public
        assert registry.get(old).handler is registry.get(canonical).handler


def test_jsonl_envelope_replay_through_core(tmp_path: Path):
    """An exporter-shaped JSONL line replays cleanly through dispatch()
    without needing the future importer — the load-bearing 'import-ready
    write schema' commitment."""

    # journal.init the DB
    mcp_call("journal.init", {"home": str(tmp_path / "home")})

    # Build a JSONL line by hand and route its args through dispatch.
    line = {
        "tool": "venue.add",
        "args": {
            "name": "Polymarket",
            "kind": "prediction_market",
            "home": str(tmp_path / "home"),
            # Importer-shaped extras the dispatcher tolerates:
            "_event_id": 42,
            "_event_type": "venue.created",
            "_actor_id": "import:fixture-2026",
            "_created_at": "2026-05-18T14:00:00Z",
            "_contract_version": "1.0",
        },
    }
    # Strip the underscore-prefixed transport metadata that the importer
    # would drop before calling dispatch.
    line_args = line["args"]
    assert isinstance(line_args, dict)
    line_tool = line["tool"]
    assert isinstance(line_tool, str)
    domain_args = {k: v for k, v in line_args.items() if not k.startswith("_")}
    env = dispatch(line_tool, domain_args, actor_id="import:fixture-2026").model_dump(
        mode="json", exclude_none=True
    )
    assert env["ok"] is True
    assert env["data"]["name"] == "Polymarket"


def test_cli_import_commit_parity():
    mcp = mcp_call(
        "import.commit", {"path": "/tmp/x.jsonl", "_allow_no_idempotency": True}
    ).model_dump(mode="json", exclude_none=True)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "--actor-id", "agent:default",
            "--request-id", "rid",
            "--allow-no-idempotency",
            "import", "commit",
            "--path", "/tmp/x.jsonl",
        ])
    cli = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert rc == 1
    assert mcp["error"]["code"] == cli["error"]["code"] == "NOT_FOUND"
