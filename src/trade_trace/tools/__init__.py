"""Tool handlers shared by CLI and MCP transports.

Each handler returns a dict that becomes the `data` payload of a success
envelope. Handlers that fail raise a `ToolError` (envelope-encoded into an
error envelope by the core).

Note: imports are kept thin to avoid circular references. Heavyweight
modules (`ledger`, `events.log`) are loaded by the dispatcher's
`build_registry()` and by callers that need them directly.
"""

from trade_trace.tools.errors import ToolError

__all__ = ["ToolError"]
