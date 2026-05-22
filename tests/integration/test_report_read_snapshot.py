"""trade-trace-d8lu: multi-query report compositions used to issue several
independent SELECTs on the same connection without an explicit BEGIN. In
WAL mode each SELECT picks up the latest committed state, so a concurrent
writer could land inconsistent rows in the middle of a report (decision
counts disagreeing with strategy health counts, for example).

The fix is `storage.database.read_snapshot`, a small context manager that
opens a deferred read transaction and commits it on exit. This module
covers the contract directly and also pins it inside report.bootstrap so
the same snapshot covers every sub-report it composes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.mcp_server import mcp_call
from trade_trace.reports.bootstrap import compose_bootstrap_packet
from trade_trace.storage.database import read_snapshot
from trade_trace.storage.paths import db_path


def _init_home(tmp_path) -> Path:
    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}).model_dump(mode="json")["ok"] is True
    return home


def test_read_snapshot_pins_state_against_external_commit(tmp_path):
    home = _init_home(tmp_path)
    reader = sqlite3.connect(db_path(home))
    writer = sqlite3.connect(db_path(home))
    reader.execute("PRAGMA busy_timeout = 5000")
    writer.execute("PRAGMA busy_timeout = 5000")
    try:
        before = reader.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
        with read_snapshot(reader):
            first = reader.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
            assert first == before
            writer.execute(
                "INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("vsnap-1", "snap", "manual", "{}", "2026-01-01T00:00:00Z", "actor"),
            )
            writer.commit()
            # Inside the snapshot the second SELECT must match the first.
            second = reader.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
            assert second == first, (second, first)
        # Outside the snapshot the new row becomes visible.
        third = reader.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
        assert third == first + 1
    finally:
        reader.close()
        writer.close()


def test_read_snapshot_is_a_noop_inside_existing_transaction(tmp_path):
    home = _init_home(tmp_path)
    conn = sqlite3.connect(db_path(home))
    try:
        conn.execute("BEGIN")
        assert conn.in_transaction is True
        with read_snapshot(conn):
            # No new transaction opened; the helper yields the same connection.
            assert conn.in_transaction is True
        # The outer BEGIN is still in flight — the helper did not commit it.
        assert conn.in_transaction is True
        conn.commit()
    finally:
        conn.close()


def test_compose_bootstrap_packet_uses_read_snapshot_so_writes_during_composition_are_invisible(tmp_path):
    """End-to-end proof: while compose_bootstrap_packet is mid-composition,
    a separate writer commits a new venue/instrument/decision. None of that
    should appear in the assembled packet, since the packet's snapshot was
    pinned at the first SELECT after entering the read_snapshot block."""
    home = _init_home(tmp_path)
    _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})

    writer = sqlite3.connect(db_path(home))
    writer.execute("PRAGMA busy_timeout = 5000")

    real_reader = sqlite3.connect(db_path(home))
    real_reader.execute("PRAGMA busy_timeout = 5000")

    sneaky_inserted = {"done": False}

    class _SneakConnection:
        """Mimics sqlite3.Connection at the surface area report code touches.
        The first SELECT triggers a write on a separate connection so the
        snapshot guard has something to protect against."""

        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner
            self._calls = 0

        def execute(self, sql, *args, **kwargs):
            self._calls += 1
            lowered = sql.lstrip().lower()
            if (
                self._calls >= 2
                and lowered.startswith("select")
                and not sneaky_inserted["done"]
            ):
                writer.execute(
                    "INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("vsnap-bootstrap", "sneak", "manual", "{}", "2026-01-01T00:00:00Z", "actor"),
                )
                writer.commit()
                sneaky_inserted["done"] = True
            return self._inner.execute(sql, *args, **kwargs)

        def commit(self):
            return self._inner.commit()

        @property
        def in_transaction(self):
            return self._inner.in_transaction

    reader = _SneakConnection(real_reader)

    try:
        packet = compose_bootstrap_packet(
            reader,  # type: ignore[arg-type]
            as_of="2026-01-20T00:00:00Z",
            raw_filter={},
        )
    finally:
        real_reader.close()
        writer.close()

    assert sneaky_inserted["done"] is True, "the writer should have committed inside the report body"
    # The sneak venue should not appear anywhere in the packet — every
    # sub-report SELECT runs against the snapshot pinned at the BEGIN.
    import json
    text = json.dumps(packet)
    assert "vsnap-bootstrap" not in text, text
