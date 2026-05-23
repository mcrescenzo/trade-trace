"""Pytest configuration.

Adds `src/` to sys.path for in-tree imports without requiring `pip install -e .`
to land before tests can run. Also installs a session-wide patch that
auto-injects an `idempotency_key` for write tools when neither a key nor
the `_allow_no_idempotency` opt-in is supplied — see trade-trace-cpz2.
Tests marked `strict_idempotency` opt out and see the unpatched dispatch
so they can exercise the rejection contract.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest  # noqa: E402

from trade_trace import cli as _cli  # noqa: E402
from trade_trace import core as _core  # noqa: E402
from trade_trace import mcp_server as _mcp_server  # noqa: E402

_ORIGINAL_DISPATCH = _core.dispatch
_AUTO_KEY_COUNTER = [0]


def _next_auto_key(tool: str) -> str:
    _AUTO_KEY_COUNTER[0] += 1
    return f"test-auto:{tool}:{_AUTO_KEY_COUNTER[0]:08d}"


def _auto_keying_dispatch(
    tool_name: str,
    args: dict[str, Any],
    *,
    actor_id: str = "cli:default",
    request_id: str | None = None,
    registry=None,
):
    reg = registry if registry is not None else _core.default_registry()
    try:
        registration = reg.get(tool_name)
        if (
            registration.is_write
            and not args.get("idempotency_key")
            and args.get("_allow_no_idempotency") is not True
        ):
            args = {**args, "idempotency_key": _next_auto_key(tool_name)}
    except (KeyError, AttributeError):
        pass
    return _ORIGINAL_DISPATCH(
        tool_name, args, actor_id=actor_id, request_id=request_id, registry=registry,
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "strict_idempotency: run with the unpatched dispatch so the test sees "
        "the strict idempotency_key enforcement on write tools (trade-trace-cpz2)",
    )
    _core.dispatch = _auto_keying_dispatch
    _cli.dispatch = _auto_keying_dispatch
    _mcp_server.dispatch = _auto_keying_dispatch


@pytest.fixture(autouse=True)
def _reset_auto_key_counter_per_test():
    """Reset the auto-idempotency-key counter between tests so each test
    starts from a known state. Without this the counter accumulates across
    the whole session (trade-trace-r85a), which makes test failures harder
    to reproduce in isolation.

    Per bead trade-trace-8e3b the same hook also drains the deterministic
    request-id and id-prefix counters so a test that leaks a partially
    used CLOCK_OVERRIDE context cannot poison the next test's id sequence.
    """
    _AUTO_KEY_COUNTER[0] = 0
    from trade_trace.core import _reset_deterministic_request_id_counter
    from trade_trace.tools._helpers import reset_deterministic_id_counter

    _reset_deterministic_request_id_counter()
    reset_deterministic_id_counter()
    yield


@pytest.fixture(autouse=True)
def _restore_strict_dispatch_for_marker(request):
    if request.node.get_closest_marker("strict_idempotency"):
        prior_core = _core.dispatch
        prior_cli = _cli.dispatch
        prior_mcp = _mcp_server.dispatch
        _core.dispatch = _ORIGINAL_DISPATCH
        _cli.dispatch = _ORIGINAL_DISPATCH
        _mcp_server.dispatch = _ORIGINAL_DISPATCH
        try:
            yield
        finally:
            _core.dispatch = prior_core
            _cli.dispatch = prior_cli
            _mcp_server.dispatch = prior_mcp
    else:
        yield


@pytest.fixture
def initialized_home(tmp_path):
    """Per-test isolated `$TRADE_TRACE_HOME` directory with the journal
    schema already migrated (trade-trace-qs5v / SIMP-008). 30+ tests
    previously redefined the same three-line `home` fixture; this is
    the shared shape. Tests that need a customized init flow (e.g.,
    `_journal_init` with extra args) keep their per-file fixture.
    """

    from trade_trace.mcp_server import mcp_call

    h = tmp_path / "home"
    init = mcp_call("journal.init", {"home": str(h)})
    assert init.ok, init
    return h


@pytest.fixture
def home(initialized_home):
    """Per-test isolated initialized home alias for exact duplicate tests."""

    return initialized_home
