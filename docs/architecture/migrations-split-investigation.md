# Migration module split — investigation (SIMP-003)

> Status: **decision document for trade-trace-6x3j** (investigation +
> recommendation). No code or test changes in this document.

## Problem

`src/trade_trace/storage/migrations.py` is 1,361 lines and combines:

- FTS5 capability probe (`_require_fts5`)
- 10 numbered migration functions (`_migration_001_meta`,
  `_migration_002_event_log`, … through
  `_migration_010_strategy_id_new_row_triggers`)
- append-only / new-row trigger SQL embedded inside several migrations
- the `MIGRATIONS` registry (the ordered list the runner walks)
- the `_MIGRATION_TABLES_CREATED` and (per trade-trace-n1mm)
  `_MIGRATION_COLUMNS_ADDED` fingerprints used by
  `_assert_schema_matches_meta`
- the `SchemaMetaMismatchError` exception class
- the `apply_pending_migrations` runner and the
  `current_version` / `_record_version` helpers

Migration 003 alone defines the entire core ledger schema, indexes,
and append-only triggers, and is roughly 250 lines on its own.

This module is read on every operator/agent session via
`apply_pending_migrations` and read on every PR by reviewers who
want to understand a single migration. The size penalizes both
audiences.

## Design constraints

1. **Schema equivalence is load-bearing.** Splitting cannot change
   the bytes any migration ALTER/CREATE statement emits. A
   pre-existing journal must restore byte-identically post-split.
2. **Migration order is canonical.** The numbered ordering of
   `MIGRATIONS` is the contract; any split must keep that ordering
   intact.
3. **Public imports must not break.** Other modules and tests
   import `apply_pending_migrations`, `current_version`,
   `SchemaMetaMismatchError`, and the `_MIGRATION_TABLES_CREATED`
   constant from `trade_trace.storage.migrations`.

## Choices considered

### A. Keep a single file, factor helpers only

Extract just the trigger-SQL templates (the append-only / new-row
pattern that recurs) into a module-level helper. The migration
functions still live inline.

**Cost:** small.
**Carrying risk:** does not address the "I have to scroll past 9
unrelated migrations to read migration 7" complaint. The trigger
extraction is a minor saving (≤80 lines).
**Recommendation:** insufficient on its own.

### B. Per-migration module under `storage/migrations/`

Convert `storage/migrations.py` into a package
`storage/migrations/__init__.py` that imports each migration from a
sibling module:

```
storage/migrations/__init__.py    # re-exports + registry
storage/migrations/_runner.py     # apply_pending_migrations,
                                  # SchemaMetaMismatchError,
                                  # _assert_schema_matches_meta
storage/migrations/m001_meta.py
storage/migrations/m002_event_log.py
...
storage/migrations/m010_strategy_id.py
```

The package `__init__.py` keeps every existing public name
re-exported, so callers don't change their imports. Each migration
module owns its own DDL + any migration-specific constants.

**Cost:** moderate. ~10 new files; one rename of the existing module
to a package. Test fixture point at `apply_pending_migrations` and
`current_version` keep working unchanged.
**Carrying risk:** the `MIGRATIONS` list now lives in `__init__.py`
with explicit imports per number. Adding a new migration requires
two edits (new file + the registry entry); the existing
single-file design requires the same two edits in one file.
Marginal.
**Recommendation:** **adopt**. The reader gains a clean per-migration
file boundary; the runner gains nothing but a small relative-import
chain; nothing else moves.

### C. Generic migration framework

Replace the hand-rolled runner with something like `alembic` or
`yoyo-migrations`.

**Cost:** very high (storage contract surface).
**Carrying risk:** introduces a third-party dependency on the data
path, changes how migrations are written, and forces a redesign of
the schema/meta mismatch diagnostic.
**Recommendation:** reject. The hand-rolled runner is small and
auditable; the win from a framework is mostly cosmetic.

## Recommendation

Adopt **option (B): per-migration module under `storage/migrations/`**,
scoped narrowly:

1. Convert `storage/migrations.py` → `storage/migrations/` package.
   `__init__.py` re-exports every name `migrations.py` currently
   exposes (`apply_pending_migrations`, `current_version`,
   `SchemaMetaMismatchError`, `MIGRATIONS`,
   `_MIGRATION_TABLES_CREATED`, `_MIGRATION_COLUMNS_ADDED`,
   `_assert_schema_matches_meta`). Existing imports keep working.
2. Move each `_migration_NNN_*` function into a separate file
   `m001_meta.py` … `m010_strategy_id.py`. Each file holds **only**
   the DDL for that migration plus a one-line docstring at the top.
3. Move the runner (`apply_pending_migrations`, `current_version`,
   `_record_version`, `_require_fts5`, `_assert_schema_matches_meta`)
   into `_runner.py`. `SchemaMetaMismatchError` moves with it.
4. The `MIGRATIONS` list, the `_MIGRATION_TABLES_CREATED` table-
   fingerprint, and the `_MIGRATION_COLUMNS_ADDED` column-fingerprint
   stay in `__init__.py` so a single file ties version numbers to
   migration callables and to the schema/meta mismatch diagnostic.

### Schema-equivalence harness

The investigation deliverable is the harness, not the refactor. Add
a regression test under
`tests/integration/test_migrations_schema_hash.py`:

1. Apply every migration against a fresh DB and capture
   `sqlite_master.sql` (a snapshot of every CREATE statement) and
   `PRAGMA table_info(<each table>)` (column order/type/nullability).
2. Hash both with `hashlib.sha256` of canonical JSON.
3. Pin the resulting two hashes as the expected values. Any future
   migration tweak (intentional schema change OR an accidental
   split-time drift) flips the hash and the test fails loudly.

The harness is intentionally **structural**, not value-based: it
catches DDL drift even when the runtime tests pass. The follow-up
implementation bead is gated on this harness landing first; the
refactor PR's acceptance is "harness hashes do not change."

## Out of scope

- Replacing the hand-rolled runner with a third-party framework.
- Splitting migration 003 (the big one) into smaller "phases."
  Migration order is canonical; phase-splitting a landed migration
  would invalidate every existing journal.
- Auto-generating migration files from a schema model.

## Follow-up beads (filed)

The investigation explicitly does NOT do the refactor; two beads
break the implementation work into bounded, reviewable PRs:

- (Follow-up A) Add the schema-equivalence harness
  (`tests/integration/test_migrations_schema_hash.py`). Lands before
  any code split.
- (Follow-up B) Split `storage/migrations.py` into the
  `storage/migrations/` package per option (B). Acceptance: harness
  hashes from (A) unchanged; existing imports unchanged; full
  pytest + mypy + ruff clean.
