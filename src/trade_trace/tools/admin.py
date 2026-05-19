"""Operability admin tools per bead trade-trace-2z7 and operability.md.

Surfaces the 10-tool admin matrix the operability spec calls for:

In MVP, fully functional:
  - journal.init      (in tools/journal.py)
  - journal.status    (in tools/journal.py)
  - journal.schema    (in tools/journal.py)
  - journal.rebuild_projections  (in tools/journal.py)
  - tool.schema       (in tools/journal.py — agent-facing introspection)
  - journal.repair    (here; --confirm required for the apply path)
  - journal.backup    (here; writes DB + manifest of SHA-256 hashes)
  - journal.restore   (here; --confirm required; reads manifest)
  - journal.config_set (here; persists key=value into the config table)

Contract-only (return UNSUPPORTED_CAPABILITY pointing at the future
embeddings work in trade-trace-a4p):
  - model.import      (air-gap model staging path; a4p)
  - model.warm        (lazy warm of the local embedder; a4p)
  - memory.reindex    (re-embed all nodes when provider changes; a4p)

Tools that mutate state respect the `--confirm` (CLI) / `_confirm: true`
(MCP) flag per the operability contract: without it they return
`ok=true` with `meta.preview_only=true` and describe what *would*
happen. With it, they execute.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.storage import open_database, resolve_home
from trade_trace.storage.paths import db_path
from trade_trace.tools._helpers import now_iso, require
from trade_trace.tools.errors import ToolError


def _confirm_requested(args: dict[str, Any]) -> bool:
    """Return True when either CLI `--confirm` or MCP `_confirm: true`
    was passed. The CLI flag parser surfaces it as `confirm=True`."""

    return bool(args.get("confirm") or args.get("_confirm"))


def _set_preview_meta(ctx: ToolContext) -> None:
    """Mark the envelope's meta with `preview_only=true` so the agent
    can branch on whether the call mutated state."""

    ctx.meta_hints["preview_only"] = True


# -- journal.repair ----------------------------------------------


def _journal_repair(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Run a manual integrity check + emit a preview/apply report.

    MVP scope: PRAGMA integrity_check, foreign_key_check, and a count
    of orphan rows in core tables. No destructive fixes; the apply path
    surfaces a structured report the operator can act on.
    """

    home = resolve_home(args.get("home"))
    path = db_path(home)
    if not path.exists():
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            "journal not initialized; run `tt journal init` first",
            details={"home": str(home), "db_path": str(path)},
        )
    db = open_database(path, create_parent=False)
    try:
        integrity_rows = db.connection.execute(
            "PRAGMA integrity_check"
        ).fetchall()
        integrity = [r[0] for r in integrity_rows]
        fk_rows = db.connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        fk_violations = [
            {"table": r[0], "rowid": r[1], "parent": r[2], "fkid": r[3]}
            for r in fk_rows
        ]
    finally:
        db.close()
    findings = {
        "integrity_check": integrity,
        "foreign_key_violations": fk_violations,
        "ok": integrity == ["ok"] and not fk_violations,
    }
    if not _confirm_requested(args):
        _set_preview_meta(ctx)
        return {
            "preview_only": True,
            "findings": findings,
            "would_apply": (
                "no destructive fixes in MVP; future repair tools will "
                "rebuild projection tables and prune orphan edges per "
                "operability.md §5.4"
            ),
        }
    # `--confirm`: no destructive fixes ship in MVP — return findings.
    return {"preview_only": False, "findings": findings, "applied": False,
            "note": "MVP repair is read-only; findings above are the report"}


# -- journal.backup ----------------------------------------------


