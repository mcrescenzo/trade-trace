"""File-permission audit per beads trade-trace-4qf, trade-trace-ljl9,
and security.md §4 + §6.3.

On POSIX platforms, every file the journal owns is created with mode
0600 and every directory it owns with mode 0700, regardless of the
caller's umask. Windows is documented as best-effort: the tests skip
there.

The bead trade-trace-ljl9 extends the original DB+JSONL coverage to:
- the journal home and its `export/jsonl/YYYY/MM/DD` subdirectories
- the `.jsonl.tmp` temp file the exporter writes before the atomic
  rename
- the `<db>-wal` and `<db>-shm` neighbors SQLite WAL mode creates
- the output of `journal.backup` (DB copy, manifest, and the copied
  JSONL tree) plus its dest directory tree
- behavior under a permissive umask (0o000) so the test would fail
  if the implementation relied on umask masking instead of explicit
  chmod / O_CREAT mode bits.

Directory-leakage stance: the date-bucketed export tree
(`export/jsonl/YYYY/MM/DD/`) is chmodded to 0700 after each write so
a `ls $TRADE_TRACE_HOME` from another user reveals nothing about
event timestamps or counts. The journal `$HOME` parent is chmodded
to 0700 too. Higher directories (e.g. `$HOME` itself) are the
operator's responsibility per the operability docs.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import cast

import pytest

from trade_trace.events import EventWriter
from trade_trace.exporter import drain_outbox
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="POSIX permission bits not enforceable on Windows",
)


@pytest.fixture
def permissive_umask():
    """Run the test under umask 0o000 so the implementation cannot rely
    on the default umask 0o022 masking out the group/world bits — only
    explicit chmod / O_CREAT mode bits keep the contract."""

    old = os.umask(0o000)
    try:
        yield
    finally:
        os.umask(old)


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


# -- DB file ------------------------------------------------------


def test_sqlite_db_created_with_0600(tmp_path: Path, permissive_umask):
    home = tmp_path / "home"
    db = open_database(db_path(home))
    try:
        apply_pending_migrations(db.connection)
    finally:
        db.close()
    assert _mode(db_path(home)) == 0o600


def test_sqlite_wal_and_shm_files_pinned_to_0600(
    tmp_path: Path, permissive_umask,
):
    """SQLite creates `<db>-wal` and `<db>-shm` neighbors lazily on
    the first write. The storage layer pins them to 0600 on close()
    so a long-running process cannot leak transient state under a
    permissive umask (bead trade-trace-ljl9)."""

    home = tmp_path / "home"
    db = open_database(db_path(home))
    try:
        apply_pending_migrations(db.connection)
        # Force a checkpoint so the WAL file is materialized.
        db.connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
    finally:
        db.close()

    wal = db_path(home).with_name(db_path(home).name + "-wal")
    shm = db_path(home).with_name(db_path(home).name + "-shm")
    for sibling in (wal, shm):
        if sibling.exists():
            assert _mode(sibling) == 0o600, (
                f"{sibling.name} mode {oct(_mode(sibling))} leaks via umask"
            )


# -- Directory tree ---------------------------------------------


def test_journal_home_directory_is_0700(tmp_path: Path, permissive_umask):
    """The journal-home parent created by open_database is chmodded
    to 0700 so a `ls $TRADE_TRACE_HOME/..` from another user reveals
    nothing about the journal's contents (bead trade-trace-ljl9)."""

    home = tmp_path / "home"
    db = open_database(db_path(home))
    try:
        apply_pending_migrations(db.connection)
    finally:
        db.close()
    # db_path(home) lives under home/db/; the immediate parent of the
    # DB file is the one open_database tightens.
    parent = db_path(home).parent
    assert _mode(parent) == 0o700


def test_open_db_for_args_creates_home_with_0700(
    tmp_path: Path, permissive_umask,
):
    """`open_db_for_args` lazily creates the journal home before
    discovering the DB is not initialized. The fresh directory must be
    chmodded to 0700 immediately so a permissive umask cannot leak a
    transient world-readable directory between `mkdir` and the
    journal-not-initialized error (bead trade-trace-pqex).
    """

    from trade_trace.tools._helpers import open_db_for_args
    from trade_trace.tools.errors import ToolError

    home = tmp_path / "uninitialized-home"
    with pytest.raises(ToolError) as info:
        open_db_for_args({"home": str(home)})
    assert info.value.code.value == "STORAGE_ERROR"
    assert home.exists()
    assert _mode(home) == 0o700


# -- Exported JSONL: tmp + final + dir bucket -------------------


def _drive_one_event(home: Path) -> Path:
    db = open_database(db_path(home))
    try:
        apply_pending_migrations(db.connection)
        writer = EventWriter(db.connection)
        writer.set_outbox_jsonl_enabled()
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload={
                "instrument_id": "i_1", "type": "skip",
                "reason": "perm test",
            },
            actor_id="agent:default",
            idempotency_key="perm-1",
        )
        result = drain_outbox(db.connection, home)
    finally:
        db.close()
    assert len(result.exported_files) == 1
    return result.exported_files[0]


def test_exported_jsonl_file_created_with_0600(
    tmp_path: Path, permissive_umask,
):
    home = tmp_path / "home"
    exported = _drive_one_event(home)
    assert _mode(exported) == 0o600


