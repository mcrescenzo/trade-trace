# Lane 1 status: completed

Read-only simplification review completed for storage/events/import-export/security boundaries in /home/hermes/code/trade-trace.

What I did:
- Verified repo preflight:
  - HEAD: ffcd97420bf44c846451bd5d39596d39437d6e3e
  - Branch: main
- Inspected in-scope modules:
  - src/trade_trace/storage/
  - src/trade_trace/events/
  - src/trade_trace/exporter.py
  - src/trade_trace/security/
  - src/trade_trace/tools/admin.py backup/restore/config paths
  - tests/integration/test_migrations*.py
  - tests/integration/test_outbox_export.py
  - tests/security/
- Ran targeted validation:
  - uv run pytest tests/integration/test_outbox_export.py tests/integration/test_migrations.py tests/integration/test_migrations_schema_hash.py tests/security -q
  - Result: 232 passed in 2.41s

Files created or modified:
- None. Read-only lane respected: no edits, no Beads writes, no memory/Hindsight, no push/publish/delete.

Findings: simplification candidates

1. Consolidate file/directory permission helpers across storage, exporter, and admin

Evidence:
- src/trade_trace/storage/database.py:51-75
  - _set_user_only_permissions()
  - _set_user_only_dir_permissions()
- src/trade_trace/storage/database.py:78-89
  - _chmod_wal_shm_siblings()
- src/trade_trace/tools/admin.py:49-70
  - _tighten_file()
  - _tighten_dir()
- src/trade_trace/exporter.py:156-208
  - inline import stat, chmod final file to 0600, chmod date-bucket parent dirs to 0700

Why this is a simplification candidate:
- The same security boundary is implemented in three places with slightly different names and comments:
  - file chmod 0600
  - directory chmod 0700
  - best-effort POSIX-only behavior
- This creates test drag: security permission tests must indirectly cover multiple near-identical implementations.
- It also creates maintenance drift risk if one path gains a new platform exception or stricter behavior and the others do not.

Behavior-preserving simplification:
- Extract shared helpers into a small internal module, e.g. src/trade_trace/storage/permissions.py or src/trade_trace/security/filesystem.py:
  - chmod_user_only_file(path: Path) -> None
  - chmod_user_only_dir(path: Path) -> None
  - chmod_user_only_parents_until(path: Path, stop: Path) -> None, if desired
- Keep existing semantics:
  - no-op on non-POSIX
  - suppress OSError/PermissionError/NotImplementedError as currently appropriate
  - no behavior changes to backup/export/database creation

Validation commands:
- uv run pytest tests/security/test_file_permissions.py tests/integration/test_outbox_export.py tests/integration/test_admin_tools.py -q
- Also rerun full targeted lane command above.

Suggested backlog shape:
- New simplification item, bounded.
- Label: simplification:20260520
- Domain: storage-events-security


2. Extract a generic safe-relative-path/resolve-under-root helper for restore and model import paths

Evidence:
- src/trade_trace/tools/admin.py:129-145
  - _safe_model_relpath()
  - _resolve_under()
- src/trade_trace/tools/admin.py:447-500
  - journal.restore reuses _safe_model_relpath() for manifest entries, then manually repeats root containment checks for both source and destination paths
- src/trade_trace/tools/admin.py:459-473
  - restore catches ToolError from _safe_model_relpath() and remaps the model-specific error into restore-specific validation details
- src/trade_trace/tools/admin.py:474-499
  - repeated source-root and home-root containment checks

Why this is a simplification candidate:
- The path validation behavior is good, but the abstraction name is model-specific while restore now depends on it.
- journal.restore has to wrap/rephrase model-oriented errors, which is a contract smell and increases cognitive load at a security boundary.
- The same pattern is likely useful in multiple “copy from manifest/import tree into home” surfaces:
  - reject empty/non-string
  - reject absolute paths
  - reject Windows drives
  - reject ..
  - resolve under root and ensure containment after symlink resolution

Behavior-preserving simplification:
- Extract generic helpers, for example:
  - safe_relative_path(rel: str, *, field: str = "path") -> Path
  - resolve_under(root: Path, rel: str | Path, *, field: str = "path") -> Path
- Let model import and journal.restore call the same generic helper but provide domain-specific error messages/details at call boundaries.
- Preserve current restore behavior:
  - reject traversal/absolute/Windows-drive paths before copy
  - reject resolved source outside backup src
  - reject resolved destination outside TRADE_TRACE_HOME
  - keep current ErrorCode.VALIDATION_ERROR for restore manifest path failures

Validation commands:
- uv run pytest tests/security/test_restore_manifest_paths.py tests/integration/test_admin_tools.py tests/integration/test_operability_drill.py -q

Suggested backlog shape:
- New simplification item, bounded.
- This is not a bug unless behavior changes; current tests pass.


3. Migration registry/fingerprint metadata is manually duplicated and can drift

Evidence:
- src/trade_trace/storage/migrations/__init__.py:43-54
  - MIGRATIONS ordered list
- src/trade_trace/storage/migrations/__init__.py:65-82
  - _MIGRATION_TABLES_CREATED version-indexed table fingerprints
- src/trade_trace/storage/migrations/__init__.py:91-119
  - _MIGRATION_COLUMNS_ADDED version-indexed column fingerprints
