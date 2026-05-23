"""M1 manual ledger / source / resolution write tools per PRD §4.0–§4.5.

This package is a thin composition layer over the per-domain submodules.
Each handler lives next to its schema and `register_<domain>_tools`
function in its own module (`venue.py`, `instrument.py`, `snapshot.py`,
`thesis.py`, `forecast.py`, `decision.py`, `outcome.py`, `source.py`);
`register_ledger_tools` composes them. Cross-domain scoring helpers
live in `_scoring.py` and are re-exported below so `journal.py` rescan
and `tests/integration/test_scoring_lifecycle.py` keep their existing
import surface.

Decomposition completed under bead trade-trace-pcxf (final step:
trade-trace-36ui).
"""

from __future__ import annotations

from trade_trace.contracts.tool_registry import ToolRegistry

# Re-exported for external callers (journal.py rescan, tests/integration/
# test_scoring_lifecycle.py). The aliases are deliberate per ruff PLC0414
# so the surface is explicit.
from trade_trace.tools.ledger._scoring import (
    _autoscore_pending_forecasts as _autoscore_pending_forecasts,
)
from trade_trace.tools.ledger._scoring import (
    _current_resolved_final_outcome as _current_resolved_final_outcome,
)
from trade_trace.tools.ledger._scoring import (
    _emit_forecast_scored as _emit_forecast_scored,
)
from trade_trace.tools.ledger._scoring import (
    _score_one_forecast as _score_one_forecast,
)
from trade_trace.tools.ledger._scoring import (
    derive_scoring_state as derive_scoring_state,
)
from trade_trace.tools.ledger.decision import register_decision_tools
from trade_trace.tools.ledger.forecast import register_forecast_tools
from trade_trace.tools.ledger.instrument import register_instrument_tools
from trade_trace.tools.ledger.outcome import register_outcome_tools
from trade_trace.tools.ledger.snapshot import register_snapshot_tools
from trade_trace.tools.ledger.source import register_source_tools
from trade_trace.tools.ledger.thesis import register_thesis_tools
from trade_trace.tools.ledger.venue import register_venue_tools


def register_ledger_tools(registry: ToolRegistry) -> None:
    """Register all M1 manual ledger / source / resolution write tools."""

    register_venue_tools(registry)
    register_instrument_tools(registry)
    register_snapshot_tools(registry)
    register_thesis_tools(registry)
    register_forecast_tools(registry)
    register_decision_tools(registry)
    register_outcome_tools(registry)
    register_source_tools(registry)
