"""Tool-handler exception type. Raised inside handlers and turned into the
error envelope by the core dispatcher."""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.errors import ErrorCode


class ToolError(Exception):
    """Carries the stable error code + message + details from a handler."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}
