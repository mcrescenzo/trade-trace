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

Embeddings admin paths:
  - model.import      (opt-in local model staging/download path; 89x)
  - model.warm        (lazy warm of the local embedder; 89x)
  - memory.reindex    (re-embed all nodes when provider changes; 89x)
  - keyring.revoke    (revoke stored OpenAI embeddings credential)

Tools that mutate state respect the `--confirm` (CLI) / `_confirm: true`
(MCP) flag per the operability contract: without it they return
`ok=true` with `meta.preview_only=true` and describe what *would*
happen. With it, they execute.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import urllib.request
from pathlib import Path, PureWindowsPath
from typing import Any

from trade_trace._permissions import chmod_user_only_dir, chmod_user_only_file
from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.storage import open_database, resolve_home
from trade_trace.storage.paths import db_path
from trade_trace.tools._helpers import now_iso, require
from trade_trace.tools.errors import ToolError
from trade_trace.tools.memory import _embeddings_provider, _float32_blob, _query_embedding

OPENAI_EMBEDDINGS_KEYRING_SERVICE = "trade-trace:embeddings:openai"
EMBEDDINGS_API_KEY_ARG = "api_key"
BGE_SMALL_MODEL_ID = "BAAI/bge-small-en-v1.5"
BGE_SMALL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
BGE_SMALL_MODEL_DIRNAME = "bge-small-en-v1.5"
BGE_SMALL_TARGET_SUBDIR = Path("models") / BGE_SMALL_MODEL_DIRNAME
BGE_SMALL_HF_BASE_URL = f"https://huggingface.co/{BGE_SMALL_MODEL_ID}/resolve/{BGE_SMALL_REVISION}"
BGE_SMALL_LOCK: tuple[dict[str, Any], ...] = (
    {"path": "config.json", "size": 743, "sha256": "094f8e891b932f2000c92cfc663bac4c62069f5d8af5b5278c4306aef3084750"},
    {"path": "tokenizer.json", "size": 711396, "sha256": "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"},
    {"path": "tokenizer_config.json", "size": 366, "sha256": "9261e7d79b44c8195c1cada2b453e55b00aeb81e907a6664974b4d7776172ab3"},
    {"path": "vocab.txt", "size": 231508, "sha256": "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3"},
    {"path": "special_tokens_map.json", "size": 125, "sha256": "b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3"},
    {"path": "modules.json", "size": 349, "sha256": "84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf"},
    {"path": "sentence_bert_config.json", "size": 52, "sha256": "84e39fda68ccbff05bfa723ae9c0e70e23e2ec373b76e0f8c6e71af72a693cbf"},
    {"path": "1_Pooling/config.json", "size": 190, "sha256": "d1caf60c96f5fba2157c0c26b76d80818fad6cf0b8eb5e73ec372ff9818eba5c"},
    {"path": "config_sentence_transformers.json", "size": 124, "sha256": "940d5f50db195fa6e5e6a4f122c095f77880de259d74b14a65779ed48bdd7c56"},
    {"path": "model.safetensors", "size": 133466304, "sha256": "f34dad568ecbc8f2452ae7ea84e72884e1bab4f299cec39fd8f978b5fba8d3c9"},
)


def _confirm_requested(args: dict[str, Any]) -> bool:
    """Return True when either CLI `--confirm` or MCP `_confirm: true`
    was passed. The CLI flag parser surfaces it as `confirm=True`."""

    return bool(args.get("confirm") or args.get("_confirm"))


def _set_preview_meta(ctx: ToolContext) -> None:
    """Mark the envelope's meta with `preview_only=true` so the agent
    can branch on whether the call mutated state."""

    ctx.meta_hints["preview_only"] = True


def _model_target_dir(home: Path) -> Path:
    return home / BGE_SMALL_TARGET_SUBDIR


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _trusted_bge_small_lock() -> tuple[dict[str, Any], ...]:
    """Return Trade Trace-pinned bge-small file hashes/sizes.

    Tests may monkeypatch this narrow seam with tiny fixture files. Source
    directories and HuggingFace metadata are never trusted as proof.
    """

    return BGE_SMALL_LOCK


