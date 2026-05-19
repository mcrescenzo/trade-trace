"""Security primitives: secret-pattern scanning and log redaction.

Per operability.md §6.3 / §7 and bead trade-trace-sy1, the MVP ships four
secret-shape patterns and a write-time guard on user-supplied free-text
fields. Additions are non-breaking; tightening is breaking.
"""

from trade_trace.security.patterns import (
    BUILTIN_PATTERNS,
    SecretMatch,
    SecretPatternError,
    compiled_patterns,
    list_patterns,
    redact_for_log,
    register,
    reset_patterns,
    scan_text,
)

__all__ = [
    "BUILTIN_PATTERNS",
    "SecretMatch",
    "SecretPatternError",
    "compiled_patterns",
    "list_patterns",
    "redact_for_log",
    "register",
    "reset_patterns",
    "scan_text",
]
