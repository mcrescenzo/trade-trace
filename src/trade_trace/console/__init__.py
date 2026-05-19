"""Trade Trace Console — read-only local dashboard package.

See `docs/architecture/console.md` for the accepted architecture
contract; this `__init__` exists so submodules
(`trade_trace.console.pagination`, etc.) are importable from a
fresh install. Implementation modules are added per-bead under
the trade-trace-1kkv epic.
"""

from __future__ import annotations