def safe_relative_path(rel: object) -> Path:
    """Return *rel* as a safe, non-empty relative path.

    This low-level helper is intentionally domain-neutral: callers translate
    failures into their own ToolError code/message/details at the trust
    boundary. It rejects absolute POSIX paths, Windows absolute/drive paths,
    empty/non-string values, and any parent traversal segment before callers
    attempt disk reads or writes.
    """

    if not isinstance(rel, str) or not rel:
        raise ValueError("path must be a non-empty string")
    path = Path(rel)
    win = PureWindowsPath(rel)
    if path.is_absolute() or win.is_absolute() or win.drive or ".." in path.parts or ".." in win.parts:
        raise ValueError("path is not a safe relative path")
    return path


def resolve_under_root(root: Path, rel: object) -> Path:
    """Resolve a safe relative path beneath *root*, rejecting escapes.

    The containment check is performed after symlink resolution with
    ``strict=False`` so callers can validate intended destinations before the
    final file exists, while still detecting existing symlink pivots that would
    escape the root.
    """

    rel_path = safe_relative_path(rel)
    root_resolved = root.resolve(strict=False)
    candidate = (root / rel_path).resolve(strict=False)
    if root_resolved != candidate and root_resolved not in candidate.parents:
        raise ValueError("path resolves outside root")
    return candidate


def _safe_model_relpath(rel: object) -> Path:
    try:
        return safe_relative_path(rel)
    except ValueError as exc:
        raise ToolError(ErrorCode.INVARIANT_VIOLATION, "invalid trusted model path", details={"path": rel}) from exc


def _resolve_under(root: Path, rel: object) -> Path:
    try:
        rel_path = safe_relative_path(rel)
    except ValueError as exc:
        raise ToolError(ErrorCode.INVARIANT_VIOLATION, "invalid trusted model path", details={"path": rel}) from exc
    root_resolved = root.resolve(strict=False)
    candidate = (root / rel_path).resolve(strict=False)
    if root_resolved != candidate and root_resolved not in candidate.parents:
        raise ToolError(ErrorCode.INVARIANT_VIOLATION, "model path escapes root", details={"root": str(root), "path": rel})
    return candidate


def _trusted_model_entries() -> tuple[tuple[str, int, str], ...]:
    entries: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for entry in _trusted_bge_small_lock():
        rel = entry.get("path") if isinstance(entry, dict) else None
        size = entry.get("size") if isinstance(entry, dict) else None
        expected = entry.get("sha256") if isinstance(entry, dict) else None
        if not isinstance(rel, str):
            raise ToolError(ErrorCode.INVARIANT_VIOLATION, "invalid trusted model path", details={"path": rel})
        _safe_model_relpath(rel)
        if rel in seen:
            raise ToolError(ErrorCode.INVARIANT_VIOLATION, "duplicate trusted model path", details={"path": rel})
        if not isinstance(size, int) or size < 0:
            raise ToolError(ErrorCode.INVARIANT_VIOLATION, "invalid trusted model size", details={"path": rel})
        if not isinstance(expected, str) or len(expected) != 64:
            raise ToolError(ErrorCode.INVARIANT_VIOLATION, "invalid trusted model sha256", details={"path": rel})
        seen.add(rel)
        entries.append((rel, size, expected))
    if not entries:
        raise ToolError(ErrorCode.INVARIANT_VIOLATION, "trusted model lock is empty")
    return tuple(entries)


def _verify_model_dir(model_dir: Path) -> dict[str, Any]:
    verified: list[str] = []
    for rel, expected_size, expected in _trusted_model_entries():
        candidate = _resolve_under(model_dir, rel)
        if candidate.is_symlink() or not candidate.is_file():
            raise ToolError(
                ErrorCode.INVARIANT_VIOLATION,
                f"trusted model file missing or not regular {rel!r}",
                details={"path": rel, "candidate": str(candidate)},
            )
        actual_size = candidate.stat().st_size
        if actual_size != expected_size:
            raise ToolError(
                ErrorCode.INVARIANT_VIOLATION,
                f"size mismatch on model file {rel!r}",
                details={"path": rel, "expected_size": expected_size, "actual_size": actual_size},
            )
        actual = _sha256_file(candidate)
        if actual != expected:
            raise ToolError(
                ErrorCode.INVARIANT_VIOLATION,
                f"sha256 mismatch on model file {rel!r}",
                details={"path": rel, "expected_sha256": expected, "actual_sha256": actual},
            )
        verified.append(rel)
    return {"model_id": BGE_SMALL_MODEL_ID, "revision": BGE_SMALL_REVISION, "verified_files": verified}


