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
