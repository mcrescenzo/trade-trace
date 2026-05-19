What I did:
- Performed read-only inspection of the security/config/ops/exporter/package-runtime lane.
- Opened and reviewed relevant implementation, tests, workflow/config, and docs references.
- Ran safe local import/proof probes using temporary directories only.
- Did not edit files, create/update Beads, install packages, use network, or mutate repo/shared services.

Files opened/probed/search-reviewed:
- src/trade_trace/exporter.py
- src/trade_trace/security/patterns.py
- src/trade_trace/security/__init__.py
- src/trade_trace/security/keyring.py
- src/trade_trace/__init__.py
- src/trade_trace/tools/admin.py
- src/trade_trace/tools/__init__.py
- src/trade_trace/tools/cli.py partial via search/read
- src/trade_trace/contracts/tool_registry.py partial
- pyproject.toml
- .gitignore
- .github/workflows/ci.yml
- .github/workflows/workflow.yml
- .claude/settings.json
- tests/security/test_redacted_exports.py
- tests/security/test_secret_pattern_writes.py search-reviewed
- docs search-reviewed for export/security/config/package claims

Commands run/results:
- python probe using `python`: failed because `python` not found. This overlaps existing “python executable docs assumption” theme, not reported as new.
- `python3` direct import/proof probes:
  - `import trade_trace; import trade_trace.core` succeeded.
  - `import trade_trace.tools.admin` from a fresh process failed with circular ImportError.
  - `_journal_restore` path traversal proof using only `/tmp` succeeded in writing `/tmp/evil.txt` outside the requested restore home; cleanup removed the temp outside file.
- All probes were read-only with respect to repo files.

Files created/modified:
- No repository files created or modified.
- Temporary files under `/tmp` were created by proof probes and cleaned by tempdir cleanup; one `/tmp/evil.txt` proof file was explicitly removed.

Candidate records:

id: security-config-ops-001
title: journal.restore trusts manifest paths and can restore files outside TRADE_TRACE_HOME
severity: P1
confidence: confirmed
domain: security-config-ops
bug_class: unsafe restore path traversal / backup-restore filesystem write escape
evidence_type: static inspection + local runtime proof in temp dirs
evidence:
- src/trade_trace/tools/admin.py:409-413 documents `_journal_restore` as restoring DB + JSONL outbox “into `$TRADE_TRACE_HOME`”.
- src/trade_trace/tools/admin.py:449-464 verifies manifest entries by joining `src_path / entry["path"]`, but performs no validation that `entry["path"]` is relative, normalized, non-absolute, and free of `..`.
- src/trade_trace/tools/admin.py:468-473 then copies each entry using:
  - `src_file = src_path / entry["path"]`
  - `out_file = home / entry["path"]`
  - `out_file.parent.mkdir(parents=True, exist_ok=True)`
  - `shutil.copy2(src_file, out_file)`
- Because `Path / "../../evil.txt"` is accepted, a malicious or corrupted manifest can make `out_file` resolve outside `home`.
- Local proof command, in `/home/hermes/code/trade-trace`, using only temp paths:
  - Created backup at `/tmp/.../backups/b1`
  - Created manifest entry `../../evil.txt` with a valid SHA-256 for source file `/tmp/.../evil.txt`
  - Called `_journal_restore({"src": ..., "home": ..., "_confirm": True}, ctx)`
  - Observed output:
    - `{'preview_only': False, 'home': '/tmp/tmp5gvctiit/home', 'restored_count': 1, 'restored_files': ['../../evil.txt']}`
    - `/tmp/evil.txt` existed and contained the proof payload, outside `/tmp/tmp5gvctiit/home`
