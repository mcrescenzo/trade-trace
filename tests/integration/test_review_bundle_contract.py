"""review.bundle contract stub per trade-trace-7w1."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from trade_trace.cli import main as cli_main
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.tools.review_bundle import ReviewBundleInput, ReviewBundleOutput


def test_review_bundle_registered():
    """The tool must be present in the default registry."""

    registry = default_registry()
    assert "review.bundle" in registry.names()


def test_review_bundle_returns_unsupported_capability():
    env = mcp_call("review.bundle", {"filter": {}, "max_records": 10})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is False
    assert body["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert body["error"]["details"]["reason"] == "implementation_deferred_p1"
    assert "P1" in body["error"]["message"]


def test_review_bundle_input_schema_introspectable():
    """Pydantic schema is introspectable so the agent knows the shape."""

    schema = ReviewBundleInput.model_json_schema()
    assert "filter" in schema["properties"]
    assert "max_records" in schema["properties"]
    assert schema["properties"]["max_records"]["maximum"] == 200


def test_review_bundle_output_schema_carries_bundle_hash():
    schema = ReviewBundleOutput.model_json_schema()
    assert "bundle_hash" in schema["properties"]
    assert "selected" in schema["properties"]
    assert "caveats" in schema["properties"]


def test_cli_review_bundle_parity():
    """CLI and MCP both surface the same UNSUPPORTED_CAPABILITY envelope."""

    mcp = mcp_call("review.bundle", {"filter": {}}).model_dump(mode="json", exclude_none=True)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "--actor-id", "agent:default",
            "--request-id", "rid",
            "review", "bundle",
            "--filter-json", "{}",
        ])
    cli = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert rc == 1
    assert mcp["error"]["code"] == cli["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert mcp["error"]["details"]["reason"] == cli["error"]["details"]["reason"]
