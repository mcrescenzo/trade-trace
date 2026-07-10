from __future__ import annotations

import re
from pathlib import Path

from trade_trace.core import build_registry
from trade_trace.mcp_server import mcp_call, mcp_tool_specs

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "architecture" / "non-adapter-experimental-tool-disposition.md"

NON_ADAPTER_EXPERIMENTAL_TOOLS = frozenset(
    {
        "approval.get",
        "approval.list",
        "approval.record",
        "approval.report",
        "forecast.anchor_to_snapshot",
    }
)

ADAPTER_BACKED_EXPERIMENTAL_TOOLS = frozenset(
    {
        "market.refresh",
        "market.search",
        "outcome.fetch",
        "snapshot.fetch",
        "snapshot.fetch_series",
    }
)


def _decision_rows() -> dict[str, str]:
    text = DOC.read_text(encoding="utf-8")
    match = re.search(
        r"<!-- non-adapter-experimental-disposition:start -->(.*?)"
        r"<!-- non-adapter-experimental-disposition:end -->",
        text,
        re.DOTALL,
    )
    assert match is not None, "non-adapter experimental disposition markers missing"

    rows: dict[str, str] = {}
    for row_match in re.finditer(
        r"^\|\s*`([^`]+)`\s*\|\s*([^|\s]+)\s*\|",
        match.group(1),
        re.MULTILINE,
    ):
        tool_name, decision = row_match.groups()
        assert tool_name not in rows, f"duplicate disposition row for {tool_name}"
        rows[tool_name] = decision
    return rows


def test_decision_record_covers_exact_non_adapter_experimental_scope() -> None:
    rows = _decision_rows()
    assert rows == {name: "keep-experimental" for name in NON_ADAPTER_EXPERIMENTAL_TOOLS}
    assert set(rows).isdisjoint(ADAPTER_BACKED_EXPERIMENTAL_TOOLS)

    text = DOC.read_text(encoding="utf-8")
    assert "trade-trace-cjgz2.2" in text
    assert "Owner-only decision" in text
    for adapter_name in ADAPTER_BACKED_EXPERIMENTAL_TOOLS:
        assert adapter_name in text


def test_decision_record_matches_runtime_visibility(tmp_path: Path) -> None:
    registry = build_registry()
    default_names = set(registry.public_names())
    legacy_names = set(registry.public_names(include_legacy=True))
    experimental_names = set(registry.public_names(include_experimental=True))
    default_specs = {spec["name"] for spec in mcp_tool_specs(registry)}
    experimental_specs = {
        spec["name"] for spec in mcp_tool_specs(registry, include_experimental=True)
    }

    for name in NON_ADAPTER_EXPERIMENTAL_TOOLS:
        registration = registry.get(name)
        assert registration.metadata()["catalog_visibility"] == "experimental"
        assert name not in default_names
        assert name not in legacy_names
        assert name in experimental_names
        assert name not in default_specs
        assert name in experimental_specs

    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}).ok
    default_catalog = mcp_call("tool.schema", {"home": str(home)})
    experimental_catalog = mcp_call(
        "tool.schema",
        {"home": str(home), "include_experimental": True},
    )
    assert default_catalog.ok
    assert experimental_catalog.ok

    default_schema_names = {tool["name"] for tool in default_catalog.data["tools"]}
    experimental_schema_names = {
        tool["name"] for tool in experimental_catalog.data["tools"]
    }
    assert NON_ADAPTER_EXPERIMENTAL_TOOLS.isdisjoint(default_schema_names)
    assert NON_ADAPTER_EXPERIMENTAL_TOOLS <= experimental_schema_names