failure mode:
- An operator restoring a tampered backup can write arbitrary files outside the journal home wherever the current process has filesystem permission.
- This can corrupt unrelated files, plant files in parent directories, or overwrite sensitive local files if paths and permissions line up.
observed vs expected:
- Observed: restore accepts `../` manifest paths and copies outside the configured home.
- Expected: restore should reject absolute paths, Windows-drive paths, `..` components, symlinks where relevant, and any resolved output not strictly under `home`; it should verify/copy only allowlisted backup-relative paths such as the DB basename and `export/jsonl/**/*.jsonl`.
reproduction/trace path:
1. In a temp dir, create `src=/tmp/<root>/backups/b1` and `home=/tmp/<root>/home`.
2. Create source file `/tmp/<root>/evil.txt`.
3. Create `src/manifest.json` with:
   - `files: [{"path": "../../evil.txt", "sha256": <hash of /tmp/<root>/evil.txt>, "size": ...}]`
4. Invoke `_journal_restore({"src": str(src), "home": str(home), "_confirm": True}, ctx)`.
5. Observe restored file path resolves outside `home`, e.g. `/tmp/evil.txt`.
duplicate/overlap analysis:
- Not a duplicate of listed existing themes. It is materially different from docs command/link issues, exporter SECRET_PATTERNS alias, malformed CLI JSON, source secret persistence, and journal.config_set confirmation.
- It is in the backup/export/restore corruption/security scope.
proposed Bead body:
- `journal.restore` trusts manifest `files[*].path` values. It verifies `src_path / entry["path"]` and then copies to `home / entry["path"]` without rejecting absolute paths or `..` traversal. A tampered backup manifest can therefore write outside `$TRADE_TRACE_HOME` during confirmed restore. Add a restore path normalizer equivalent to the model import `_safe_model_relpath`/`_resolve_under` logic: reject absolute paths, Windows drive/absolute paths, `..` parts, non-string/empty paths, and resolved outputs outside the intended root. Also constrain accepted paths to the DB filename and `export/jsonl/**/*.jsonl` if that is the restore contract. Verify all hashes before copying and preserve the all-or-nothing behavior.
acceptance criteria:
- Restore rejects manifest entries with `..`, absolute POSIX paths, absolute/drive Windows paths, empty/non-string paths, and resolved output paths outside `$TRADE_TRACE_HOME`.
- Restore still accepts valid backup manifests produced by `journal.backup`.
- Regression test proves a manifest entry such as `../../evil.txt` returns an error and does not create/overwrite a file outside home.
- Regression test covers both verification and copy phases; no partial files are written for rejected manifests.
validation command:
- `python3 -m pytest tests/security tests/integration -q` or a narrower new test such as `python3 -m pytest tests/security/test_restore_manifest_paths.py -q`
risks/uncertainty:
- Confirmed via direct internal function call, not full CLI dispatch, because a separate direct-import issue exists. The vulnerable code path is the same handler registered for `journal.restore`.
- Did not mutate repo or run destructive commands; proof used temp paths only.

id: security-config-ops-002
title: Fresh direct import of trade_trace.tools.admin fails with circular ImportError
severity: P2
confidence: confirmed
domain: security-config-ops
bug_class: package runtime / importability regression
evidence_type: static inspection + import probe
evidence:
- src/trade_trace/tools/__init__.py:7-9 claims imports are kept thin to avoid circular references.
- src/trade_trace/tools/__init__.py:12 executes `from trade_trace.tools.errors import ToolError`.
- src/trade_trace/tools/errors.py imports `trade_trace.contracts.errors`.
- Python package import of `trade_trace.contracts.errors` first initializes `trade_trace/contracts/__init__.py`, which imports `trade_trace.contracts.grammar`; grammar imports `trade_trace.tools.errors`, re-entering the partially initialized module.
- Runtime proof from repo root:
  - Command:
    - `python3 - <<'PY' ... import trade_trace.tools.admin ... PY`
  - Output:
    - `ImportError cannot import name 'ToolError' from partially initialized module 'trade_trace.tools.errors' (most likely due to a circular import) (/home/hermes/code/trade-trace/src/trade_trace/tools/errors.py)`
- Control probe:
  - `import trade_trace; import trade_trace.core` succeeds in the same environment, so the failure is import-order dependent and can affect users/tests importing tool modules directly.
