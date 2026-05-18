"""Embeddings air-gap default per bead trade-trace-ubp acceptance #1.

`Vectors OFF by default. journal.init produces zero outbound network
calls`. The semantic-strategy / sqlite-vec / bge-small download path
is deferred to a follow-up bead (see ubp close reason); the default
must remain off until the follow-up lands.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call


@pytest.fixture
def no_network(monkeypatch):
    """Replace `socket.socket` with a raising stub so any outbound DNS
    or TCP attempt during the test surfaces as an exception. Local
    sqlite-only paths do not touch this surface."""

    def _block(*args, **kwargs):
        raise RuntimeError("network access is disabled in this test")

    monkeypatch.setattr(socket, "socket", _block)


def test_journal_init_with_no_network_succeeds(no_network, tmp_path: Path):
    home = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(home)})
    assert env.ok
    assert env.data["embeddings_provider"] == "none"
    assert env.data["outbound_network_active"] is False


def test_journal_status_reports_none_default(no_network, tmp_path: Path):
    home = tmp_path / "home"
    mcp_call("journal.init", {"home": str(home)})
    env = mcp_call("journal.status", {"home": str(home)})
    assert env.ok
    assert env.data["embeddings_provider"] == "none"


def test_memory_retain_and_recall_offline(no_network, tmp_path: Path):
    """The full retain → recall round-trip works with the socket layer
    disabled, confirming the BM25 + temporal + graph strategies are
    pure-SQL and require no embeddings infrastructure (acceptance #1)."""

    home = tmp_path / "home"
    mcp_call("journal.init", {"home": str(home)})
    retain = mcp_call("memory.retain", {
        "home": str(home),
        "node_type": "observation",
        "body": "offline reasoning still finds this row",
        "idempotency_key": "00000000-0000-4000-8000-offline-test1",
    })
    assert retain.ok
    recall = mcp_call("memory.recall", {
        "home": str(home), "query": "offline reasoning", "k": 5,
    })
    assert recall.ok
    assert any(it["id"] == retain.data["id"] for it in recall.data["items"])
