"""TraceLab substrate-invariant checker over run artifacts.

The checker is intentionally artifact-only: it reads a dispatch JSONL trace and a
local SQLite journal, uses disposable copies for rebuild verification, and runs a
quiesced backup/restore round-trip into caller-provided scratch paths. It does
not score throughput.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from tools.tracelab.backup import run_backup_once
from trade_trace.mcp_server import mcp_call
from trade_trace.projections import rebuild_positions
from trade_trace.storage.paths import DB_FILENAME

PASS = "PASS"
FAIL = "FAIL"
LIMITATION = "LIMITATION"


def _load_trace(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
    return records


def _status(name: str, status: str, reason: str, **evidence: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "reason": reason, "evidence": evidence}


def _pair_key(record: dict[str, Any]) -> tuple[Any, ...] | None:
    request_id = record.get("request_id")
    if request_id:
        return ("request_id", request_id)
    retry_of = record.get("retry_of")
    if retry_of:
        return ("request_id", retry_of)
    fp = record.get("replay_fingerprint")
    actor_id = record.get("actor_id")
    tool = record.get("tool")
    if actor_id and isinstance(fp, dict) and fp.get("digest"):
        return ("actor_replay_fingerprint", actor_id, tool, fp.get("digest"))
    return None


def check_lock_recovery(trace_path: str | Path) -> dict[str, Any]:
    """Check STORAGE_ERROR invariants from dispatch trace records.

    Non-lock STORAGE_ERROR fails immediately. single_writer_lock records must be
    paired to a successful retry by request lineage or by actor+fingerprint. A
    lock record with neither request lineage nor replay fingerprint is reported
    as a documented limitation because raw idempotency keys are intentionally not
    present in traces.
    """

    records = _load_trace(trace_path)
    successes: set[tuple[Any, ...]] = set()
    for rec in records:
        if rec.get("ok") is True:
            key = _pair_key(rec)
            if key is not None:
                successes.add(key)
            retry_of = rec.get("retry_of")
            if retry_of:
                successes.add(("request_id", retry_of))

    lock_errors: list[dict[str, Any]] = []
    non_lock_storage_errors: list[dict[str, Any]] = []
    paired = 0
    limitations = 0
    unpaired: list[str] = []
    for rec in records:
        if rec.get("error_code") != "STORAGE_ERROR":
            continue
        if rec.get("details", {}).get("reason") != "single_writer_lock":
            non_lock_storage_errors.append({
                "request_id": rec.get("request_id"),
                "tool": rec.get("tool"),
                "reason": rec.get("details", {}).get("reason"),
            })
            continue
        lock_errors.append(rec)
        key = _pair_key(rec)
        if key is None:
            limitations += 1
        elif key in successes:
            paired += 1
        else:
            unpaired.append(str(rec.get("request_id") or rec.get("tool") or "unknown"))

    if non_lock_storage_errors or unpaired:
        return _status(
            "storage_errors_recovery_in_1_retry",
            FAIL,
            "non-lock STORAGE_ERROR or pairable single_writer_lock without recovering success observed",
            total_records=len(records),
            single_writer_lock_errors=len(lock_errors),
            paired_single_writer_locks=paired,
            keyless_lock_limitations=limitations,
            non_lock_storage_errors=non_lock_storage_errors,
            unpaired_lock_request_ids=unpaired,
        )
    if limitations:
        return _status(
            "storage_errors_recovery_in_1_retry",
            LIMITATION,
            "all pairable lock errors recovered; some keyless lock records cannot be proven without raw keys",
            total_records=len(records),
            single_writer_lock_errors=len(lock_errors),
            paired_single_writer_locks=paired,
            keyless_lock_limitations=limitations,
            non_lock_storage_errors=[],
            unpaired_lock_request_ids=[],
        )
    return _status(
        "storage_errors_recovery_in_1_retry",
        PASS,
        "all STORAGE_ERROR records are single_writer_lock and recovered by one retry lineage",
        total_records=len(records),
        single_writer_lock_errors=len(lock_errors),
        paired_single_writer_locks=paired,
        keyless_lock_limitations=0,
        non_lock_storage_errors=[],
        unpaired_lock_request_ids=[],
    )


def _positions_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cols = [row[1] for row in conn.execute("PRAGMA table_info(positions)").fetchall()]
    if not cols:
        return []
    quoted = ", ".join(f'"{c}"' for c in cols)
    order = ", ".join(f'"{c}"' for c in cols)
    rows = conn.execute(f"SELECT {quoted} FROM positions ORDER BY {order}").fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def check_rebuild_positions(run_db_path: str | Path) -> dict[str, Any]:
    source = Path(run_db_path)
    with tempfile.TemporaryDirectory(prefix="tracelab-rebuild-") as tmp:
        copy_path = Path(tmp) / source.name
        source_uri = f"{source.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(source_uri, uri=True) as src, sqlite3.connect(copy_path) as dst:
            src.backup(dst)
        with sqlite3.connect(copy_path) as conn:
            before = _positions_rows(conn)
            with conn:
                result = rebuild_positions(conn)
            after = _positions_rows(conn)
    diff = {"before_only": [r for r in before if r not in after], "after_only": [r for r in after if r not in before]}
    if diff["before_only"] or diff["after_only"]:
        return _status(
            "rebuild_positions_reproduces_rows",
            FAIL,
            "journal.rebuild_projections positions on a DB copy produced a non-empty positions diff",
            before_count=len(before),
            after_count=len(after),
            rebuild={"dropped_rows": result.dropped_rows, "rebuilt_rows": result.rebuilt_rows},
            diff=diff,
        )
    return _status(
        "rebuild_positions_reproduces_rows",
        PASS,
        "rebuilding positions on a DB copy reproduced identical deterministic rows",
        before_count=len(before),
        after_count=len(after),
        rebuild={"dropped_rows": result.dropped_rows, "rebuilt_rows": result.rebuilt_rows},
        diff={"before_only": [], "after_only": []},
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_quiesced_backup_restore(
    *,
    home: str | Path,
    run_db_path: str | Path,
    backup_dest_root: str | Path,
    quiescence_window: str,
) -> dict[str, Any]:
    backup = run_backup_once(
        home=home,
        dest_root=backup_dest_root,
        quiescence_window=quiescence_window,
        keep=7,
    )
    if not backup.ok:
        return _status(
            "quiesced_backup_restore_byte_identical",
            FAIL,
            "journal.backup returned an error envelope",
            backup_dir=str(backup.backup_dir),
            envelope=backup.envelope.model_dump(mode="json", exclude_none=True),
        )
    restored_home = Path(backup_dest_root) / "restore-check-home"
    restore = mcp_call(
        "journal.restore",
        {
            "home": str(restored_home),
            "src": str(backup.backup_dir),
            "_confirm": True,
            "idempotency_key": f"tracelab-substrate-restore:{backup.backup_dir.name}",
        },
        actor_id="system:tracelab-substrate-invariants",
    )
    if not restore.ok:
        return _status(
            "quiesced_backup_restore_byte_identical",
            FAIL,
            "journal.restore returned an error envelope",
            backup_dir=str(backup.backup_dir),
            envelope=restore.model_dump(mode="json", exclude_none=True),
        )
    original_hash = _sha256(Path(run_db_path))
    restored_hash = _sha256(restored_home / DB_FILENAME)
    return _status(
        "quiesced_backup_restore_byte_identical",
        PASS if original_hash == restored_hash else FAIL,
        "restored DB is byte-identical to the quiesced run DB" if original_hash == restored_hash else "restored DB differs from the quiesced run DB",
        backup_dir=str(backup.backup_dir),
        restored_home=str(restored_home),
        original_sha256=original_hash,
        restored_sha256=restored_hash,
    )


def check_substrate_invariants(
    *,
    run_db_path: str | Path,
    home: str | Path,
    dispatch_trace_path: str | Path,
    backup_dest_root: str | Path,
    quiescence_window: str,
) -> dict[str, Any]:
    invariants = [
        check_lock_recovery(dispatch_trace_path),
        check_rebuild_positions(run_db_path),
        check_quiesced_backup_restore(
            home=home,
            run_db_path=run_db_path,
            backup_dest_root=backup_dest_root,
            quiescence_window=quiescence_window,
        ),
    ]
    overall = FAIL if any(i["status"] == FAIL for i in invariants) else (LIMITATION if any(i["status"] == LIMITATION for i in invariants) else PASS)
    return {
        "schema_version": "1",
        "checker": "tracelab.substrate_invariants",
        "overall_status": overall,
        "throughput_scored": False,
        "inputs": {
            "run_db_path": str(run_db_path),
            "home": str(home),
            "dispatch_trace_path": str(dispatch_trace_path),
            "backup_dest_root": str(backup_dest_root),
            "quiescence_window": quiescence_window,
        },
        "invariants": invariants,
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check TraceLab substrate invariants over run artifacts")
    parser.add_argument("--run-db", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--dispatch-trace", required=True)
    parser.add_argument("--backup-dest-root", required=True)
    parser.add_argument("--quiescence-window", required=True)
    ns = parser.parse_args(argv)
    report = check_substrate_invariants(
        run_db_path=ns.run_db,
        home=ns.home,
        dispatch_trace_path=ns.dispatch_trace,
        backup_dest_root=ns.backup_dest_root,
        quiescence_window=ns.quiescence_window,
    )
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["overall_status"] != FAIL else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
