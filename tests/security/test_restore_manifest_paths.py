"""journal.restore must reject malicious manifest paths (trade-trace-l24k).

A backup manifest with `../../evil.txt` or `/etc/passwd` in `files[*].path`
must be rejected before any file write so a tampered manifest cannot
write/corrupt files outside `$TRADE_TRACE_HOME` with the process's
permissions.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}, actor_id="agent:default").ok
    return h


def _make_manifest_dir(parent: Path, files: list[tuple[str, bytes]]) -> Path:
    """Create a manifest dir under `parent` with the supplied
    `(relative_path, body)` entries. Each entry's body is placed at the
    `src_path / entry.path` resolution so the existing hash-verify loop
    cannot incidentally reject the traversal attempt — the regression must
    catch the bug at the path-validation layer, not by missing-file luck."""

    src = parent / "src"
    src.mkdir(parents=True, exist_ok=True)
    entries = []
    for rel, body in files:
        candidate = (src / rel)
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(body)
        entries.append({
            "path": rel,
            "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })
    manifest = {"files": entries, "created_at": "2026-05-19T00:00:00.000Z"}
    (src / "manifest.json").write_text(json.dumps(manifest))
    return src


def _make_manifest_only(parent: Path, manifest_path_value) -> Path:
    src = parent / f"src-{len(list(parent.glob('src-*')))}"
    src.mkdir(parents=True, exist_ok=True)
    manifest = {
        "files": [{
            "path": manifest_path_value,
            "size": 5,
            "sha256": hashlib.sha256(b"pwned").hexdigest(),
        }],
        "created_at": "2026-05-19T00:00:00.000Z",
    }
    (src / "manifest.json").write_text(json.dumps(manifest))
    return src


def test_journal_restore_rejects_parent_traversal(tmp_path, home):
    """A manifest entry with `..` segments must be rejected with
    VALIDATION_ERROR and `details.field == "path"` BEFORE any disk read
    or copy. The fix must reject at path-validation, not by incidental
    missing-file failure (trade-trace-l24k)."""

    src = _make_manifest_dir(tmp_path, [("../evil.txt", b"pwned")])
    env = mcp_call(
        "journal.restore",
        {
            "home": str(home),
            "src": str(src),
            "_confirm": True,
            "idempotency_key": "l24k-traversal",
        },
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "path"
    assert env["error"]["details"]["manifest_path"] == "../evil.txt"


def test_journal_restore_rejects_absolute_path(tmp_path, home):
    """A manifest entry with an absolute path must be rejected with
    VALIDATION_ERROR before any copy. Without the path-validation guard,
    `home / "/abs/path"` evaluates to `/abs/path` (Python's `/` operator
    on an absolute right-hand side returns the absolute path verbatim),
    so a tampered manifest could write anywhere the process can reach."""

    src = tmp_path / "src"
    src.mkdir()
    # Stage a benign file inside src and reference it via an absolute
    # path in the manifest. The validator must reject before resolving
    # the absolute path.
    benign = src / "x.bin"
    benign.write_bytes(b"pwned")
    import hashlib as _h
    manifest = {
        "files": [{
            "path": "/etc/passwd-evil",
            "size": 5,
            "sha256": _h.sha256(b"pwned").hexdigest(),
        }],
        "created_at": "2026-05-19T00:00:00.000Z",
    }
    (src / "manifest.json").write_text(json.dumps(manifest))
    env = mcp_call(
        "journal.restore",
        {
            "home": str(home),
            "src": str(src),
            "_confirm": True,
            "idempotency_key": "l24k-absolute",
        },
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "path"
    assert env["error"]["details"]["manifest_path"] == "/etc/passwd-evil"


@pytest.mark.parametrize(
    ("manifest_path", "case"),
    [
        ("C:/Users/Public/evil.db", "windows-drive"),
        ("", "empty"),
        (123, "non-string"),
    ],
)
def test_journal_restore_rejects_other_unsafe_manifest_paths(tmp_path, home, manifest_path, case):
    """Characterize restore-specific details for generic unsafe path cases."""

    src = _make_manifest_only(tmp_path, manifest_path)
    env = mcp_call(
        "journal.restore",
        {
            "home": str(home),
            "src": str(src),
            "_confirm": True,
            "idempotency_key": f"d2jv-{case}",
        },
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"] == {
        "field": "path",
        "manifest_path": manifest_path,
        "reason": "unsafe_manifest_path",
    }


def test_journal_restore_accepts_valid_relative_paths(tmp_path, home):
    """A normal manifest with relative-only paths (`trade-trace.sqlite`,
    `outbox/foo.jsonl`) must still restore successfully."""

    src = _make_manifest_dir(
        tmp_path,
        [
            ("trade-trace.sqlite", b"sqlite-bytes"),
            ("outbox/foo.jsonl", b'{"line": 1}\n'),
        ],
    )
    env = mcp_call(
        "journal.restore",
        {
            "home": str(home),
            "src": str(src),
            "_confirm": True,
            "idempotency_key": "l24k-valid",
        },
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is True, env
    assert (home / "trade-trace.sqlite").exists()
    assert (home / "outbox/foo.jsonl").exists()


# -- bead trade-trace-jm14: malformed manifest must fail cleanly --------
#
# A tampered or hand-written manifest can omit the `files` array or
# individual `path` / `sha256` keys. journal.restore must surface a clean
# VALIDATION_ERROR instead of letting a raw KeyError escape as an unhandled
# internal error.


def _write_manifest(tmp_path: Path, manifest: dict) -> Path:
    src = tmp_path / f"src-{len(list(tmp_path.glob('src-*')))}"
    src.mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").write_text(json.dumps(manifest))
    return src


def test_journal_restore_rejects_manifest_missing_files_array(tmp_path, home):
    src = _write_manifest(tmp_path, {"created_at": "2026-05-19T00:00:00.000Z"})
    env = mcp_call(
        "journal.restore",
        {"home": str(home), "src": str(src), "_confirm": True,
         "idempotency_key": "jm14-no-files"},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["reason"] == "missing_files"


@pytest.mark.parametrize(
    ("entry", "case"),
    [
        ({"sha256": "deadbeef"}, "missing-path"),
        ({"path": "trade-trace.sqlite"}, "missing-sha256"),
        ("not-a-dict", "non-dict-entry"),
    ],
)
def test_journal_restore_rejects_manifest_entry_missing_keys(tmp_path, home, entry, case):
    src = _write_manifest(
        tmp_path,
        {"files": [entry], "created_at": "2026-05-19T00:00:00.000Z"},
    )
    env = mcp_call(
        "journal.restore",
        {"home": str(home), "src": str(src), "_confirm": True,
         "idempotency_key": f"jm14-{case}"},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["reason"] == "incomplete_entry"


# -- bead trade-trace-g86k: symlink rejection in backup/restore --------
#
# A hostile backup directory can plant symlinks that pivot a read at copy
# time to an arbitrary file the hash check never saw, or point manifest.json
# itself at an out-of-tree file. journal.restore must reject both before any
# bytes are read for restore.


def test_journal_restore_rejects_out_of_tree_symlink_escape(tmp_path, home):
    """A manifest entry whose *src* file is a symlink to an OUT-OF-TREE
    target is rejected at the path-containment layer (the symlink resolves
    outside the backup source), before any bytes are read. This is the
    strongest rejection — the symlink can never even be hashed
    (bead trade-trace-g86k / trade-trace-l24k)."""

    outside = tmp_path / "outside_secret.bin"
    outside.write_bytes(b"top-secret-outside-the-backup")

    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "evil_link.db").symlink_to(outside)

    manifest = {
        "files": [{
            "path": "evil_link.db",
            "size": outside.stat().st_size,
            "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
        }],
        "created_at": "2026-05-19T00:00:00.000Z",
    }
    (src / "manifest.json").write_text(json.dumps(manifest))

    env = mcp_call(
        "journal.restore",
        {"home": str(home), "src": str(src), "_confirm": True,
         "idempotency_key": "g86k-symlink-escape"},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "path"
    # The symlink target was never restored into home.
    assert not (home / "evil_link.db").exists()


def test_journal_restore_rejects_in_tree_symlink_source(tmp_path, home):
    """A manifest entry whose *src* file is a symlink whose target stays
    INSIDE the backup source (so it passes the path-containment check) must
    still be rejected by the explicit symlink-source guard — only regular
    files journal.backup wrote are trusted (bead trade-trace-g86k)."""

    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    # A real file inside src, and a symlink (also inside src) pointing at it.
    real = src / "real.db"
    real.write_bytes(b"real-bytes")
    (src / "alias.db").symlink_to(real)

    manifest = {
        "files": [{
            "path": "alias.db",
            "size": real.stat().st_size,
            "sha256": hashlib.sha256(real.read_bytes()).hexdigest(),
        }],
        "created_at": "2026-05-19T00:00:00.000Z",
    }
    (src / "manifest.json").write_text(json.dumps(manifest))

    env = mcp_call(
        "journal.restore",
        {"home": str(home), "src": str(src), "_confirm": True,
         "idempotency_key": "g86k-symlink-in-tree"},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["reason"] == "symlink_source"
    assert not (home / "alias.db").exists()


def test_journal_restore_rejects_symlinked_manifest(tmp_path, home):
    """A backup directory whose manifest.json is itself a symlink (to an
    arbitrary on-disk file) must be rejected before the manifest is read
    (bead trade-trace-g86k)."""

    real_manifest = tmp_path / "real_manifest.json"
    real_manifest.write_text(json.dumps(
        {"files": [], "created_at": "2026-05-19T00:00:00.000Z"}
    ))
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").symlink_to(real_manifest)

    env = mcp_call(
        "journal.restore",
        {"home": str(home), "src": str(src), "_confirm": True,
         "idempotency_key": "g86k-symlink-manifest"},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["reason"] == "symlink_manifest"


def test_journal_backup_skips_symlinked_jsonl(tmp_path, home):
    """journal.backup must not follow a symlink planted under
    export/jsonl into a backup: a symlinked entry is skipped so an
    arbitrary out-of-tree file cannot be pulled into the backup (and thus
    into a later restore) (bead trade-trace-g86k)."""

    # An out-of-tree secret the attacker wants to exfiltrate via backup.
    secret = tmp_path / "outside_secret.jsonl"
    secret.write_text('{"secret": "do-not-back-me-up"}\n', encoding="utf-8")

    jsonl_dir = home / "export" / "jsonl"
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    # A legitimate real file the backup SHOULD capture.
    real = jsonl_dir / "real.jsonl"
    real.write_text('{"line": 1}\n', encoding="utf-8")
    # A hostile symlink the backup MUST skip.
    (jsonl_dir / "evil.jsonl").symlink_to(secret)

    dest = tmp_path / "backup"
    env = mcp_call(
        "journal.backup",
        {"home": str(home), "dest": str(dest), "_confirm": True,
         "idempotency_key": "g86k-backup-symlink"},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is True, env

    manifest = json.loads((dest / "manifest.json").read_text())
    backed_up_paths = {entry["path"] for entry in manifest["files"]}
    # The real file is captured; the symlink target is not.
    assert "export/jsonl/real.jsonl" in backed_up_paths
    assert "export/jsonl/evil.jsonl" not in backed_up_paths
    assert not (dest / "export" / "jsonl" / "evil.jsonl").exists()
