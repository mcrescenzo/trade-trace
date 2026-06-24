"""`_parse_kv_args` repeated-flag → list accumulation per
trade-trace-pybt. Docs/contracts.md §2.1 documents repeated array
flags; before the fix, the parser overwrote the previous value and
silently dropped earlier list items.
"""

from __future__ import annotations

from trade_trace.cli import _parse_kv_args


def test_repeated_flag_accumulates_into_list():
    """Two `--node-types` values land in a list, in order, with each
    value coerced individually."""

    parsed = _parse_kv_args(
        ["--node-types", "observation", "--node-types", "reflection"],
    )
    assert parsed == {"node_types": ["observation", "reflection"]}


def test_repeated_flag_preserves_type_coercion_per_value():
    """Each repeated value coerces independently — integers stay
    integers, booleans stay booleans."""

    parsed = _parse_kv_args(
        ["--ks", "5", "--ks", "10", "--flags", "true", "--flags", "false"],
    )
    assert parsed["ks"] == [5, 10]
    assert parsed["flags"] == [True, False]


def test_single_flag_remains_scalar():
    """A non-repeated flag retains its scalar shape — the list
    accumulator does not wrap a one-occurrence value."""

    parsed = _parse_kv_args(["--node-type", "observation"])
    assert parsed == {"node_type": "observation"}


def test_comma_value_is_not_split():
    """Comma-separated values stay as a single string. Callers who
    want a JSON array use `--<key>-json '[…]'` instead."""

    parsed = _parse_kv_args(["--tags", "a,b,c"])
    assert parsed == {"tags": "a,b,c"}


def test_json_flag_after_repeated_scalar_still_lists():
    """A `--key-json` after a `--key` would semantically conflict; we
    keep the documented behavior of accumulating both into the list
    (no special-casing) so the agent gets a typed error from the
    runtime tool if it intended distinct shapes."""

    parsed = _parse_kv_args(
        ["--tags", "alpha", "--tags-json", '["beta", "gamma"]'],
    )
    assert parsed == {"tags": ["alpha", ["beta", "gamma"]]}


def test_schema_literal_json_field_is_preserved():
    parsed = _parse_kv_args(
        [
            "--metadata-json", '{"source": "cli"}',
            "--liquidity-depth-json", '{"bids": [[0.4, 12]]}',
        ],
        schema_fields={"metadata_json", "liquidity_depth_json"},
    )
    assert parsed == {
        "metadata_json": {"source": "cli"},
        "liquidity_depth_json": {"bids": [[0.4, 12]]},
    }


def test_json_transport_hint_still_strips_for_non_json_schema_field():
    parsed = _parse_kv_args(
        ["--filter-json", '{"status": "active"}'],
        schema_fields={"filter"},
    )
    assert parsed == {"filter": {"status": "active"}}