def _journal_backup(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Copy the SQLite DB + the outbox JSONL tree into `<dest>` plus a
    manifest of SHA-256 hashes. Idempotent in the sense that re-running
    against the same dest overwrites the prior backup.

    Args:
      dest: directory the backup is written to. Created if missing.
    """

    home = resolve_home(args.get("home"))
    dest = require(args, "dest")
    dest_path = Path(dest)
    src_db = db_path(home)
    if not src_db.exists():
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            "journal not initialized; nothing to back up",
            details={"home": str(home), "db_path": str(src_db)},
        )
    if not _confirm_requested(args):
        _set_preview_meta(ctx)
        return {
            "preview_only": True,
            "would_write": {
                "dest": str(dest_path),
                "db_file": str(dest_path / src_db.name),
                "manifest": str(dest_path / "manifest.json"),
            },
        }
    dest_path.mkdir(parents=True, exist_ok=True)
    # Copy DB; checkpoint WAL first by opening a connection in
    # read-only mode would be ideal but SQLite's backup API is what's
    # really needed. For MVP we issue PRAGMA wal_checkpoint to flush
    # then copy the file.
    db = open_database(src_db, create_parent=False)
    try:
        db.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    finally:
        db.close()
    out_db = dest_path / src_db.name
    shutil.copy2(src_db, out_db)
    db_hash = hashlib.sha256(out_db.read_bytes()).hexdigest()
    files_manifest = [{"path": src_db.name, "sha256": db_hash,
                       "size": out_db.stat().st_size}]

    # Also back up the export/jsonl tree.
    jsonl_src = home / "export" / "jsonl"
    if jsonl_src.exists():
        for src_file in sorted(jsonl_src.rglob("*.jsonl")):
            rel = src_file.relative_to(home)
            out_file = dest_path / rel
            out_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, out_file)
            files_manifest.append({
                "path": str(rel),
                "sha256": hashlib.sha256(out_file.read_bytes()).hexdigest(),
                "size": out_file.stat().st_size,
            })

    manifest = {
        "schema_version": "1",
        "created_at": now_iso(),
        "home": str(home),
        "files": files_manifest,
    }
    manifest_path = dest_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2))
    return {
        "preview_only": False,
        "dest": str(dest_path),
        "file_count": len(files_manifest),
        "manifest_path": str(manifest_path),
        "db_sha256": db_hash,
    }


# -- journal.restore ---------------------------------------------


def _journal_restore(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Read a manifest from `<src>` and restore the DB + JSONL outbox
    into `$TRADE_TRACE_HOME`. Refuses without `--confirm`. SHA-256 of
    every restored file is verified against the manifest; mismatch
    aborts the restore."""

    home = resolve_home(args.get("home"))
    src = require(args, "src")
    src_path = Path(src)
    manifest_path = src_path / "manifest.json"
    if not manifest_path.exists():
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            f"manifest not found at {manifest_path}",
            details={"src": str(src_path),
                     "manifest_path": str(manifest_path)},
        )
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            f"manifest at {manifest_path} is not valid JSON: {exc}",
            details={"manifest_path": str(manifest_path)},
        ) from exc

    file_count = len(manifest.get("files", []))
    if not _confirm_requested(args):
        _set_preview_meta(ctx)
        return {
            "preview_only": True,
            "would_restore": {
                "home": str(home),
                "file_count": file_count,
                "manifest_created_at": manifest.get("created_at"),
            },
        }

    # Verify hashes BEFORE copying anything so a corrupt source aborts
    # cleanly.
    for entry in manifest["files"]:
        candidate = src_path / entry["path"]
        if not candidate.exists():
            raise ToolError(
                ErrorCode.STORAGE_ERROR,
                f"manifest references missing file {entry['path']!r}",
                details={"candidate": str(candidate)},
            )
        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            raise ToolError(
                ErrorCode.INVARIANT_VIOLATION,
                f"sha256 mismatch on {entry['path']!r}: "
                f"manifest={entry['sha256']!r} actual={actual!r}",
                details={"entry": entry, "actual_sha256": actual},
            )

    home.mkdir(parents=True, exist_ok=True)
    restored: list[str] = []
    for entry in manifest["files"]:
        src_file = src_path / entry["path"]
        out_file = home / entry["path"]
        out_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, out_file)
        restored.append(entry["path"])
    return {
        "preview_only": False,
        "home": str(home),
        "restored_count": len(restored),
        "restored_files": restored,
    }


# -- journal.config_set ------------------------------------------


