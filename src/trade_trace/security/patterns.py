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
- ``ethereum_address``  : ``\b0x[a-fA-F0-9]{40}\b`` (word-bounded; longer hex blobs like Polymarket condition ids, 0x+64 hex, are not Ethereum addresses — see trade-trace-aqpf)
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
    "ethereum_address": r"\b0x[a-fA-F0-9]{40}\b",
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


MAX_REGEX_SOURCE_LENGTH: int = 1000
"""Per bead trade-trace-14iy / DEBT-041: cap the source length of a
caller-registered regex so a pathological pattern can't be smuggled
through the `register()` extension point. The cap is large enough for
real secret-detection patterns (the built-ins are <100 chars each)
but small enough to keep compile time bounded."""

MAX_SCAN_INPUT_BYTES: int = 1_000_000
"""Cap the input length `scan_text` and `redact_for_log` will scan.
Beyond this size, only the first MAX_SCAN_INPUT_BYTES are scanned;
this keeps the entire pattern set's combined CPU cost bounded even
if an agent pastes a multi-megabyte blob into a thesis body. Inputs
this long are out-of-policy elsewhere (blob caps in
operability.md §8), but the scan layer doesn't trust that."""


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
        SecretPatternError: when the name is invalid, the regex fails
            to compile, or the regex source exceeds
            `MAX_REGEX_SOURCE_LENGTH` (a coarse ReDoS guard per bead
            trade-trace-14iy).
    """

    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise SecretPatternError(
            f"pattern name must match {_NAME_RE.pattern!r}; got {name!r}"
        )
    if isinstance(regex, re.Pattern):
        if len(regex.pattern) > MAX_REGEX_SOURCE_LENGTH:
            raise SecretPatternError(
                f"pattern {name!r} regex source exceeds "
                f"MAX_REGEX_SOURCE_LENGTH ({MAX_REGEX_SOURCE_LENGTH}); "
                "trim the pattern or split into multiple registrations "
                "(bead trade-trace-14iy ReDoS guard)"
            )
        _compiled[name] = regex
        return
    if len(regex) > MAX_REGEX_SOURCE_LENGTH:
        raise SecretPatternError(
            f"pattern {name!r} regex source exceeds "
            f"MAX_REGEX_SOURCE_LENGTH ({MAX_REGEX_SOURCE_LENGTH}); "
            "trim the pattern or split into multiple registrations "
            "(bead trade-trace-14iy ReDoS guard)"
        )
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
    list across runs.

    Per bead trade-trace-14iy / DEBT-041: inputs longer than
    `MAX_SCAN_INPUT_BYTES` are truncated to that prefix before
    scanning so a pathological multi-megabyte blob can't cause the
    pattern set to dominate CPU. The truncation is silent — the
    write-time blob caps in operability.md §8 are the user-facing
    bound; this is a defense-in-depth layer behind them.
    """

    if not isinstance(text, str) or not text:
        return []
    if len(text) > MAX_SCAN_INPUT_BYTES:
        text = text[:MAX_SCAN_INPUT_BYTES]
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


_REDACTION_TRUNCATION_MARKER = "[REDACTED-LOG-TRUNCATED-OVER-MAX_SCAN_INPUT_BYTES]"


def redact_for_log(text: str) -> str:
    """Return `text` with every secret match replaced by the literal
    token `REDACTED-<pattern_kind>`. Used by the logging redactor so
    log files never carry the original secret bytes.

    Overlapping matches are resolved left-to-right; the leftmost match
    is redacted first, then the scan re-runs on the redacted string
    until no new matches surface (bounded by `len(text)` iterations).

    Per bead trade-trace-8n98: when `text` is longer than
    `MAX_SCAN_INPUT_BYTES`, the un-scanned tail is replaced with a
    marker before redaction runs. The scanner caps input length as a
    ReDoS/CPU defense (see `scan_text`), but for log redaction we MUST
    fail closed — without the truncation, a secret in the tail would
    pass through verbatim into a 'redacted' log.
    """

    if not isinstance(text, str) or not text:
        return text
    if len(text) > MAX_SCAN_INPUT_BYTES:
        out = text[:MAX_SCAN_INPUT_BYTES] + _REDACTION_TRUNCATION_MARKER
    else:
        out = text
    seen: set[tuple[int, str]] = set()
    for _ in range(len(out) + 1):
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
