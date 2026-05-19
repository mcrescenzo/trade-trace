"""Shared security-test fixtures per trade-trace-hnwp (SIMP-018).

Two no-network shapes that live here so individual test modules don't
duplicate the socket-monkeypatch boilerplate:

- `no_socket_creation` (strict): replaces `socket.socket` with a raising
  callable, so any code that even constructs a socket fails the test.
  Use this when the test asserts the code path doesn't create sockets
  at all — e.g. the embeddings-off-by-default audit.

- `no_outbound_connect_or_dns` (granular): replaces
  `socket.socket.connect` and `socket.getaddrinfo` with raising stubs,
  so socket construction succeeds but actual outbound traffic raises.
  Use this when the test allows socket creation by libraries (in-process
  binding, etc.) and only asserts no outbound TCP/DNS leaves the host.
"""

from __future__ import annotations

import socket

import pytest


@pytest.fixture
def no_socket_creation(monkeypatch):
    """Replace `socket.socket` with a raising stub. Any attempt to create
    a socket raises `RuntimeError`. Local sqlite-only paths do not touch
    this surface, so they pass without sockets."""

    def _block(*args, **kwargs):
        raise RuntimeError("network access is disabled in this test")

    monkeypatch.setattr(socket, "socket", _block)
    return monkeypatch


@pytest.fixture
def no_outbound_connect_or_dns(monkeypatch):
    """Replace `socket.socket.connect` and `socket.getaddrinfo` with
    raising stubs so any outbound TCP or DNS attempt raises with a
    PRD §2.4.1-anchored AssertionError."""

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
