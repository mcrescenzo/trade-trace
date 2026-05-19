"""File-permission audit per bead trade-trace-4qf and security.md §4.

On POSIX platforms, every file the journal owns is created with mode
0600. Windows is documented as best-effort: the tests skip there.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from trade_trace.events import EventWriter
from trade_trace.exporter import drain_outbox
from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="POSIX permission bits not enforceable on Windows",
)


def test_sqlite_db_created_with_0600(tmp_path: Path):
    home = tmp_path / "home"
    db = open_database(db_path(home))
    try:
        apply_pending_migrations(db.connection)
    finally:
        db.close()
    mode = stat.S_IMODE(os.stat(db_path(home)).st_mode)
    assert mode == 0o600, f"expected 0o600 on the SQLite DB; got {oct(mode)}"


def test_exported_jsonl_file_created_with_0600(tmp_path: Path):
    home = tmp_path / "home"
    db = open_database(db_path(home))
    try:
        apply_pending_migrations(db.connection)
        writer = EventWriter(db.connection)
        writer.set_outbox_jsonl_enabled()
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload={"instrument_id": "i_1", "type": "skip", "reason": "perm test"},
            actor_id="agent:default",
            idempotency_key="perm-1",
        )
        result = drain_outbox(db.connection, home)
    finally:
        db.close()

    assert len(result.exported_files) == 1
    exported = result.exported_files[0]
    mode = stat.S_IMODE(os.stat(exported).st_mode)
    assert mode == 0o600, f"expected 0o600 on exported JSONL; got {oct(mode)}"
