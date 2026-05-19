"""Every `is_write=True` registered tool must expose a non-null
`json_schema` per trade-trace-3i33. Before the fix, 8 write tools
(snapshot.add, the four source.attach_to_*, memory.retain/reflect/
link, playbook.create/propose_version, decision.record_adherence,
strategy.create/update, plus admin / import writes) had
`json_schema=None`, forcing agents to read Python source to discover
required arguments.
"""

from __future__ import annotations

from trade_trace.core import default_registry


def test_every_write_tool_has_json_schema():
    reg = default_registry()
    missing = [
        name
        for name, r in reg.by_name.items()
        if r.is_write and r.json_schema is None
    ]
    assert not missing, (
        "write tool(s) without a json_schema (agents cannot discover "
        f"required arguments via `tool.schema`): {sorted(missing)!r}. "
        "Add the example_minimal entry in tools/_examples.py and wire it "
        "via `**_examples_for('tool.name')` in the registration."
    )


def test_every_write_tool_has_example_minimal():
    """A non-null json_schema is currently derived from example_minimal.
    A registration without an example would silently fall back to the
    auto-derive's empty-object output, so pin the relationship here."""

    reg = default_registry()
    missing = [
        name
        for name, r in reg.by_name.items()
        if r.is_write and r.example_minimal is None
    ]
    assert not missing, (
        f"write tool(s) without example_minimal: {sorted(missing)!r}. "
        "Add the entry in tools/_examples.py and wire it via "
        "`**_examples_for(...)`."
    )
