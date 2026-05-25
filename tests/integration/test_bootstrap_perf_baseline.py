from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call

PERF_TESTS_ENV = "TRADE_TRACE_RUN_PERF_TESTS"
BOOTSTRAP_BUDGET_SECONDS = 1.0

pytestmark = pytest.mark.skipif(
    os.environ.get(PERF_TESTS_ENV) != "1",
    reason=f"Perf baseline opt-in; set {PERF_TESTS_ENV}=1 to run.",
)


def test_report_bootstrap_empty_home_under_budget(tmp_path: Path):
    home = tmp_path / "bootstrap-perf"
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok, init

    start = time.perf_counter()
    env = mcp_call("report.bootstrap", {"home": str(home), "as_of": "2026-05-25T00:00:00Z"})
    elapsed = time.perf_counter() - start

    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True, body
    assert body["data"]["kind"] == "agent.bootstrap"
    assert elapsed < BOOTSTRAP_BUDGET_SECONDS, (
        f"report.bootstrap took {elapsed:.3f}s (budget {BOOTSTRAP_BUDGET_SECONDS}s)"
    )
