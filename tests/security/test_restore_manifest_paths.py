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
