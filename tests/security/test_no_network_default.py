"""PRD §2.4.1 / VISION §safety promise: MVP makes no outbound network calls
on a fresh `journal.init`. Air-gappable on first run.

The test monkeypatches `socket.socket.connect` with a raising stub for the
duration of the call, so any code path attempting an outbound TCP connection
fails the test immediately. DNS lookups via `socket.getaddrinfo` are similarly
caught.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call


@pytest.fixture
def no_network(monkeypatch):
    """Replace socket primitives so any outbound attempt raises immediately."""

    def _refuse_connect(self, addr):  # noqa: ARG001
        raise AssertionError(
            f"outbound TCP connect to {addr!r} during operation that "
            "MVP guarantees as air-gapped (PRD §2.4.1)."
        )

    def _refuse_getaddrinfo(*args, **kwargs):  # noqa: ARG001
        raise AssertionError(
            f"outbound DNS getaddrinfo({args[0]!r}) during operation that "
            "MVP guarantees as air-gapped (PRD §2.4.1)."
        )

    monkeypatch.setattr(socket.socket, "connect", _refuse_connect, raising=True)
    monkeypatch.setattr(socket, "getaddrinfo", _refuse_getaddrinfo, raising=True)
    return monkeypatch


def test_journal_init_no_network(no_network, tmp_path: Path):
    """`journal.init` on a fresh home must not open a socket."""

    env = mcp_call("journal.init", {"home": str(tmp_path / "home")})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    assert body["data"]["outbound_network_active"] is False


def test_journal_status_no_network(no_network, tmp_path: Path):
    """`journal.status` against an uninitialized home must not open a socket."""

    env = mcp_call("journal.status", {"home": str(tmp_path / "home")})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    assert body["data"]["outbound_network_active"] is False


def test_journal_schema_no_network(no_network):
    """`journal.schema` is in-process Pydantic; no network ever."""

    env = mcp_call("journal.schema", {})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True


def test_init_then_status_then_reinit_no_network(no_network, tmp_path: Path):
    """A representative idempotent loop must not open a socket."""

    home = str(tmp_path / "home")
    for tool in ("journal.init", "journal.status", "journal.init", "journal.status"):
        env = mcp_call(tool, {"home": home})
        body = env.model_dump(mode="json", exclude_none=True)
        assert body["ok"] is True, body