- src/trade_trace/storage/migrations/_runner.py:58-78
  - _registry() late-binds three parallel structures
- src/trade_trace/storage/migrations/_runner.py:151-177
  - _assert_schema_matches_meta() walks the separate fingerprint structures

Why this is a simplification candidate:
- Three parallel structures must stay aligned by version number:
  - migration callable order
  - tables-created fingerprint
  - columns-added fingerprint
- Comments say trigger drift is explicitly out of scope, so the fingerprint mechanism is intentionally limited, but the current representation still requires duplicate version bookkeeping.
- Adding a migration currently means touching multiple arrays correctly. The code is clear, but the contract is more fragile than necessary.

Behavior-preserving simplification:
- Introduce a small MigrationSpec dataclass:
  - version: int
  - apply: Callable[[sqlite3.Connection], None]
  - creates_tables: tuple[str, ...] = ()
  - adds_columns: Mapping[str, tuple[str, ...]] = {}
- Derive MIGRATIONS, _MIGRATION_TABLES_CREATED, and _MIGRATION_COLUMNS_ADDED from a single MIGRATION_SPECS tuple, or update _runner to consume specs directly.
- Preserve public exports if compatibility matters.

Validation commands:
- uv run pytest tests/integration/test_migrations.py tests/integration/test_migrations_schema_hash.py -q
- Consider adding one small test that spec versions are contiguous and equal to callable order.

Suggested backlog shape:
- New simplification item if the parent epic wants migration-maintenance reduction.
- Scope is moderate but bounded. Not a broad schema redesign.


4. JSONL envelope shaping is duplicated, but should probably merge into existing deadcode/serialization cleanup rather than become a new item

Evidence:
- src/trade_trace/events/log.py:81-102
  - EventRecord.to_jsonl_line()
  - builds {tool, args, _event_id, _event_type, _actor_id, _created_at, _contract_version}
- src/trade_trace/exporter.py:133-170
  - write_event_atomic()
  - builds the same JSONL envelope shape before writing to disk
- src/trade_trace/exporter.py:81-99
  - resolve_tool_for_event() used by both paths
- Existing context says deadcode hunt 20260520 covers EventRecord.to_jsonl_line.

Why this is a simplification candidate:
- There are two envelope-construction paths with the same contract.
- If EventRecord.to_jsonl_line is reachable, it should delegate to a shared envelope builder.
- If it is unreachable, the existing deadcode hunt already owns it.

Recommendation:
- Do not create a duplicate simplification bead unless parent confirms EventRecord.to_jsonl_line remains reachable.
- Prefer merging into the existing deadcode/serialization cleanup:
  - either remove EventRecord.to_jsonl_line if confirmed unused, or
  - extract build_jsonl_envelope(event_id, event_type, actor_id, created_at, payload, contract_version="1.0") and call it from both places.

Validation commands:
- uv run pytest tests/integration/test_outbox_export.py tests/integration/test_jsonl_atomic_write.py tests/integration/test_jsonl_replay_readiness.py -q

Disposition:
- Recommend merge into existing deadcode hunt / serialization cleanup, not a new simplification item.


5. Minor over-abstraction: events.unit_of_work.transaction() wrapper has negligible value but low priority

Evidence:
- src/trade_trace/events/unit_of_work.py:104-113
  - transaction(conn) contextmanager is just functional sugar around with UnitOfWork(conn)
- Usage:
  - src search found no production callers of events.unit_of_work.transaction()
  - tests/integration/test_transactions.py:145 uses it directly

Why this is a simplification candidate:
- It adds a second public entrypoint to the same transaction primitive.
- The finally: pass block is pure scaffolding.
- However this is very small and may fall under dead-code/low-value API cleanup rather than the storage/security simplification threshold.

Recommendation:
- Do not prioritize as a new simplification item unless API surface cleanup is in scope.
- If pursued, replace test usage with UnitOfWork directly and remove the wrapper, but check public contract expectations first.

Validation commands:
- uv run pytest tests/integration/test_transactions.py -q

Disposition:
- Low priority; likely below threshold for this lane.


Coverage accounting:
- storage/database.py: reviewed
- storage/paths.py: reviewed
- storage/policy.py: not deeply reviewed; only migration policy references checked
- storage/migrations/_runner.py: reviewed
- storage/migrations/__init__.py: reviewed
- storage/migrations/m001-m010: inventoried; not line-by-line audited beyond registry/fingerprint behavior
- events/log.py: reviewed
- events/unit_of_work.py: reviewed
- events/semantic_keys.py: reviewed
- exporter.py: reviewed
- security/patterns.py: reviewed
- security/keyring.py: reviewed, with delete_api_key intentionally not reported because existing deadcode context owns it
- tools/admin.py backup/restore/config paths: reviewed relevant lines
- tests/integration/test_migrations.py: included in validation
- tests/integration/test_migrations_schema_hash.py: included in validation
- tests/integration/test_outbox_export.py: reviewed and included in validation
- tests/security/: included in validation

Issues encountered:
- None blocking.
- One search command used an invalid combined path and returned “Path not found”; I reran the searches separately against src and tests.
- No repository files were changed.
