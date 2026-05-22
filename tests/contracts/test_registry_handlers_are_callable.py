"""Global contract per trade-trace-r85a: every registered tool must have
a callable handler. The per-module `test_*_registered` checks used to
only assert "name in default_registry().names()" — they would pass even
if a registration had `handler=None`. This contract test runs once for
every tool in the registry so the trivial per-tool checks become a
double-floor instead of the only guard.
"""

from __future__ import annotations

import pytest

from trade_trace.core import default_registry


@pytest.mark.parametrize("tool_name", sorted(default_registry().names()))
def test_registered_tool_has_a_callable_handler(tool_name):
    registration = default_registry().get(tool_name)
    assert registration.name == tool_name, registration
    assert callable(registration.handler), (
        f"{tool_name!r} is registered but its handler is not callable: "
        f"{registration.handler!r}"
    )
    assert isinstance(registration.is_write, bool), registration
    assert isinstance(registration.cli_invocation, tuple), registration
