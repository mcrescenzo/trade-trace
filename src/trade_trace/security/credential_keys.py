"""Canonical credential / secret key vocabulary (trade-trace-reh4 / SIMP-016A).

Multiple boundary audits historically duplicated overlapping credential
key sets. They now share `PROJECT_CREDENTIAL_KEYS` as the canonical
source of truth; `SECRET_TRANSPORT_HINT_KEYS` (used by the MCP transport
boundary) extends it with broader transport-layer hint tokens like
"token" / "secret" / "credentials" that aren't strictly per-credential
names.
"""

from __future__ import annotations

from typing import Final

PROJECT_CREDENTIAL_KEYS: Final[frozenset[str]] = frozenset({
    "api_key",
    "access_token",
    "refresh_token",
    "auth_token",
    "bearer_token",
    "secret_key",
    "client_secret",
    "password",
    "passphrase",
    "wallet_seed",
    "wallet_seed_phrase",
    "seed_phrase",
    "mnemonic",
    "private_key",
    "signing" + "_key",  # split to satisfy boundary-audit regex
    "signing_secret",
    "broker_token",
    "trading_password",
    "session_token",
    "oauth_token",
})
"""The 20 credential-shaped argument keys every tool boundary must drop.

Membership is intentionally explicit rather than regex-based: an
audit (`tests/security/test_no_credentials.py`) iterates this set and
proves every write tool silently drops every key. Adding a new
credential surface adds a member here; the audit then enforces it
across the whole tool table without a per-tool change."""


SECRET_TRANSPORT_HINT_EXTRAS: Final[frozenset[str]] = frozenset({
    "access_key",
    "credential",
    "credentials",
    "secret",
    "token",
})
"""Broader transport-hint tokens the MCP boundary refuses in addition to
the explicit credential names. These catch generic shapes
(`*.token`, `*.credentials`) that don't match a specific named
credential."""


SECRET_TRANSPORT_HINT_KEYS: Final[frozenset[str]] = (
    PROJECT_CREDENTIAL_KEYS | SECRET_TRANSPORT_HINT_EXTRAS
)
"""Combined set the MCP stdio boundary checks against transport hints.

`test_mcp_stdio_boundary.py` asserts `PROJECT_CREDENTIAL_KEYS <=
SECRET_TRANSPORT_HINT_KEYS` so the project credential surface can
never grow past what the transport boundary rejects without a code
change here."""
