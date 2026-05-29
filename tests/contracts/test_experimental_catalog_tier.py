"""Contract for the `experimental` catalog-visibility tier (bead
trade-trace-4kec.2).

The tier freezes Product-B tools out of the default catalog without deleting
their handlers. The guarantees pinned here:

- An `experimental` tool is hidden from the default public catalog and from
  every default listing surface (`public_names`, `tool.schema` catalog mode,
  `mcp_tool_specs`).
- It stays dispatchable via `dispatch()` / `mcp_call`.
- `include_legacy` does NOT reveal it; only `include_experimental` does, and
  the two tiers are independent.
"""

from __future__ import annotations

from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.core import build_registry
from trade_trace.mcp_server import mcp_call, mcp_tool_specs


def _handler(args, ctx):
    return {"ok": True}


def _registry_with_tiers() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("frozen.tool", _handler, description="frozen B surface")
    reg.register("legacy.tool", _handler, description="legacy surface")
    reg.register("normal.tool", _handler, description="default surface")
    reg.mark("frozen.tool", catalog_visibility="experimental")
    reg.mark("legacy.tool", catalog_visibility="legacy")
    return reg


def test_experimental_tool_hidden_from_default_catalog():
    reg = _registry_with_tiers()
    default = reg.public_names()
    assert "normal.tool" in default
    assert "frozen.tool" not in default
    assert "legacy.tool" not in default


def test_include_legacy_does_not_surface_experimental():
    reg = _registry_with_tiers()
    legacy_view = reg.public_names(include_legacy=True)
    assert "legacy.tool" in legacy_view
    assert "frozen.tool" not in legacy_view


def test_include_experimental_surfaces_only_experimental():
    reg = _registry_with_tiers()
    experimental_view = reg.public_names(include_experimental=True)
    assert "frozen.tool" in experimental_view
    assert "legacy.tool" not in experimental_view


def test_experimental_tool_remains_dispatchable():
    reg = _registry_with_tiers()
    # Visibility is a listing concern only; the handler resolves by name.
    assert "frozen.tool" in reg.by_name
    assert reg.get("frozen.tool").handler is _handler


def test_mcp_tool_specs_honor_experimental_flag():
    reg = _registry_with_tiers()
    default_names = {spec["name"] for spec in mcp_tool_specs(reg)}
    assert "frozen.tool" not in default_names
    opted_in = {spec["name"] for spec in mcp_tool_specs(reg, include_experimental=True)}
    assert "frozen.tool" in opted_in


def test_real_registry_has_no_unexpected_experimental_leak(tmp_path):
    # The shipped registry should currently expose no experimental tools in the
    # default catalog; this guards future freeze beads against accidental leaks.
    reg = build_registry()
    for reg_entry in reg.public_registrations():
        assert reg_entry.catalog_visibility != "experimental", reg_entry.name

    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}).ok
    catalog = mcp_call("tool.schema", {"home": str(home)})
    assert catalog.ok
    assert hasattr(catalog, "data")
    for tool in catalog.data["tools"]:
        assert tool["metadata"]["catalog_visibility"] != "experimental", tool["name"]
