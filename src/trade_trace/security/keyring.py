"""OS keyring wrapper for embedding-provider API keys.

The third-party ``keyring`` dependency is imported lazily so Trade Trace
keeps its default zero-secret, no-optional-dependency startup path. This
module intentionally exposes only value-in/value-out helpers and never logs
or persists secret material. Before any secret operation, the selected
``keyring`` backend is validated so insecure plaintext/null/fail fallback
backends cannot masquerade as ``os_keyring`` storage.
"""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.tools.errors import ToolError


class KeyringUnavailableError(RuntimeError):
    """Raised when the optional keyring backend cannot be imported or used."""


_INSECURE_BACKEND_MODULE_PREFIXES = (
    "keyrings.alt.",
    "keyring.backends.fail.",
    "keyring.backends.null.",
)
_INSECURE_BACKEND_NAME_FRAGMENTS = (
    "plaintext",
    "plain text",
    "chainerbackend",  # may silently fall through to keyrings.alt/plaintext
    "nullkeyring",
    "failkeyring",
)


def _backend() -> Any:
    try:
        import keyring  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - env-dependent
        raise KeyringUnavailableError(
            "optional dependency 'keyring' is required for API embeddings keys; "
            "install trade-trace[embeddings] and configure a secure OS keyring backend"
        ) from exc
    return _validated_backend(keyring)


def _validated_backend(keyring_module: Any) -> Any:
    """Return a keyring API object only when its selected backend is secure.

    Python's ``keyring`` package can select insecure fallbacks from
    ``keyrings.alt`` or null/fail backends. Those are not OS credential stores,
    so Trade Trace refuses them instead of reporting ``api_key_storage`` as
    ``os_keyring``. Tests may provide an in-memory fake backend only when it
    explicitly marks itself with ``trade_trace_test_secure_backend=True``.
    """

    selected = keyring_module.get_keyring() if hasattr(keyring_module, "get_keyring") else keyring_module
    if getattr(selected, "trade_trace_test_secure_backend", False):
        return keyring_module

    cls = selected.__class__
    module = str(getattr(cls, "__module__", "")).lower()
    name = str(getattr(cls, "__name__", "")).lower()
    text = f"{module}.{name} {selected!r}".lower()
    priority = getattr(selected, "priority", None)

    insecure = (
        any(module.startswith(prefix) for prefix in _INSECURE_BACKEND_MODULE_PREFIXES)
        or any(fragment in text for fragment in _INSECURE_BACKEND_NAME_FRAGMENTS)
        or priority is None
        or (isinstance(priority, (int, float)) and priority <= 0)
    )
    if insecure:
        raise KeyringUnavailableError(
            "insecure or unavailable keyring backend refused; configure a secure OS keyring backend"
        )
    return keyring_module


def _keyring_error(message: str, exc: Exception) -> ToolError:
    return ToolError(
        ErrorCode.STORAGE_ERROR,
        message,
        details={"secret_storage": "os_keyring", "reason": exc.__class__.__name__},
    )


def store_api_key(service: str, value: str) -> None:
    """Store ``value`` for ``service`` in the OS keyring.

    ``service`` is a non-secret account/service identifier such as
    ``trade-trace:embeddings:openai``. The secret ``value`` is deliberately
    not returned and must not be logged by callers.
    """

    if not isinstance(value, str) or not value:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "api key must be a non-empty string",
            details={"field": "api_key"},
        )
    try:
        _backend().set_password(service, "api_key", value)
    except Exception as exc:  # pragma: no cover - backend-dependent
        raise _keyring_error("failed to store API key in OS keyring", exc) from exc


def load_api_key(service: str) -> str | None:
    """Load the API key for ``service`` from the OS keyring, if present."""

    try:
        return _backend().get_password(service, "api_key")
    except Exception as exc:  # pragma: no cover - backend-dependent
        raise _keyring_error("failed to load API key from OS keyring", exc) from exc


def delete_api_key(service: str) -> None:
    """Delete the API key for ``service`` from the OS keyring if present."""

    try:
        backend = _backend()
        try:
            backend.delete_password(service, "api_key")
        except Exception as exc:
            # keyring raises backend-specific errors for absent secrets. Treat
            # absence as idempotent success only when a follow-up read is empty.
            if backend.get_password(service, "api_key") is not None:
                raise exc
    except Exception as exc:  # pragma: no cover - backend-dependent
        raise _keyring_error("failed to delete API key from OS keyring", exc) from exc