def test_exported_jsonl_date_bucket_directories_are_0700(
    tmp_path: Path, permissive_umask,
):
    """The exporter tightens `export/jsonl/YYYY/MM/DD/` so directory
    listings do not leak event filenames (bead trade-trace-ljl9)."""

    home = tmp_path / "home"
    exported = _drive_one_event(home)
    # exported lives under home/export/jsonl/YYYY/MM/DD/<file>
    day_dir = exported.parent
    month_dir = day_dir.parent
    year_dir = month_dir.parent
    for d in (day_dir, month_dir, year_dir):
        assert _mode(d) == 0o700, (
            f"{d.name} mode {oct(_mode(d))} leaks event timestamps"
        )


def test_exporter_tmp_file_is_created_with_0600_from_the_start(
    tmp_path: Path, permissive_umask,
):
    """The exporter writes a `.jsonl.tmp` and then renames. The tmp
    file must be created with mode 0600 so a permissive umask cannot
    leave a transient world-readable file on disk for the duration
    of the write (bead trade-trace-ljl9).

    We check by intercepting the rename: capture the tmp path before
    it's renamed and assert its mode is 0o600.
    """

    import trade_trace.exporter as exporter_mod

    captured: dict[str, object] = {}
    original_replace = os.replace

    def _replace_capture(src, dst):
        captured["tmp"] = Path(src)
        captured["tmp_mode"] = _mode(Path(src))
        return original_replace(src, dst)

    home = tmp_path / "home"
    db = open_database(db_path(home))
    try:
        apply_pending_migrations(db.connection)
        writer = EventWriter(db.connection)
        writer.set_outbox_jsonl_enabled()
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_tmp",
            payload={"instrument_id": "i_1", "type": "skip"},
            actor_id="agent:default",
            idempotency_key="perm-tmp",
        )
        # Patch the symbol the exporter module sees (it imported os).
        monkey_setattr = exporter_mod.os
        original = monkey_setattr.replace
        monkey_setattr.replace = _replace_capture  # type: ignore[assignment]
        try:
            drain_outbox(db.connection, home)
        finally:
            monkey_setattr.replace = original  # type: ignore[method-assign]
    finally:
        db.close()

    assert "tmp_mode" in captured, "tmp file was never observed"
    assert captured["tmp_mode"] == 0o600, (
        f"tmp file mode {oct(cast('int', captured['tmp_mode']))} would leak under "
        "permissive umask"
    )


# -- Backup output ---------------------------------------------


def test_journal_backup_outputs_are_0600_with_0700_dir(
    tmp_path: Path, permissive_umask,
):
    """`journal.backup` copies the DB plus the JSONL tree into a
    destination directory and writes a manifest. Every file and
    directory it creates must be locked down to 0600 / 0700
    regardless of umask (bead trade-trace-ljl9)."""

    home = tmp_path / "home"
    # Seed a journal with one drained event so the backup has both a
    # DB and a JSONL file to handle.
    _drive_one_event(home)

    dest = tmp_path / "backup-dest"
    env = mcp_call("journal.backup", {
        "home": str(home), "dest": str(dest), "_confirm": True,
    })
    assert env.ok, env

    # The destination directory itself is 0700.
    assert _mode(dest) == 0o700

    # Every regular file in the backup tree is 0600.
    for child in dest.rglob("*"):
        if child.is_file():
            assert _mode(child) == 0o600, (
                f"backup leaked {child.relative_to(dest)}: "
                f"mode {oct(_mode(child))}"
            )
        elif child.is_dir():
            assert _mode(child) == 0o700, (
                f"backup dir leaked {child.relative_to(dest)}: "
                f"mode {oct(_mode(child))}"
            )


def test_journal_restore_tightens_permissive_backup_modes(
    tmp_path: Path, permissive_umask,
):
    """`journal.restore` must not preserve permissive source modes.

    `shutil.copy2` preserves source permission bits on POSIX, so a backup tree
    copied through a permissive medium (0644 files / 0755 dirs) would otherwise
    restore world-readable journal data. Restore re-pins journal-owned regular
    files to 0600 and directories under TRADE_TRACE_HOME to 0700.
    """

    home = tmp_path / "home"
    _drive_one_event(home)

    backup = tmp_path / "backup-src"
    env = mcp_call("journal.backup", {
        "home": str(home), "dest": str(backup), "_confirm": True,
    })
    assert env.ok, env

    # Simulate a permissive backup/source transport before restore.
    os.chmod(backup, 0o755)
    for child in backup.rglob("*"):
        if child.is_dir():
            os.chmod(child, 0o755)
        elif child.is_file():
            os.chmod(child, 0o644)

    restored_home = tmp_path / "restored-home"
    env = mcp_call("journal.restore", {
        "home": str(restored_home), "src": str(backup), "_confirm": True,
    })
    assert env.ok, env

    assert _mode(restored_home) == 0o700
    for child in restored_home.rglob("*"):
        if child.is_file():
            assert _mode(child) == 0o600, (
                f"restore leaked {child.relative_to(restored_home)}: "
                f"mode {oct(_mode(child))}"
            )
        elif child.is_dir():
            assert _mode(child) == 0o700, (
                f"restore dir leaked {child.relative_to(restored_home)}: "
                f"mode {oct(_mode(child))}"
            )
