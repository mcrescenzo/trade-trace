"""Console security headers, CSP, and network-isolation guarantees
(trade-trace-1kkv.13).

The Console runs on `localhost` and only ever serves vendored
assets. The headers here lock that posture into every HTTP
response, and the helper functions are also called directly from
tests so we don't have to spin up FastAPI to verify the contract.

Per `docs/architecture/console.md` §6 + §7 + threat model:

- CSP forbids `unsafe-inline` and `unsafe-eval`; sources are
  `'self'` only — no external CDNs.
- `X-Frame-Options: DENY` — Console is not embeddable.
- `X-Content-Type-Options: nosniff`.
- `Referrer-Policy: no-referrer` — no leakage of internal URLs.
- `Permissions-Policy` shuts down camera, microphone, geolocation,
  payment, USB, and `interest-cohort` (FLoC) since Console never
  needs any of them.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "font-src 'self'; "
    "img-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'none'; "
    "object-src 'none'; "
    "base-uri 'none'"
)


PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), payment=(), "
    "usb=(), interest-cohort=()"
)


SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CSP,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": PERMISSIONS_POLICY,
    # Cache-busting on the read endpoints so a stale Overview page
    # never lingers behind a browser cache.
    "Cache-Control": "no-store",
}


def apply_security_headers(headers: dict[str, str] | Any) -> None:
    """Mutate a mapping-like headers object in place. Supports
    `dict` and Starlette's `MutableHeaders` since both behave
    identically for `__setitem__`."""

    for name, value in SECURITY_HEADERS.items():
        headers[name] = value


def csp_forbids(directive: str, expression: str) -> bool:
    """Return True when `expression` is *not* in the named CSP
    directive — i.e., the CSP forbids it. Used by smoke tests."""

    for clause in CSP.split(";"):
        clause = clause.strip()
        if clause.startswith(directive):
            return expression not in clause
    # If the directive isn't named, the policy doesn't allow it.
    return True


def external_resources_in_markup(markup: str) -> list[str]:
    """Return external URLs referenced from built markup or CSS.

    The shipped Console must be fully self-contained. The CSP would
    block remote loads anyway, but this gives a faster feedback loop
    during development and release checks.
    """

    findings: list[str] = []
    for prefix in ("http://", "https://", "//"):
        idx = 0
        while True:
            idx = markup.find(prefix, idx)
            if idx == -1:
                break
            # Slice a reasonable chunk so the test output is
            # actionable (paths get truncated to whitespace).
            end = idx
            while end < len(markup) and markup[end] not in (
                " ", "\"", "'", "<", ">", "\n",
            ):
                end += 1
            findings.append(markup[idx:end])
            idx = end
    return findings


class OutboundConnectionAttempted(AssertionError):
    """Raised when a test fixture detects a non-loopback connect
    attempt. The Console must never reach outside the loopback
    interface; the test harness asserts that explicitly."""


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})


def is_loopback_address(address: Any) -> bool:
    """Return True when a getaddrinfo/connect target points at the
    loopback interface."""

    if isinstance(address, tuple) and address:
        host = address[0]
    else:
        host = address
    if not isinstance(host, str):
        return False
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


def iter_security_header_pairs() -> Iterable[tuple[str, str]]:
    """Stable ordering for tests that want to verify the full set
    appears on a response."""

    return SECURITY_HEADERS.items()
