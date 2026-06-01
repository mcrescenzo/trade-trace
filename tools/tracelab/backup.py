"""Scheduled tracelab journal backup sidecar.

This module intentionally calls the public Trade Trace dispatch surface for
``journal.backup`` instead of copying files itself.  The underlying backup tool
checkpoints WAL then copies the DB file, so callers must run this one-shot only
inside a B12 quiescence window (agents/feeders paused).
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trade_trace.core import ErrorEnvelope, SuccessEnvelope, dispatch

DEFAULT_PREFIX = "journal-backup"
DEFAULT_ACTOR_ID = "system:tracelab-backup-sidecar"


@dataclass(frozen=True)
class BackupSidecarResult:
    """Result returned by :func:`run_backup_once`."""

    backup_dir: Path
    envelope: SuccessEnvelope | ErrorEnvelope
    pruned: tuple[Path, ...]
    quiescence_window: str

    @property
    def ok(self) -> bool:
        return self.envelope.ok


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _backup_dirs(dest_root: Path, prefix: str) -> list[Path]:
    if not dest_root.exists():
        return []
    return sorted(
        (p for p in dest_root.iterdir() if p.is_dir() and p.name.startswith(f"{prefix}-")),
        key=lambda p: (p.stat().st_mtime_ns, p.name),
        reverse=True,
    )


def prune_backups(dest_root: Path, *, keep: int, prefix: str = DEFAULT_PREFIX) -> list[Path]:
    """Prune old sidecar-created backups under ``dest_root``.

    Only directories named ``<prefix>-*`` are eligible; arbitrary directories in
    the destination root are never touched.
    """

    if keep < 1:
        raise ValueError("keep must be >= 1")
    pruned: list[Path] = []
    for old in _backup_dirs(dest_root, prefix)[keep:]:
        shutil.rmtree(old)
        pruned.append(old)
    return pruned


def run_backup_once(
    *,
    home: str | Path,
    dest_root: str | Path,
    quiescence_window: str,
    keep: int = 7,
    prefix: str = DEFAULT_PREFIX,
    actor_id: str = DEFAULT_ACTOR_ID,
    idempotency_key: str | None = None,
    backup_name: str | None = None,
) -> BackupSidecarResult:
    """Run one confirmed journal backup during a declared quiescence window.

    ``quiescence_window`` is required by design: this sidecar does not infer or
    orchestrate B12 scheduling.  B11/B12 callers should invoke it only after
    pausing agents and feeders.  The value is recorded in the backup directory
    and passed through the dispatch args for traceability.
    """

    if not quiescence_window or not quiescence_window.strip():
        raise ValueError("quiescence_window is required; run only with agents/feeders paused")
    if keep < 1:
        raise ValueError("keep must be >= 1")

    dest_root_path = Path(dest_root)
    dest_root_path.mkdir(parents=True, exist_ok=True)
    name = backup_name or f"{prefix}-{_timestamp()}"
    backup_dir = dest_root_path / name
    if backup_dir.exists():
        raise FileExistsError(f"backup destination already exists: {backup_dir}")

    args: dict[str, Any] = {
        "home": str(Path(home)),
        "dest": str(backup_dir),
        "_confirm": True,
        "quiescence_window": quiescence_window,
        "idempotency_key": idempotency_key or f"tracelab-backup:{name}",
    }
    envelope = dispatch("journal.backup", args, actor_id=actor_id)

    if envelope.ok:
        marker = {
            "schema_version": "1",
            "quiescence_window": quiescence_window,
            "tool": "journal.backup",
            "confirm": True,
            "backup_dir": str(backup_dir),
            "created_at": _timestamp(),
        }
        (backup_dir / "tracelab-backup.json").write_text(
            json.dumps(marker, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        pruned = tuple(prune_backups(dest_root_path, keep=keep, prefix=prefix))
    else:
        pruned = ()

    return BackupSidecarResult(
        backup_dir=backup_dir,
        envelope=envelope,
        pruned=pruned,
        quiescence_window=quiescence_window,
    )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one confirmed tracelab journal backup")
    parser.add_argument("--home", required=True, help="TRADE_TRACE_HOME to back up")
    parser.add_argument("--dest-root", required=True, help="Disposable root directory for sidecar backups")
    parser.add_argument("--quiescence-window", required=True, help="Name/id of the active agents-paused window")
    parser.add_argument("--keep", type=int, default=7, help="Number of sidecar backups to retain")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="Backup directory prefix")
    parser.add_argument("--backup-name", help="Explicit backup directory name (tests/schedulers)")
    ns = parser.parse_args(argv)

    result = run_backup_once(
        home=ns.home,
        dest_root=ns.dest_root,
        quiescence_window=ns.quiescence_window,
        keep=ns.keep,
        prefix=ns.prefix,
        backup_name=ns.backup_name,
    )
    print(json.dumps({
        "ok": result.ok,
        "backup_dir": str(result.backup_dir),
        "pruned": [str(p) for p in result.pruned],
        "envelope": result.envelope.model_dump(mode="json", exclude_none=True),
    }, sort_keys=True))
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
