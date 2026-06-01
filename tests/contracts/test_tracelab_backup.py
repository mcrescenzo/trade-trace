from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.tracelab.backup import prune_backups, run_backup_once
from trade_trace.core import dispatch
from trade_trace.mcp_server import mcp_call


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_backup_sidecar_requires_quiescence_window(initialized_home, tmp_path):
    try:
        run_backup_once(home=initialized_home, dest_root=tmp_path / "backups", quiescence_window="")
    except ValueError as exc:
        assert "quiescence_window" in str(exc)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("run_backup_once accepted an empty quiescence window")


def test_journal_backup_preview_without_confirm_writes_nothing(initialized_home, tmp_path):
    dest = tmp_path / "preview"

    env = dispatch(
        "journal.backup",
        {
            "home": str(initialized_home),
            "dest": str(dest),
            "idempotency_key": "test:backup-preview",
        },
        actor_id="agent:default",
    )

    assert env.ok, env
    assert env.data["preview_only"] is True
    assert not dest.exists()
    assert not (dest / "trade-trace.sqlite").exists()
    assert not (dest / "manifest.json").exists()


def test_backup_sidecar_confirm_writes_files_and_dispatch_trace(initialized_home, tmp_path, monkeypatch):
    trace_path = tmp_path / "dispatch.jsonl"
    monkeypatch.setenv("TRADE_TRACE_DISPATCH_TRACE", "1")
    monkeypatch.setenv("TRADE_TRACE_DISPATCH_TRACE_PATH", str(trace_path))

    result = run_backup_once(
        home=initialized_home,
        dest_root=tmp_path / "backups",
        quiescence_window="b12-paused-agents",
        keep=3,
        backup_name="journal-backup-0001",
    )

    assert result.ok, result.envelope
    assert result.envelope.data["preview_only"] is False
    assert (result.backup_dir / "trade-trace.sqlite").exists()
    assert (result.backup_dir / "manifest.json").exists()
    assert (result.backup_dir / "tracelab-backup.json").exists()
    marker = json.loads((result.backup_dir / "tracelab-backup.json").read_text())
    assert marker["quiescence_window"] == "b12-paused-agents"
    assert marker["tool"] == "journal.backup"
    assert marker["confirm"] is True

    trace_records = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert any(record["tool"] == "journal.backup" and record["ok"] is True for record in trace_records)


def test_backup_sidecar_quiesced_restore_round_trip_byte_identical(initialized_home, tmp_path):
    live_db = initialized_home / "trade-trace.sqlite"

    result = run_backup_once(
        home=initialized_home,
        dest_root=tmp_path / "backups",
        quiescence_window="b12-byte-identical-window",
        keep=2,
        backup_name="journal-backup-roundtrip",
    )
    assert result.ok, result.envelope

    restored_home = tmp_path / "restored-home"
    restore = mcp_call(
        "journal.restore",
        {
            "home": str(restored_home),
            "src": str(result.backup_dir),
            "_confirm": True,
            "idempotency_key": "test:restore-sidecar-roundtrip",
        },
        actor_id="agent:default",
    )

    assert restore.ok, restore
    assert _sha256(restored_home / "trade-trace.sqlite") == _sha256(live_db)


def test_backup_sidecar_retention_cap_enforced(initialized_home, tmp_path):
    dest_root = tmp_path / "backups"

    first = run_backup_once(
        home=initialized_home,
        dest_root=dest_root,
        quiescence_window="b12-retention-window",
        keep=2,
        backup_name="journal-backup-0001",
    )
    second = run_backup_once(
        home=initialized_home,
        dest_root=dest_root,
        quiescence_window="b12-retention-window",
        keep=2,
        backup_name="journal-backup-0002",
    )
    third = run_backup_once(
        home=initialized_home,
        dest_root=dest_root,
        quiescence_window="b12-retention-window",
        keep=2,
        backup_name="journal-backup-0003",
    )

    assert first.ok and second.ok and third.ok
    assert first.backup_dir in third.pruned
    assert not first.backup_dir.exists()
    assert second.backup_dir.exists()
    assert third.backup_dir.exists()
    assert sorted(p.name for p in dest_root.iterdir()) == ["journal-backup-0002", "journal-backup-0003"]


def test_prune_backups_ignores_non_sidecar_directories(tmp_path):
    dest_root = tmp_path / "backups"
    (dest_root / "journal-backup-0001").mkdir(parents=True)
    (dest_root / "journal-backup-0002").mkdir()
    (dest_root / "manual-keep").mkdir()

    pruned = prune_backups(dest_root, keep=1)

    assert len(pruned) == 1
    assert (dest_root / "manual-keep").exists()
    assert len(list(dest_root.glob("journal-backup-*"))) == 1
