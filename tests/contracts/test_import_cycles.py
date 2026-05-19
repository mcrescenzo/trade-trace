"""Per-module import smoke tests per trade-trace-9oxn.

Direct `import trade_trace.tools.admin` (and other public modules)
used to fail with a circular ImportError on a fresh interpreter
because `trade_trace.contracts.grammar` imported `ToolError` at module
top level, which dragged `tools.errors` → `contracts.errors` →
`contracts.__init__` → `contracts.grammar` back through itself.

Running each import in a subprocess gives a fresh interpreter per
test; the test fails loudly if the cycle returns.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

# Representative public modules an external integration might import
# directly without first going through `trade_trace.__init__`.
PUBLIC_MODULES = [
    "trade_trace.tools.admin",
    "trade_trace.tools.errors",
    "trade_trace.contracts.grammar",
    "trade_trace.cli",
    "trade_trace.core",
    "trade_trace.events.log",
]


@pytest.mark.parametrize("module", PUBLIC_MODULES)
def test_module_imports_in_fresh_interpreter(module: str):
    """Each module must import cleanly when it's the first
    trade_trace module touched in the interpreter."""

    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"`import {module}` failed in a fresh interpreter:\n"
        f"stdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
