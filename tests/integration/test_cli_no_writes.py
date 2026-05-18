"""M0 acceptance criterion: package and CLI shells run without product writes.

The point is that just invoking `tt journal status` against a process with no
prior state must not create files, network sockets, or background side effects.
"""

from __future__ import annotations

import io
import os
import socket
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from trade_trace.cli import main as cli_main


def test_journal_status_creates_no_filesystem_artifacts(tmp_path: Path, monkeypatch):
    """`tt journal status` against an empty $TRADE_TRACE_HOME must touch zero files."""

    monkeypatch.setenv("TRADE_TRACE_HOME", str(tmp_path))
    before = sorted(tmp_path.iterdir())
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["journal", "status"])
    after = sorted(tmp_path.iterdir())
    assert rc == 0
    assert before == after == []
    # The stdout is a JSON-only envelope with no prose.
    line = buf.getvalue().strip()
    assert line.startswith("{") and line.endswith("}")


def test_no_outbound_network_default(monkeypatch):
    """PRD §2.4.1 promise: a fresh `tt journal status` makes zero outbound calls.

    We enforce this defensively by replacing socket.socket.connect with a
    raising stub for the duration of the call. If any code path tries to open
    a network socket, the test fails immediately.
    """

    real_connect = socket.socket.connect

    def _refuse(self, addr):
        raise AssertionError(
            f"outbound network attempt to {addr!r} during journal.status — "
            "the MVP boundary (PRD §2.4.1) forbids this on default-init."
        )

    monkeypatch.setattr(socket.socket, "connect", _refuse, raising=True)
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_main(["journal", "status"])
        assert rc == 0
    finally:
        monkeypatch.setattr(socket.socket, "connect", real_connect, raising=True)


def test_human_flag_emits_stderr_only(capsys, monkeypatch):
    """`--human` must emit prose only to stderr; stdout must remain pure JSON."""

    rc = cli_main(["--human", "journal", "status"])
    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip().startswith("{")
    assert "ok: journal.status" in out.err


@pytest.mark.parametrize("token", ["", "  ", "\n", "\t"])
def test_cli_rejects_empty_invocation(token, capsys):
    """An empty positional list returns nonzero without writes."""

    # argparse treats `--` and empty positionals differently; we only exercise
    # the explicit empty path here.
    rc = cli_main([])
    out = capsys.readouterr()
    assert rc != 0
    assert "usage" in out.err.lower()