def _model_files_present(home: Path) -> bool:
    try:
        _verify_model_dir(_model_target_dir(home))
        return True
    except ToolError:
        return False


def _atomic_replace_dir(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    chmod_user_only_dir(dest.parent)
    staging = dest.parent / f".{dest.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for rel, _size, _sha in _trusted_model_entries():
        source = _resolve_under(src, rel)
        if source.is_symlink() or not source.is_file():
            raise ToolError(ErrorCode.INVARIANT_VIOLATION, "trusted model file missing or not regular", details={"path": rel})
        out = _resolve_under(staging, rel)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, out, follow_symlinks=False)
    _verify_model_dir(staging)
    if dest.exists():
        shutil.rmtree(dest)
    staging.replace(dest)
    chmod_user_only_dir(dest)


def _download_bge_small_model(home: Path) -> dict[str, Any]:
    """One-shot opt-in download seam for BAAI/bge-small-en-v1.5.

    The production path is intentionally explicit and narrow: it downloads only
    Trade Trace-pinned allowlisted files at an immutable HuggingFace revision,
    then verifies SHA-256 and size before activation.
    """

    target = _model_target_dir(home)
    if _model_files_present(home):
        verified = _verify_model_dir(target)
        return {"downloaded": False, "target": str(target), **verified}
    tmp = target.parent / f".{target.name}.download"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        for rel, _size, _sha in _trusted_model_entries():
            out = _resolve_under(tmp, rel)
            out.parent.mkdir(parents=True, exist_ok=True)
            url = f"{BGE_SMALL_HF_BASE_URL}/{urllib.request.pathname2url(rel)}"
            with urllib.request.urlopen(url, timeout=300) as response:  # nosec B310 - explicit opt-in URL
                out.write_bytes(response.read())
        _atomic_replace_dir(tmp, target)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)
    verified = _verify_model_dir(target)
    return {"downloaded": True, "target": str(target), "source_url": BGE_SMALL_HF_BASE_URL, **verified}


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
    chmod_user_only_dir(dest_path)
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
    chmod_user_only_file(out_db)
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
            # Tighten every parent directory under dest_path so a
            # backup destination can't leak directory listings even
            # when intermediate dirs (export/, export/jsonl/, …) are
            # newly created by `mkdir(parents=True)`.
            for parent in out_file.parents:
                if parent == dest_path:
                    break
                chmod_user_only_dir(parent)
            shutil.copy2(src_file, out_file)
            chmod_user_only_file(out_file)
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
    chmod_user_only_file(manifest_path)
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

    # Validate every manifest path before touching the disk per bead
    # trade-trace-l24k. A tampered manifest entry with `..` segments, an
    # absolute path, or a Windows drive prefix must be rejected before
    # any read/copy so a malicious backup cannot write or corrupt files
    # outside `home` with the process's permissions. Use the same generic
    # rel-path and root-containment helpers as `model.import`, then translate
    # failures into journal.restore-specific ToolError details.
    validated: list[tuple[dict[str, Any], Path, Path]] = []
    for entry in manifest["files"]:
        raw_path = entry["path"]
        try:
            rel = safe_relative_path(raw_path)
        except ValueError as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"manifest path {raw_path!r} is not a safe relative "
                "path under TRADE_TRACE_HOME (no `..`, absolutes, or "
                "Windows drives allowed) per trade-trace-l24k",
                details={
                    "field": "path",
                    "manifest_path": raw_path,
                    "reason": "unsafe_manifest_path",
                },
            ) from exc
        try:
            src_file = resolve_under_root(src_path, raw_path)
        except ValueError as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"manifest path {raw_path!r} resolves outside the "
                "backup source after symlink resolution",
                details={
                    "field": "path",
                    "manifest_path": raw_path,
                    "src": str(src_path.resolve(strict=False)),
                    "resolved": str((src_path / rel).resolve(strict=False)),
                },
            ) from exc
        try:
            out_file = resolve_under_root(home, raw_path)
        except ValueError as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"manifest path {raw_path!r} resolves outside "
                "TRADE_TRACE_HOME after symlink resolution",
                details={
                    "field": "path",
                    "manifest_path": raw_path,
                    "home": str(home.resolve(strict=False)),
                    "resolved": str((home / rel).resolve(strict=False)),
                },
            ) from exc
        validated.append((entry, src_file, out_file))

    # Verify hashes BEFORE copying anything so a corrupt source aborts
    # cleanly.
    for entry, src_file, _ in validated:
        if not src_file.exists():
            raise ToolError(
                ErrorCode.STORAGE_ERROR,
                f"manifest references missing file {entry['path']!r}",
                details={"candidate": str(src_file)},
            )
        actual = hashlib.sha256(src_file.read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            raise ToolError(
                ErrorCode.INVARIANT_VIOLATION,
                f"sha256 mismatch on {entry['path']!r}: "
                f"manifest={entry['sha256']!r} actual={actual!r}",
                details={"entry": entry, "actual_sha256": actual},
            )

    home.mkdir(parents=True, exist_ok=True)
    chmod_user_only_dir(home)
    restored: list[str] = []
    for entry, src_file, out_file in validated:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        for parent in (out_file.parent, *out_file.parent.parents):
            if parent == home:
                chmod_user_only_dir(parent)
                break
            if home in parent.parents:
                chmod_user_only_dir(parent)
        shutil.copy2(src_file, out_file)
        chmod_user_only_file(out_file)
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
        if value == "api:openai" and _confirm_requested(args) and not args.get(EMBEDDINGS_API_KEY_ARG):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "api:openai requires an API key supplied by an interactive CLI prompt "
                "or a non-persisted api_key argument; the key is stored only in the OS keyring",
                details={"field": "api_key", "secret_storage": "os_keyring"},
            )

    home = resolve_home(args.get("home"))
    path = db_path(home)
    if not path.exists():
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            "journal not initialized; run `tt journal init` first",
            details={"home": str(home), "db_path": str(path)},
        )

    # Per bead trade-trace-b10: journal.config_set is a mutating admin
    # tool and must follow the same confirm/preview contract every
    # other admin tool uses (operability.md §2z7). Without --confirm
    # the call returns ok=true with meta.preview_only=true describing
    # what *would* be written; with --confirm it persists.
    if not _confirm_requested(args):
        _set_preview_meta(ctx)
        return {
            "preview_only": True,
            "would_write": {
                "key": key,
                "value": value,
                "home": str(home),
            },
        }

    model_download: dict[str, Any] | None = None
    if key == "embeddings.provider" and value == "local":
        # Opt-in boundary: the only lazy outbound path fires on an explicit
        # provider switch to local, and only when the verified model directory
        # is missing. Air-gap installs can avoid this path with model.import.
        if not _model_files_present(home):
            model_download = _download_bge_small_model(home)
        else:
            model_download = {"downloaded": False, "target": str(_model_target_dir(home))}
    elif key == "embeddings.provider" and value == "api:openai":
        # Consume the secret only to populate the OS keyring. Never persist it
        # in config, events, outbox, return data, or logs.
        from trade_trace.security.keyring import store_api_key

        store_api_key(OPENAI_EMBEDDINGS_KEYRING_SERVICE, str(args[EMBEDDINGS_API_KEY_ARG]))

    if key == "embeddings.provider":
        # Avoid loading sqlite-vec while changing the provider row; the extension
        # is optional and should not be required merely to toggle config.
        conn = sqlite3.connect(str(path), isolation_level=None)
        try:
            conn.execute(
                "INSERT INTO config(key, value, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value = excluded.value, updated_at = excluded.updated_at",
                (key, value, now_iso()),
            )
            conn.commit()
        finally:
            conn.close()
    else:
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
    result = {"preview_only": False, "key": key, "value": value}
    if model_download is not None:
        result["model"] = model_download
    if key == "embeddings.provider" and value == "api:openai":
        result["api_key_storage"] = "os_keyring"
    return result


