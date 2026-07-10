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

ADAPTER_BACKED_POLYMARKET_TOOLS = frozenset(
    {
        "market.refresh",
        "market.search",
        "outcome.fetch",
        "snapshot.fetch",
        "snapshot.fetch_series",
    }
)


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


def test_destructive_operator_tools_are_admin_gated():
    """Regression for bead trade-trace-6rnk.

    journal.backup, journal.restore, and journal.config_set are destructive
    operator-only tools registered is_write=True. They must be is_admin=True so
    the default catalog view (public_names(include_admin=False)) never surfaces
    them to non-admin agents. model.import and memory.reindex are gated for
    defense in depth: even include_legacy=True must not re-surface them.
    """

    reg = build_registry()
    destructive = (
        "journal.backup",
        "journal.restore",
        "journal.config_set",
        "model.import",
        "memory.reindex",
    )

    default = set(reg.public_names())
    legacy_view = set(reg.public_names(include_legacy=True))
    experimental_view = set(reg.public_names(include_experimental=True))
    admin_view = set(reg.public_names(include_admin=True, include_legacy=True, include_experimental=True))

    for name in destructive:
        assert name in reg.by_name, f"{name} should be registered"
        assert reg.get(name).is_admin, f"{name} must be is_admin=True"
        # Excluded from every non-admin listing surface.
        assert name not in default, f"{name} leaked into default catalog"
        assert name not in legacy_view, f"{name} leaked via include_legacy"
        assert name not in experimental_view, f"{name} leaked via include_experimental"
        # Still reachable when the operator explicitly opts into admin tools.
        assert name in admin_view, f"{name} should appear in the admin view"


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


def test_adapter_backed_polymarket_tools_require_catalog_opt_in(tmp_path):
    """Live adapter surfaces stay dispatchable but are hidden by default.

    The Polymarket adapter is disabled unless an operator configures it, and the
    network-backed tool surfaces should not appear in the default catalog that a
    fresh MCP client sees. Explicit experimental opt-in is required to list them.
    """

    reg = build_registry()
    all_names = set(reg.names())
    default_names = set(reg.public_names())
    legacy_names = set(reg.public_names(include_legacy=True))
    experimental_names = set(reg.public_names(include_experimental=True))

    assert ADAPTER_BACKED_POLYMARKET_TOOLS.issubset(all_names)
    assert ADAPTER_BACKED_POLYMARKET_TOOLS.isdisjoint(default_names)
    assert ADAPTER_BACKED_POLYMARKET_TOOLS.isdisjoint(legacy_names)
    assert ADAPTER_BACKED_POLYMARKET_TOOLS.issubset(experimental_names)
    for name in ADAPTER_BACKED_POLYMARKET_TOOLS:
        assert reg.get(name).metadata()["catalog_visibility"] == "experimental"

    default_specs = {spec["name"] for spec in mcp_tool_specs(reg)}
    opted_in_specs = {spec["name"] for spec in mcp_tool_specs(reg, include_experimental=True)}
    assert ADAPTER_BACKED_POLYMARKET_TOOLS.isdisjoint(default_specs)
    assert ADAPTER_BACKED_POLYMARKET_TOOLS.issubset(opted_in_specs)

    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}).ok
    default_catalog = mcp_call("tool.schema", {"home": str(home)})
    assert default_catalog.ok
    assert ADAPTER_BACKED_POLYMARKET_TOOLS.isdisjoint(
        {tool["name"] for tool in default_catalog.data["tools"]}
    )
    opted_in_catalog = mcp_call(
        "tool.schema", {"home": str(home), "include_experimental": True}
    )
    assert opted_in_catalog.ok
    assert ADAPTER_BACKED_POLYMARKET_TOOLS.issubset(
        {tool["name"] for tool in opted_in_catalog.data["tools"]}
    )