def _journal_config_set(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Persist a key=value pair into the `config` table. Per
    operability.md §4.3, config keys are open-namespace strings; the
    server stores them verbatim and lets consumers interpret. The
    embeddings.provider key is validated against the closed enum
    {none, local, api:openai} per memory-layer.md §8.5."""

    key = require(args, "key")
    value = require(args, "value")
    if not isinstance(key, str) or not key:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "key must be a non-empty string",
            details={"field": "key", "value": key},
        )
    if not isinstance(value, str):
        # Coerce non-string values (ints, bools, floats) to their JSON
        # form so the config table stays text-only.
        value = json.dumps(value, sort_keys=True)
    # Specific key validation: embeddings.provider.
    if key == "embeddings.provider":
        allowed = {"none", "local", "api:openai"}
        if value not in allowed:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"embeddings.provider must be one of {sorted(allowed)}; "
                f"got {value!r}",
                details={"field": "value", "value": value,
                         "allowed": sorted(allowed)},
            )
        if value != "none":
            # The actual provider activation lives in bead a4p; surface
            # the unsupported state explicitly so the agent doesn't
            # think the embeddings strategy is suddenly active.
            raise ToolError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "embeddings.provider != 'none' is deferred to bead "
                "trade-trace-a4p (sqlite-vec + bge-small + keyring). "
                "The config surface accepts the value once that bead lands.",
                details={"setting": "embeddings.provider", "value": value,
                         "deferred_to_bead": "trade-trace-a4p"},
            )

    home = resolve_home(args.get("home"))
    path = db_path(home)
    if not path.exists():
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            "journal not initialized; run `tt journal init` first",
            details={"home": str(home), "db_path": str(path)},
        )
    db = open_database(path, create_parent=False)
    try:
        db.connection.execute(
            "INSERT INTO config(key, value, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now_iso()),
        )
        db.connection.commit()
    finally:
        db.close()
    return {"key": key, "value": value}


# -- model.* and memory.reindex stubs (bead a4p) ------------------


def _model_import_stub(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    raise ToolError(
        ErrorCode.UNSUPPORTED_CAPABILITY,
        "model.import requires the embeddings opt-in path (sqlite-vec + "
        "bge-small + OS keyring) — deferred to bead trade-trace-a4p.",
        details={"deferred_to_bead": "trade-trace-a4p",
                 "phase": "MVP-contract-only"},
    )


def _model_warm_stub(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    raise ToolError(
        ErrorCode.UNSUPPORTED_CAPABILITY,
        "model.warm requires the embeddings opt-in path — deferred to "
        "bead trade-trace-a4p.",
        details={"deferred_to_bead": "trade-trace-a4p",
                 "phase": "MVP-contract-only"},
    )


def _memory_reindex_stub(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    raise ToolError(
        ErrorCode.UNSUPPORTED_CAPABILITY,
        "memory.reindex requires the embeddings opt-in path — deferred "
        "to bead trade-trace-a4p.",
        details={"deferred_to_bead": "trade-trace-a4p",
                 "phase": "MVP-contract-only"},
    )


def register_admin_tools(registry: ToolRegistry) -> None:
    registry.register(
        "journal.repair",
        _journal_repair,
        description=(
            "Run PRAGMA integrity_check + foreign_key_check; emit a "
            "findings report. Without --confirm, returns "
            "meta.preview_only=true. MVP repair is read-only — the apply "
            "path returns the same findings without mutating state."
        ),
    )
    registry.register(
        "journal.backup",
        _journal_backup,
        is_write=True,
        description=(
            "Copy the SQLite DB + outbox JSONL tree into <dest> plus a "
            "SHA-256 manifest. Idempotent over the same dest. Requires "
            "--confirm to write; without it returns "
            "meta.preview_only=true with the would-be file list."
        ),
    )
    registry.register(
        "journal.restore",
        _journal_restore,
        is_write=True,
        description=(
            "Restore from <src> back into $TRADE_TRACE_HOME, verifying "
            "every file's SHA-256 against the manifest before copying. "
            "Requires --confirm; without it returns "
            "meta.preview_only=true. Mismatched SHA-256 aborts the "
            "restore with INVARIANT_VIOLATION."
        ),
    )
    registry.register(
        "journal.config_set",
        _journal_config_set,
        is_write=True,
        description=(
            "Persist a key=value pair into the config table. The "
            "embeddings.provider key is validated against the closed "
            "enum {none, local, api:openai}; non-'none' values "
            "currently surface UNSUPPORTED_CAPABILITY pointing at "
            "bead trade-trace-a4p."
        ),
    )
    registry.register(
        "model.import",
        _model_import_stub,
        is_write=True,
        description=(
            "[Deferred to trade-trace-a4p] Copy a pre-staged embedding "
            "model under $TRADE_TRACE_HOME/models/ — air-gap path for "
            "the SEMANTIC recall strategy. Currently surfaces "
            "UNSUPPORTED_CAPABILITY."
        ),
    )
    registry.register(
        "model.warm",
        _model_warm_stub,
        description=(
            "[Deferred to trade-trace-a4p] Load the local embedder into "
            "memory and run a dummy embed for latency-sensitive setups. "
            "Currently surfaces UNSUPPORTED_CAPABILITY."
        ),
    )
    registry.register(
        "memory.reindex",
        _memory_reindex_stub,
        is_write=True,
        description=(
            "[Deferred to trade-trace-a4p] Re-embed all nodes on "
            "provider change inside a single transaction. Reports node "
            "count + cost estimate before running. Currently surfaces "
            "UNSUPPORTED_CAPABILITY."
        ),
    )