# -- model.* and memory.reindex stubs (bead a4p) ------------------


def _model_import(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Copy a pre-staged BAAI/bge-small-en-v1.5 directory into
    $TRADE_TRACE_HOME/models/bge-small-en-v1.5 without touching the network.
    The source is verified against the Trade Trace-pinned model lock (immutable
    HuggingFace revision, allowlisted relative paths, SHA-256, and size). Any
    source-provided manifests are ignored and are never trusted as proof.
    """

    home = resolve_home(args.get("home"))
    raw_path = require(args, "path")
    src = Path(str(raw_path))
    if not src.is_dir():
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "model.import --path must point at a pre-staged model directory",
            details={"path": str(src)},
        )
    verified = _verify_model_dir(src)
    target = _model_target_dir(home)
    if not _confirm_requested(args):
        _set_preview_meta(ctx)
        return {
            "preview_only": True,
            "would_copy": {"src": str(src), "target": str(target)},
            **verified,
        }
    _atomic_replace_dir(src, target)
    copied = _verify_model_dir(target)
    return {
        "preview_only": False,
        "model_id": BGE_SMALL_MODEL_ID,
        "src": str(src),
        "target": str(target),
        **copied,
    }


def _model_warm_stub(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    raise ToolError(
        ErrorCode.UNSUPPORTED_CAPABILITY,
        "model.warm requires the embeddings opt-in path — deferred to "
        "bead trade-trace-a4p.",
        details={"deferred_to_bead": "trade-trace-a4p",
                 "phase": "MVP-contract-only"},
    )


def _memory_reindex_model(provider: str) -> tuple[str, int]:
    if provider == "local":
        return f"{BGE_SMALL_MODEL_ID}@{BGE_SMALL_REVISION}", 384
    if provider == "api:openai":
        return "text-embedding-3-small", 1536
    return "none", 0


def _memory_reindex_cost(provider: str, nodes: list[tuple[str, str]]) -> dict[str, Any]:
    token_estimate = sum(max(1, len(body.split())) for _node_id, body in nodes)
    if provider == "api:openai":
        # Rough public-list-price estimate for text-embedding-3-small at
        # $0.02 / 1M tokens. This is preview metadata only; no network call is
        # made by memory.reindex.
        return {
            "currency": "USD",
            "token_estimate": token_estimate,
            "estimated_usd": round(token_estimate * 0.02 / 1_000_000, 8),
            "basis": "rough estimate: text-embedding-3-small at $0.02 / 1M tokens",
        }
    return {
        "currency": "USD",
        "token_estimate": token_estimate,
        "estimated_usd": 0.0,
        "basis": "local/offline deterministic embedding path",
    }


def _memory_reindex(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Re-embed every memory node for the currently configured provider.

    Preview mode reports the node count and estimate only. Confirm mode writes
    all embeddings in one UnitOfWork transaction; any exception rolls back both
    new rows and deletion of superseded rows for the active provider.
    """

    home = resolve_home(args.get("home"))
    path = db_path(home)
    if not path.exists():
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            "journal not initialized; run `tt journal init` first",
            details={"home": str(home), "db_path": str(path)},
        )

    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        provider = _embeddings_provider(conn)
        rows = conn.execute(
            "SELECT id, COALESCE(body, '') FROM memory_nodes ORDER BY id"
        ).fetchall()
        nodes = [(str(row[0]), str(row[1])) for row in rows]
        model_id, dim = _memory_reindex_model(provider)
        plan = {
            "provider": provider,
            "model_id": model_id,
            "dim": dim,
            "node_count": len(nodes) if provider != "none" else 0,
            "cost_estimate": _memory_reindex_cost(provider, nodes if provider != "none" else []),
        }
        if not _confirm_requested(args):
            _set_preview_meta(ctx)
            return {"preview_only": True, "would_reindex": plan}
        if provider == "none":
            return {"preview_only": False, "provider": provider, "model_id": model_id, "dim": dim, "reindexed_count": 0}
        if provider == "api:openai":
            from trade_trace.security.keyring import load_api_key

            api_key = load_api_key(OPENAI_EMBEDDINGS_KEYRING_SERVICE)
            if not api_key:
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    "api:openai memory.reindex requires an embeddings API key in the OS keyring",
                    details={"provider": provider, "secret_storage": "os_keyring"},
                )
            del api_key
        created_at = now_iso()
        with UnitOfWork(conn) as uow:
            for node_id, body in nodes:
                embedding = _query_embedding(body, dim=dim, provider=provider, model_id=model_id)
                uow.execute(
                    "INSERT INTO memory_node_embeddings(node_id, provider, dim, model_id, embedding, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(node_id, provider, model_id) DO UPDATE SET "
                    "dim = excluded.dim, embedding = excluded.embedding, created_at = excluded.created_at",
                    (node_id, provider, dim, model_id, _float32_blob(embedding), created_at),
                )
            uow.execute(
                "DELETE FROM memory_node_embeddings WHERE provider = ? AND model_id <> ?",
                (provider, model_id),
            )
        return {
            "preview_only": False,
            "provider": provider,
            "model_id": model_id,
            "dim": dim,
            "reindexed_count": len(nodes),
            "deleted_prior_provider_rows": True,
        }
    finally:
        conn.close()


