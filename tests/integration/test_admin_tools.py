"""Admin tool surface per bead trade-trace-2z7.

10 admin tools registered + per-tool happy-path + --confirm/preview
contract on mutating ones.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _mcp(home: Path, tool: str, args: dict | None = None):
    payload = {"home": str(home), **(args or {})}
    return mcp_call(tool, payload, actor_id="agent:default")


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
]


@pytest.mark.parametrize("tool", ADMIN_TOOLS)
def test_admin_tool_registered(tool):
    assert tool in default_registry().names()


def test_admin_config_set_description_documents_embeddings_behavior():
    desc = default_registry().get("journal.config_set").description.lower()
    assert "enum {none, local, api:openai}" in desc
    assert "secure os keyring" in desc
    assert "noninteractive" in desc
    assert "no openai network call" in desc
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


def test_journal_config_set_embeddings_provider_none_succeeds(home):
    env = _mcp(home, "journal.config_set", {
        "key": "embeddings.provider", "value": "none",
        "_confirm": True,
    })
    assert env.ok


def test_journal_config_set_embeddings_provider_api_preview_without_key(home):
    """Previewing API provider switch does not require or persist an API key."""

    env = _mcp(home, "journal.config_set", {
        "key": "embeddings.provider", "value": "api:openai",
    })
    assert env.ok is True
    assert env.data["preview_only"] is True
    assert env.data["would_write"]["value"] == "api:openai"


def test_journal_config_set_embeddings_provider_rejects_unknown_value(home):
    """Values outside the closed enum {none, local, api:openai} are
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


def test_config_set_embeddings_provider_local_lazy_download_first_switch(home, monkeypatch):
    payload = b"deterministic tiny bge-small test fixture\n"
    admin = _patch_tiny_trusted_lock(monkeypatch, payload)
    calls = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return payload

    def _fake_urlopen(url, *, timeout):
        calls.append((url, timeout))
        assert url == f"{admin.BGE_SMALL_HF_BASE_URL}/config.json"
        return _Response()

    monkeypatch.setattr(admin.urllib.request, "urlopen", _fake_urlopen)
    first = _mcp(home, "journal.config_set", {
        "key": "embeddings.provider", "value": "local", "_confirm": True,
    })
    assert first.ok, first
    assert first.data["model"]["downloaded"] is True
    assert calls == [(f"{admin.BGE_SMALL_HF_BASE_URL}/config.json", 300)]

    second = _mcp(home, "journal.config_set", {
        "key": "embeddings.provider", "value": "local", "_confirm": True,
    })
    assert second.ok, second
    assert second.data["model"]["downloaded"] is False
    assert calls == [(f"{admin.BGE_SMALL_HF_BASE_URL}/config.json", 300)]


def test_download_rejects_bad_trusted_lock_path_before_urlopen(home, monkeypatch):
    from trade_trace.tools import admin

    monkeypatch.setattr(admin, "_trusted_bge_small_lock", lambda: ({
        "path": "../escape.bin", "size": 1, "sha256": "0" * 64,
    },))

    def _fail_urlopen(*args, **kwargs):
        raise AssertionError("urlopen must not be called for invalid lock paths")

    monkeypatch.setattr(admin.urllib.request, "urlopen", _fail_urlopen)
    env = _mcp(home, "journal.config_set", {
        "key": "embeddings.provider", "value": "local", "_confirm": True,
    })
    assert env.ok is False
    assert env.error.code.value == "INVARIANT_VIOLATION"
    assert not (home / "escape.bin").exists()


# -- deferred stubs -------------------------------------------


@pytest.mark.parametrize("tool", ["model.warm", "memory.reindex"])
def test_deferred_stub_returns_unsupported_with_bead_link(home, tool):
    env = _mcp(home, tool, {})
    assert env.ok is False
    assert env.error.code.value == "UNSUPPORTED_CAPABILITY"
    assert env.error.details["deferred_to_bead"] == "trade-trace-a4p"
