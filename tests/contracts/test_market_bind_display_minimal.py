"""`market.bind`'s displayed minimal example is decoupled from its
schema-derivation source per bead trade-trace-mpsu.

`tool.schema --tool market.bind` must present a *minimal* example showing
only the four required fields (source, external_id, state, mechanism) plus
a couple of core fields — NOT the ~30-key `example_minimal` that obscures
them. At the same time, the derived `json_schema` must keep advertising
every accepted property (it is derived from the full `example_minimal`,
not the trimmed display example), so schema-validating clients still
discover the full call shape.
"""

from __future__ import annotations

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call

REQUIRED_FIELDS = ("source", "external_id", "state", "mechanism")

# A handful of optional keys that live in `example_minimal` (and therefore
# in the derived schema) but must NOT appear in the trimmed display example.
TRIMMED_OPTIONAL_KEYS = (
    "ambiguity_kind",
    "fee_rate_bps",
    "event_grouping",
    "resolution_rule",
    "outcome_ids_by_label",
    "negative_risk",
    "tick_size",
    "rewards",
    "rebates",
)


def test_display_minimal_shows_only_required_plus_core_fields() -> None:
    reg = default_registry().get("market.bind")
    display = reg.display_example_minimal()
    assert display is not None

    # Every required field is present in the displayed example.
    for field in REQUIRED_FIELDS:
        assert field in display, f"display example missing required {field!r}"

    # The displayed example is genuinely minimal: it stays small and does
    # not re-introduce the bulk of optional metadata.
    for key in TRIMMED_OPTIONAL_KEYS:
        assert key not in display, (
            f"display example should not surface optional {key!r}; it buries "
            "the four required fields (see bead trade-trace-mpsu)."
        )
    assert len(display) <= 8, (
        f"display example has {len(display)} keys; it should stay minimal "
        "(required + a couple of core fields)."
    )


def test_display_minimal_is_decoupled_from_schema_source() -> None:
    reg = default_registry().get("market.bind")

    # The schema-derivation source keeps every accepted property.
    assert reg.example_minimal is not None
    schema_props = (reg.json_schema or {}).get("properties", {})
    for key in TRIMMED_OPTIONAL_KEYS:
        assert key in reg.example_minimal, (
            f"{key!r} must remain in example_minimal so the derived schema "
            "keeps advertising it."
        )
        assert key in schema_props, (
            f"{key!r} must stay in the derived json_schema properties — "
            "trimming the display example must not shrink the schema."
        )

    # The two are actually different objects: trimming the display did not
    # silently mutate the schema source.
    display = reg.display_example_minimal()
    assert display is not None
    assert set(display) < set(reg.example_minimal)


def test_tool_schema_surfaces_trimmed_display_example(tmp_path) -> None:
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok

    env = mcp_call("tool.schema", {"home": home, "tool": "market.bind"}, actor_id="agent:test")
    assert env.ok, env
    data = env.data

    example = data["example_minimal"]
    for field in REQUIRED_FIELDS:
        assert field in example
    for key in TRIMMED_OPTIONAL_KEYS:
        assert key not in example

    # The advertised json_schema still carries the full property set.
    schema_props = data["json_schema"]["properties"]
    for key in TRIMMED_OPTIONAL_KEYS:
        assert key in schema_props


def test_displayed_example_is_a_valid_dry_run_call(tmp_path) -> None:
    """The trimmed display example must remain a real, callable payload —
    showing fewer fields must not show an *invalid* one."""

    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok

    env = mcp_call("tool.schema", {"home": home, "tool": "market.bind"}, actor_id="agent:test")
    assert env.ok, env
    example = dict(env.data["example_minimal"])
    example["home"] = home
    example["_dry_run"] = True

    result = mcp_call("market.bind", example, actor_id="agent:test")
    assert result.ok, result
    assert result.meta.dry_run is True
