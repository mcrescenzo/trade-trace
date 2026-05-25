"""Pytest configuration.

Adds `src/` to sys.path for in-tree imports without requiring `pip install -e .`
to land before tests can run. Dispatch is intentionally unpatched: omitted-key
write calls should exercise production auto-derivation rather than a global
test-only idempotency-key injector.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest  # noqa: E402


@pytest.fixture
def legacy_auto_idempotency_key():
    """Opt-in helper for legacy tests that need synthetic unique keys.

    New omitted-key write tests should usually omit `idempotency_key` and assert
    production `meta.idempotency_source == "auto"`. Use this only when a test's
    purpose is unrelated to idempotency but it must steer past dispatch-level
    key validation for tools that are intentionally outside auto-derivation, or
    when it needs caller-controlled replay/conflict semantics.
    """

    counter = 0

    def _next(tool: str = "write") -> str:
        nonlocal counter
        counter += 1
        return f"test-legacy:{tool}:{counter:08d}"

    return _next


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "strict_idempotency: compatibility marker retained for older tests; "
        "dispatch is no longer patched globally.",
    )


@pytest.fixture(autouse=True)
def _reset_deterministic_counters_per_test():
    """Reset deterministic request-id/id-prefix counters between tests.

    Per bead trade-trace-8e3b this prevents a test that leaks a partially
    used CLOCK_OVERRIDE context from poisoning the next test's id sequence.
    """
    from trade_trace.core import _reset_deterministic_request_id_counter
    from trade_trace.tools._helpers import reset_deterministic_id_counter

    _reset_deterministic_request_id_counter()
    reset_deterministic_id_counter()
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