failure mode:
- Any consumer, test, docs example, or integration that imports `trade_trace.tools.admin` directly in a fresh process fails before reaching the admin tools.
- This also interfered with direct local verification of restore behavior until `trade_trace.core` was imported first.
observed vs expected:
- Observed: `import trade_trace.tools.admin` raises ImportError in a fresh Python process.
- Expected: public package modules under `trade_trace.tools.*` should be importable directly, especially admin/export/security surfaces used by tests and operators.
reproduction/trace path:
1. From `/home/hermes/code/trade-trace`, run:
   - `python3 - <<'PY'
try:
    import trade_trace.tools.admin
    print("admin import ok")
except Exception as e:
    print(type(e).__name__, str(e))
PY`
2. Observe circular ImportError from `trade_trace.tools.errors`.
duplicate/overlap analysis:
- Not the same as the existing exporter.SECRET_PATTERNS alias/pytest collection bug; that alias now exists at src/trade_trace/exporter.py:249-250.
- This is a separate package runtime import-order failure around `tools/__init__.py`, `tools/errors.py`, and `contracts/__init__.py`.
proposed Bead body:
- A fresh direct import of `trade_trace.tools.admin` fails due to a circular import. `tools/__init__.py` imports `ToolError`; `tools.errors` imports `trade_trace.contracts.errors`; importing a submodule initializes `contracts/__init__.py`, which imports grammar; grammar imports `tools.errors` again while partially initialized. Remove the eager `ToolError` re-export from `tools/__init__.py`, or change `tools.errors` to import the errors enum without triggering `contracts/__init__`, or otherwise break the package-level circular dependency. Add direct-import smoke tests for representative modules (`trade_trace.tools.admin`, `trade_trace.tools.errors`, `trade_trace.exporter`, `trade_trace.security`).
acceptance criteria:
- `python3 -c "import trade_trace.tools.admin"` succeeds in a fresh process.
- `python3 -c "import trade_trace.tools.errors"` succeeds in a fresh process.
- Existing `import trade_trace.core` and CLI/MCP startup remain successful.
- A regression test covers direct imports without relying on previous imports to mask the cycle.
validation command:
- `python3 - <<'PY'
import trade_trace.tools.admin
import trade_trace.tools.errors
import trade_trace.exporter
import trade_trace.security
print("ok")
PY`
risks/uncertainty:
- Core runtime import currently succeeds, so this may not break the normal CLI path in all import orders.
- Still operationally concrete for package consumers and direct tests; confirmed in a fresh process.

Areas inspected with no new report:
- exporter.py:
  - SECRET_PATTERNS alias exists at lines 249-250, avoiding the known duplicate theme.
  - Event type filename sanitization exists at lines 41-76.
  - JSONL tmp/final writes use `os.open(..., 0o600)`, `fsync`, `os.replace`, and final chmod at lines 162-190.
  - Export warnings intentionally avoid surfacing raw matched secrets in `secret_warnings` at lines 424-445.
- security/patterns.py:
  - Built-in patterns are centralized.
  - register() has name validation and source length cap.
  - scan_text input cap exists.
- security/keyring.py:
  - Keyring dependency is lazy.
  - Known insecure/null/plaintext backends are refused.
  - API key values are not returned from store and errors expose class name only.
- workflows:
  - CI runs on PR/main with read-only contents permission.
  - Publish workflow gates build on tests and uses OIDC id-token permission only for publish job.
- .gitignore:
  - Ignores sqlite DB/WAL/SHM and Beads credential key.
- .claude/settings.json:
  - Only `bd prime` hooks observed; no new product runtime finding.
- Tests/docs:
  - Existing known themes were intentionally not duplicated unless materially distinct.

Areas not fully inspected / why:
- Did not run full pytest, ruff, mypy, package build, or publish simulation because lane is read-only and requested targeted safe verification only; full test/build would be broader and potentially time-consuming.
- Did not inspect every docs audit artifact or Beads DB internals; only searched enough to avoid duplicate findings and ground relevant contracts.
- Did not exercise actual network/model download paths; no network allowed by lane.
- Did not run package installers or build tools; prohibited by task.

Side-effect caveats:
- No repo files changed.
- Temporary proof files were created under `/tmp`; the explicit outside proof file `/tmp/evil.txt` was removed by the proof script after verification.