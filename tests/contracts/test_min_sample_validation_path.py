"""Handler-level `int(min_sample)` guard coverage for the calibration
diagnostics report family (bead trade-trace-rseh).

The MCP stdio boundary declares `min_sample` as an integer, so the
gateway rejects non-integers (e.g. ``"abc"``) *before* the handler runs
— that path is covered by ``test_min_sample_validation_parity.py``. But
the handlers in
``trade_trace.reports.tool_handlers.calibration_diagnostics`` each wrap
``int(min_sample)`` in a ``try/except (ValueError, TypeError)`` so that a
*direct-dispatch* caller (CLI ``dispatch`` without a schema pre-check, or
``mcp_call`` in-process) that slips a non-coercible value through still
gets a clean ``VALIDATION_ERROR`` envelope instead of an uncaught
exception.

These tests call the handlers via ``mcp_call`` (which dispatches without
the stdio schema gate) with ``min_sample="abc"`` to exercise exactly that
handler-level fallback guard. Only three handlers in the family —
``report.calibration_advisory``, ``report.mistake_tripwire``, and
``report.process_quality`` — carry the ``(ValueError, TypeError)`` catch
block; the parametrization below pins each one's reported ``field`` so a
future refactor that drops the guard (and lets the raw ``ValueError``
escape as an INTERNAL error) is caught.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _call(tool: str, home: Path, **extra: Any) -> dict[str, Any]:
    """Dispatch ``tool`` via the in-process MCP shim, bypassing the stdio
    schema gate so a non-coercible ``min_sample`` reaches the handler."""

    return mcp_call(
        tool,
        {"home": str(home), "min_sample": "abc", **extra},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)


# (tool, extra-required-args, field reported by that handler's guard).
# The field differs per handler because each guard re-uses a nearby
# argument name in its details; this pins the observed envelope shape so
# the coverage is meaningful rather than a smoke test.
_GUARDED_HANDLERS = [
    pytest.param(
        "report.calibration_advisory",
        {"probability": 0.5},
        "probability",
        id="calibration_advisory",
    ),
    pytest.param("report.mistake_tripwire", {}, "tags", id="mistake_tripwire"),
    pytest.param("report.process_quality", {}, "min_sample", id="process_quality"),
]


@pytest.mark.parametrize("tool, extra, field", _GUARDED_HANDLERS)
def test_handler_rejects_non_coercible_min_sample(
    home: Path, tool: str, extra: dict[str, Any], field: str
) -> None:
    body = _call(tool, home, **extra)
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["field"] == field
