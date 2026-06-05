"""Admin tool surface per bead trade-trace-2z7.

10 admin tools registered + per-tool happy-path + --confirm/preview
contract on mutating ones.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.core import default_registry

# -- registration: all 10 admin tools live in registry ----------


ADMIN_TOOLS = [
    "journal.init",
    "journal.status",
    "journal.schema",
    "journal.rebuild_projections",
    "journal.repair",
    "journal.backup",
    "journal.restore",
    "journal.config_set",
    "model.import",
    "model.warm",
    "memory.reindex",
    "keyring.revoke",
]


@pytest.mark.parametrize("tool", ADMIN_TOOLS)
def test_admin_tool_registered(tool):
    assert tool in default_registry().names()


def test_admin_config_set_description_documents_embeddings_behavior():
    desc = default_registry().get("journal.config_set").description.lower()
    assert "enum {none, local}" in desc
    assert "local onnx" in desc
    assert "remote/api providers" in desc
    assert "unsupported" in desc
    assert "keyring-backed embedding auth" in desc
    assert "unsupported_capability" not in desc


# -- journal.repair ---------------------------------------------


def test_journal_repair_preview_returns_findings(home):
    env = _mcp(home, "journal.repair", {})
    assert env.ok
    assert env.data["preview_only"] is True
    assert env.data["findings"]["ok"] is True
    assert env.meta.preview_only is True


def test_journal_repair_with_confirm_returns_findings(home):
    env = _mcp(home, "journal.repair", {"_confirm": True})
    assert env.ok
    assert env.data["preview_only"] is False
    assert env.data["applied"] is False  # MVP repair is read-only
    assert "findings" in env.data


# -- journal.backup ---------------------------------------------


def test_journal_backup_preview_lists_targets(home, tmp_path):
    dest = tmp_path / "bk"
    env = _mcp(home, "journal.backup", {"dest": str(dest)})
    assert env.ok
    assert env.data["preview_only"] is True
    assert "would_write" in env.data
    # The dest dir does not yet exist; nothing should have been written.
    assert not (dest / "manifest.json").exists()


def test_journal_backup_writes_files_and_manifest_with_confirm(home, tmp_path):
    dest = tmp_path / "bk"
    env = _mcp(home, "journal.backup", {"dest": str(dest), "_confirm": True})
    assert env.ok, env
    manifest_path = Path(env.data["manifest_path"])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema_version"] == "1"
    db_entry = next(f for f in manifest["files"]
                    if f["path"] == "trade-trace.sqlite")
    actual = hashlib.sha256(
        (dest / "trade-trace.sqlite").read_bytes()
    ).hexdigest()
    assert db_entry["sha256"] == actual


def test_journal_backup_dry_run_does_not_write(home, tmp_path):
    """journal.backup writes files outside UnitOfWork, so `_dry_run` must
    short-circuit to the preview instead of writing the backup tree — even
    when `_confirm` is passed. Same raw-IO admin-writer class as
    config_set. Regression for the AX dogfood finding."""

    dest = tmp_path / "bk"
    env = _mcp(home, "journal.backup",
               {"dest": str(dest), "_confirm": True, "_dry_run": True})
    assert env.ok, env
    assert env.data["preview_only"] is True
    assert not (dest / "manifest.json").exists()
    assert not (dest / "trade-trace.sqlite").exists()


# -- journal.restore --------------------------------------------


def test_journal_restore_preview_does_not_write(home, tmp_path):
    src = tmp_path / "bk"
    _mcp(home, "journal.backup",
         {"dest": str(src), "_confirm": True})
    # Restore into a fresh home in preview mode.
    new_home = tmp_path / "restored"
    env = _mcp(new_home, "journal.restore", {
        "src": str(src), "home": str(new_home),
    })
    # Restore preview path expects the home to NOT need to be initialized
    # — the tool just inspects the manifest.
    assert env.ok, env
    assert env.data["preview_only"] is True
    # New home file should not exist yet.
    assert not (new_home / "trade-trace.sqlite").exists()


def test_journal_restore_dry_run_does_not_write(home, tmp_path):
    """journal.restore overwrites the live home outside UnitOfWork, so
    `_dry_run` must short-circuit to the preview rather than restore — even
    with `_confirm`. Same raw-IO admin-writer class as config_set/backup;
    the most destructive member since it overwrites the journal DB."""

    src = tmp_path / "bk"
    _mcp(home, "journal.backup", {"dest": str(src), "_confirm": True})
    new_home = tmp_path / "restored"
    env = _mcp(new_home, "journal.restore", {
        "src": str(src), "home": str(new_home),
        "_confirm": True, "_dry_run": True,
    })
    assert env.ok, env
    assert env.data["preview_only"] is True
    assert not (new_home / "trade-trace.sqlite").exists()


def test_journal_restore_with_confirm_recreates_db(home, tmp_path):
    """Round-trip: back up → restore into a fresh home → DB sha256 matches."""

    src = tmp_path / "bk"
    backup = _mcp(home, "journal.backup",
                  {"dest": str(src), "_confirm": True}).data
    new_home = tmp_path / "restored"
    env = _mcp(new_home, "journal.restore", {
        "src": str(src), "home": str(new_home), "_confirm": True,
    })
    assert env.ok
    restored_db = new_home / "trade-trace.sqlite"
    assert restored_db.exists()
    actual = hashlib.sha256(restored_db.read_bytes()).hexdigest()
    assert actual == backup["db_sha256"]


def test_journal_restore_detects_corrupted_backup(home, tmp_path):
    """Tamper with a file in the backup directory; restore must abort
    with INVARIANT_VIOLATION before mutating the destination."""

    src = tmp_path / "bk"
    _mcp(home, "journal.backup",
         {"dest": str(src), "_confirm": True})
    # Corrupt the DB file in the backup.
    target = src / "trade-trace.sqlite"
    target.write_bytes(target.read_bytes() + b"\x00")
    new_home = tmp_path / "restored"
    env = _mcp(new_home, "journal.restore", {
        "src": str(src), "home": str(new_home), "_confirm": True,
    })
    assert env.ok is False
    assert env.error.code.value == "INVARIANT_VIOLATION"
    # No file should have been written.
    assert not (new_home / "trade-trace.sqlite").exists()


# -- journal.config_set ----------------------------------------


def test_journal_config_set_persists_value(home):
    env = _mcp(home, "journal.config_set", {
        "key": "report.calibration.min_sample", "value": "30",
        "_confirm": True,
    })
    assert env.ok
    # Re-read directly.
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT value FROM config WHERE key = ?",
            ("report.calibration.min_sample",),
        ).fetchone()
    finally:
        db.close()
    assert row[0] == "30"


def test_journal_config_set_preview_does_not_persist(home):
    """Per bead trade-trace-b10: without --confirm the call must return
    preview_only=true and write nothing to the config table."""

    env = _mcp(home, "journal.config_set", {
        "key": "report.calibration.min_sample", "value": "30",
        # Note: no _confirm flag.
    })
    assert env.ok, env
    assert env.data["preview_only"] is True
    assert env.data["would_write"]["key"] == "report.calibration.min_sample"
    assert env.data["would_write"]["value"] == "30"

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT value FROM config WHERE key = ?",
            ("report.calibration.min_sample",),
        ).fetchone()
    finally:
        db.close()
    assert row is None, "preview must not write any config row"


def test_journal_config_set_dry_run_does_not_persist(home):
    """A write tool advertises supports_dry_run=true via tool.schema, so
    `_dry_run` must roll back even when `_confirm` is also passed. config_set
    writes outside UnitOfWork (raw sqlite/open_database commits), so it must
    branch on the request-scoped dry-run flag itself or the "dry-run" silently
    mutates the live config table. Regression for the AX dogfood finding."""

    env = _mcp(home, "journal.config_set", {
        "key": "report.calibration.min_sample", "value": "30",
        "_confirm": True, "_dry_run": True,
    })
    assert env.ok, env
    assert env.data["preview_only"] is True

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT value FROM config WHERE key = ?",
            ("report.calibration.min_sample",),
        ).fetchone()
    finally:
        db.close()
    assert row is None, "dry-run must not write any config row"


def test_journal_config_set_embeddings_provider_none_succeeds(home):
    env = _mcp(home, "journal.config_set", {
        "key": "embeddings.provider", "value": "none",
        "_confirm": True,
    })
    assert env.ok


def test_journal_config_set_embeddings_provider_rejects_api_provider(home):
    """Remote/API embedding providers are intentionally unsupported in v0.0.2."""

    env = _mcp(home, "journal.config_set", {
        "key": "embeddings.provider", "value": "api:openai",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["allowed"] == ["local", "none"]


def test_journal_config_set_embeddings_provider_rejects_unknown_value(home):
    """Values outside the closed enum {none, local} are
    VALIDATION_ERROR, not UNSUPPORTED_CAPABILITY."""

    env = _mcp(home, "journal.config_set", {
        "key": "embeddings.provider", "value": "magic",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"


# -- deferred stubs -------------------------------------------
# -- model.import / embeddings local lazy model path ------------


def _write_fixture_model(path: Path, *, payload: bytes | None = None, manifest_hash: str | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    payload = payload or b"deterministic tiny bge-small test fixture\n"
    (path / "config.json").write_bytes(payload)
    # A source-provided manifest may exist, but production code must ignore it.
    digest = manifest_hash or hashlib.sha256(payload).hexdigest()
    (path / "trade-trace-model-manifest.json").write_text(json.dumps({
        "model_id": "BAAI/bge-small-en-v1.5",
        "files": [{"path": "config.json", "size": len(payload), "sha256": digest}],
    }, sort_keys=True))
    return path


def _patch_tiny_trusted_lock(monkeypatch, payload: bytes):
    from trade_trace.tools import admin

    monkeypatch.setattr(admin, "_trusted_bge_small_lock", lambda: ({
        "path": "config.json",
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    },))
    return admin


def test_model_import_air_gap_succeeds_with_sockets_patched(home, tmp_path, monkeypatch):
    import socket

    def _block(*args, **kwargs):
        raise RuntimeError("network access is disabled in this test")

    monkeypatch.setattr(socket, "socket", _block)
    payload = b"deterministic tiny bge-small test fixture\n"
    _patch_tiny_trusted_lock(monkeypatch, payload)
    src = _write_fixture_model(tmp_path / "BAAI" / "bge-small-en-v1.5", payload=payload)
    env = _mcp(home, "model.import", {"path": str(src), "_confirm": True})
    assert env.ok, env
    target = home / "models" / "bge-small-en-v1.5"
    assert (target / "config.json").read_bytes() == (src / "config.json").read_bytes()
    assert env.data["verified_files"] == ["config.json"]


def test_model_import_dry_run_does_not_copy(home, tmp_path, monkeypatch):
    """model.import copies a model dir outside UnitOfWork, so `_dry_run` must
    short-circuit to the preview instead of staging the assets — even with
    `_confirm`. Same raw-IO admin-writer class as config_set/backup."""

    payload = b"deterministic tiny bge-small test fixture\n"
    _patch_tiny_trusted_lock(monkeypatch, payload)
    src = _write_fixture_model(tmp_path / "BAAI" / "bge-small-en-v1.5", payload=payload)
    env = _mcp(home, "model.import",
               {"path": str(src), "_confirm": True, "_dry_run": True})
    assert env.ok, env
    assert env.data["preview_only"] is True
    target = home / "models" / "bge-small-en-v1.5"
    assert not target.exists(), "dry-run must not stage the model dir"


def test_model_import_rejects_malicious_self_manifest(home, tmp_path, monkeypatch):
    trusted_payload = b"trusted fixture\n"
    _patch_tiny_trusted_lock(monkeypatch, trusted_payload)
    malicious_payload = b"malicious replacement with matching self manifest\n"
    src = _write_fixture_model(
        tmp_path / "BAAI" / "bge-small-en-v1.5",
        payload=malicious_payload,
        manifest_hash=hashlib.sha256(malicious_payload).hexdigest(),
    )
    env = _mcp(home, "model.import", {"path": str(src), "_confirm": True})
    assert env.ok is False
    assert env.error.code.value == "INVARIANT_VIOLATION"
    assert "mismatch" in env.error.message.lower()


def test_config_set_embeddings_provider_local_does_not_stage_or_require_assets(home, monkeypatch):
    target = home / "models" / "bge-small-en-v1.5"
    assert not target.exists()

    first = _mcp(home, "journal.config_set", {
        "key": "embeddings.provider", "value": "local", "_confirm": True,
    })
    assert first.ok, first
    assert first.data["model_present"] is False
    assert not target.exists()

    second = _mcp(home, "journal.config_set", {
        "key": "embeddings.provider", "value": "local", "_confirm": True,
    })
    assert second.ok, second
    assert second.data["model_present"] is False
    assert not target.exists()


def test_model_import_rejects_bad_trusted_lock_path_before_copy(home, tmp_path, monkeypatch):
    payload = b"fixture payload\n"
    src = _write_fixture_model(tmp_path / "BAAI" / "bge-small-en-v1.5", payload=payload)
    from trade_trace.tools import admin

    monkeypatch.setattr(admin, "_trusted_bge_small_lock", lambda: ({
        "path": "../escape.bin", "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
    },))
    env = _mcp(home, "model.import", {"path": str(src), "_confirm": True})
    assert env.ok is False
    assert env.error.code.value == "INVARIANT_VIOLATION"
    assert not (home / "escape.bin").exists()


# -- memory.reindex ------------------------------------------------


def _retain_memory(home: Path, key: str, body: str) -> str:
    env = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": body,
        "idempotency_key": key,
    })
    assert env.ok, env
    return env.data["id"]


def _embedding_rows(home: Path):
    conn = sqlite3.connect(str(home / "trade-trace.sqlite"))
    try:
        return conn.execute(
            "SELECT node_id, provider, model_id, dim, length(embedding) "
            "FROM memory_node_embeddings ORDER BY node_id, provider, model_id"
        ).fetchall()
    finally:
        conn.close()


def test_memory_reindex_preview_no_write(home):
    _retain_memory(home, "00000000-0000-4000-8000-reindex001", "alpha memory")
    _retain_memory(home, "00000000-0000-4000-8000-reindex002", "beta memory")
    _mcp(home, "journal.config_set", {"key": "embeddings.provider", "value": "none", "_confirm": True})
    conn = sqlite3.connect(str(home / "trade-trace.sqlite"), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO config(key, value, updated_at) VALUES ('embeddings.provider', 'local', 'now') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        before = _embedding_rows(home)
    finally:
        conn.close()

    env = _mcp(home, "memory.reindex", {})

    assert env.ok, env
    assert env.meta.preview_only is True
    assert env.data["preview_only"] is True
    assert env.data["would_reindex"]["provider"] == "local"
    assert env.data["would_reindex"]["node_count"] == 2
    assert env.data["would_reindex"]["cost_estimate"]["estimated_usd"] == 0.0
    assert _embedding_rows(home) == before


def test_memory_reindex_confirm_round_trip_embedding_count_matches_memory_nodes(home):
    node_ids = [
        _retain_memory(home, "00000000-0000-4000-8000-reindex101", "gamma memory"),
        _retain_memory(home, "00000000-0000-4000-8000-reindex102", "delta memory"),
    ]
    conn = sqlite3.connect(str(home / "trade-trace.sqlite"), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO config(key, value, updated_at) VALUES ('embeddings.provider', 'local', 'now') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        for node_id in node_ids:
            conn.execute(
                "INSERT INTO memory_node_embeddings(node_id, provider, dim, model_id, embedding, created_at) "
                "VALUES (?, 'local', 2, 'old-model', ?, 'old')",
                (node_id, b"12345678"),
            )
    finally:
        conn.close()

    env = _mcp(home, "memory.reindex", {"_confirm": True})

    assert env.ok, env
    assert env.data["preview_only"] is False
    if env.data.get("degraded") is True:
        assert env.data["reindexed_count"] == 0
        # Missing local assets/deps must not delete previously stored provider rows.
        rows = _embedding_rows(home)
        assert len(rows) == 2
        assert {row[0] for row in rows} == set(node_ids)
        assert {row[1:] for row in rows} == {("local", "old-model", 2, 8)}
    else:
        assert env.data["reindexed_count"] == 2
        rows = _embedding_rows(home)
        assert len(rows) == 2
        assert {row[0] for row in rows} == set(node_ids)
        assert {row[1] for row in rows} == {"local"}
        assert {row[2] for row in rows} == {env.data["model_id"]}
        assert {row[3] for row in rows} == {384}
        assert {row[4] for row in rows} == {384 * 4}


def test_memory_reindex_confirm_failure_rolls_back_prior_provider_state(home, monkeypatch):
    node_ids = [
        _retain_memory(home, "00000000-0000-4000-8000-reindex201", "epsilon memory"),
        _retain_memory(home, "00000000-0000-4000-8000-reindex202", "zeta memory"),
    ]
    conn = sqlite3.connect(str(home / "trade-trace.sqlite"), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO config(key, value, updated_at) VALUES ('embeddings.provider', 'local', 'now') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        for node_id in node_ids:
            conn.execute(
                "INSERT INTO memory_node_embeddings(node_id, provider, dim, model_id, embedding, created_at) "
                "VALUES (?, 'local', 2, 'old-model', ?, 'old')",
                (node_id, f"old:{node_id}".encode()),
            )
        before = _embedding_rows(home)
    finally:
        conn.close()

    from trade_trace.tools import admin

    class _FailSecondEmbedder:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def embed(self, _body):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("injected embedding failure")
            return [1.0] + [0.0] * 383

    monkeypatch.setattr(admin, "_verify_model_dir", lambda _target: {"verified_files": ["config.json"]})
    monkeypatch.setattr(admin, "LocalOnnxEmbedder", _FailSecondEmbedder)
    with pytest.raises(RuntimeError, match="injected embedding failure"):
        _mcp(home, "memory.reindex", {"_confirm": True})

    assert _embedding_rows(home) == before


# -- deferred stubs -------------------------------------------


def test_model_warm_degrades_when_local_model_assets_are_absent(home):
    env = _mcp(home, "model.warm", {})
    assert env.ok is True
    assert env.data["warmed"] is False
    assert env.data["available"] is False
    assert env.data["reason"] in {"ToolError", "LocalEmbeddingUnavailable"}