def _keyring_revoke(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Revoke the stored OpenAI embeddings credential from the OS keyring.

    This is intentionally narrow: Trade Trace currently has exactly one
    shipped keyring-backed credential lifecycle, configured by
    ``journal.config_set key=embeddings.provider value=api:openai``. Do not
    accept arbitrary service names here; broad credential management belongs in
    a separate design.
    """

    if not _confirm_requested(args):
        _set_preview_meta(ctx)
        return {
            "preview_only": True,
            "would_revoke": {
                "provider": "api:openai",
                "credential_storage": "os_keyring",
            },
        }

    from trade_trace.security.keyring import delete_api_key

    delete_api_key(OPENAI_EMBEDDINGS_KEYRING_SERVICE)
    return {
        "preview_only": False,
        "provider": "api:openai",
        "credential_storage": "os_keyring",
        "revoked": True,
    }


def register_admin_tools(registry: ToolRegistry) -> None:
    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

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
        **_examples_for("journal.backup"),
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
        **_examples_for("journal.restore"),
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
        **_examples_for("journal.config_set"),
        description=(
            "Persist a key=value pair into the config table. The "
            "embeddings.provider key is validated against the closed "
            "enum {none, local, api:openai}. 'none' disables semantic "
            "embeddings, 'local' enables local/stub semantic ranking, and "
            "'api:openai' stores a required API key only in a validated secure "
            "OS keyring. A raw key argument is accepted only for MCP/CLI "
            "noninteractive setup, is never returned, and is not persisted by "
            "the app. memory.recall currently resolves that key as a gate but "
            "uses the local/stub query embedding path; no OpenAI network call "
            "is implemented here."
        ),
    )
    registry.register(
        "model.import",
        _model_import,
        is_write=True,
        **_examples_for("model.import"),
        description=(
            "Copy a pre-staged BAAI/bge-small-en-v1.5 model directory under "
            "$TRADE_TRACE_HOME/models/bge-small-en-v1.5 for air-gap SEMANTIC "
            "recall. Requires --confirm to write; verifies every file's "
            "SHA-256 and size against Trade Trace-pinned lock data and "
            "performs zero outbound network calls."
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
        _memory_reindex,
        is_write=True,
        **_examples_for("memory.reindex"),
        description=(
            "Re-embed all memory nodes for the active embeddings provider "
            "inside a single transaction. Requires --confirm to write; "
            "without it returns meta.preview_only=true with node count and "
            "cost estimate. api:openai requires only keyring presence and "
            "uses the deterministic local substrate; no OpenAI network call "
            "is implemented here."
        ),
    )
    registry.register(
        "keyring.revoke",
        _keyring_revoke,
        is_write=True,
        **_examples_for("keyring.revoke"),
        description=(
            "Revoke the stored OpenAI embeddings key from the validated OS "
            "keyring. Requires --confirm; without it returns "
            "meta.preview_only=true. This narrow admin path is idempotent and "
            "does not accept or return key material."
        ),
    )
