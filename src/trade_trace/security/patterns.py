r"""Secret-pattern regex registry per operability.md §6.3 / bead trade-trace-sy1.

Four built-in patterns ship in MVP. Each pattern carries a stable name
(used as ``details.pattern_kind`` in VALIDATION_ERROR envelopes and as
the substitution token in log redaction) and a compiled regex. Adding
new patterns at runtime via :func:`register` is non-breaking; tightening
or removing built-in patterns is a breaking change (requires a contract
version bump per contracts.md §8).

Built-in patterns:

- ``api_key``           : ``(sk-|pk_)[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}``
- ``slack_token``       : ``xox[abprs]-[A-Za-z0-9-]+``
- ``ethereum_address``  : ``0x[a-fA-F0-9]{40}``
- ``jwt``               : three base64url segments separated by ``.``

The registry is a process-global module-level dict. Tests that mutate
it (e.g. registering a custom pattern) should call :func:`reset_patterns`
in their teardown to restore the built-in set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class SecretMatch:
    """One detected secret-shape hit.

    Attributes:
        pattern_kind: the registered pattern name (e.g. ``"api_key"``).
        match: the full matched substring (kept short for log envelopes;
            never use in user-facing UI without re-redacting).
        match_offset: byte offset of the match inside the scanned text.
        length: byte length of the matched substring.
    """

    pattern_kind: str
    match: str
    match_offset: int
    length: int


class SecretPatternError(ValueError):
    """Raised when register() is called with an invalid name / regex."""


BUILTIN_PATTERNS: Final[dict[str, str]] = {
    "api_key": r"(sk-|pk_)[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}",
    "slack_token": r"xox[abprs]-[A-Za-z0-9-]+",
    "ethereum_address": r"0x[a-fA-F0-9]{40}",
    "jwt": r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
}
"""Built-in pattern source strings per operability.md §6.3. JWT regex
requires each base64url segment to be ≥8 chars to keep the false-positive
rate manageable on domain-style strings like `a.b.c`."""


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


_compiled: dict[str, re.Pattern[str]] = {}


def _initialize() -> None:
    """Compile built-in patterns. Called on module import and from
    `reset_patterns()`."""

    _compiled.clear()
    for name, source in BUILTIN_PATTERNS.items():
        _compiled[name] = re.compile(source)


_initialize()


def register(name: str, regex: str | re.Pattern[str]) -> None:
    """Register a custom secret pattern. Non-breaking when adding new
    pattern names; calling `register()` with an existing name replaces
    the pattern (breaking on tighten — caller must own the breakage).

    Args:
        name: lowercase kebab/snake identifier (regex
            `^[a-z][a-z0-9_]*$`). This name surfaces as
            `details.pattern_kind` in VALIDATION_ERROR envelopes.
        regex: a string or compiled `re.Pattern`. Compiled here; the
            registry stores the compiled object so subsequent scans are
            cheap.

    Raises:
        SecretPatternError: when the name is invalid or the regex fails
            to compile.
    """

    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise SecretPatternError(
            f"pattern name must match {_NAME_RE.pattern!r}; got {name!r}"
        )
    if isinstance(regex, re.Pattern):
        _compiled[name] = regex
        return
    try:
        _compiled[name] = re.compile(regex)
    except re.error as exc:
        raise SecretPatternError(
            f"pattern {name!r} regex failed to compile: {exc}"
        ) from exc


def reset_patterns() -> None:
    """Restore the registry to its built-in state. Used by tests after
    registering custom patterns."""

    _initialize()


def list_patterns() -> dict[str, str]:
    """Return a name→regex-source mapping for the active registry."""

    return {name: pattern.pattern for name, pattern in _compiled.items()}


def scan_text(text: str) -> list[SecretMatch]:
    """Return every secret-shaped substring in `text`. Each match is a
    `SecretMatch` carrying the pattern_kind, the literal match, byte
    offset, and length. Order: by `(match_offset, pattern_kind)` so
    callers get a deterministic walk; the same input yields the same
    list across runs."""

    if not isinstance(text, str) or not text:
        return []
    matches: list[SecretMatch] = []
    for name, pattern in _compiled.items():
        for m in pattern.finditer(text):
            matches.append(SecretMatch(
                pattern_kind=name,
                match=m.group(0),
                match_offset=m.start(),
                length=m.end() - m.start(),
            ))
    matches.sort(key=lambda r: (r.match_offset, r.pattern_kind))
    return matches


def redact_for_log(text: str) -> str:
    """Return `text` with every secret match replaced by the literal
    token `REDACTED-<pattern_kind>`. Used by the logging redactor so
    log files never carry the original secret bytes.

    Overlapping matches are resolved left-to-right; the leftmost match
    is redacted first, then the scan re-runs on the redacted string
    until no new matches surface (bounded by `len(text)` iterations).
    """

    if not isinstance(text, str) or not text:
        return text
    out = text
    seen: set[tuple[int, str]] = set()
    for _ in range(len(text) + 1):
        matches = scan_text(out)
        if not matches:
            return out
        first = matches[0]
        key = (first.match_offset, first.pattern_kind)
        if key in seen:
            # Shouldn't happen — defensive guard against a redactor that
            # re-introduces the same pattern shape (e.g. by emitting a
            # token that matches another registered pattern).
            return out
        seen.add(key)
        out = (
            out[: first.match_offset]
            + f"REDACTED-{first.pattern_kind}"
            + out[first.match_offset + first.length :]
        )
    return out
