# Schema/meta diagnostics for non-table migrations

> Status: **investigation + recommendation** for bead `trade-trace-3elt`.
> No code or test changes in this document. The recommended fix is filed
> as a follow-up bead before close.

## Problem

`_assert_schema_matches_meta` in `src/trade_trace/storage/migrations.py`
detects a stale `meta.schema_version` row by walking
`_MIGRATION_TABLES_CREATED` and asserting that no table claimed by a
not-yet-run migration already exists on disk. If one does, the
diagnostic raises `SchemaMetaMismatchError` with the offending names
and points the operator at `tt journal restore`.

This works for migrations that **create** tables, but migrations 004,
009, and 010 only **add columns and triggers**. Their table list is
empty, so they slip past the diagnostic. When a stale `meta` is
replayed through migration 004, the operator gets a raw
`OperationalError: duplicate column name: risk_unit_label` instead of
the documented mismatch envelope.

## Investigation

| Migration | Surface           | Currently detected? |
|-----------|-------------------|--------------------|
| 001       | creates `meta`    | yes                |
| 002       | creates events/outbox/config | yes     |
| 003       | creates 14 ledger tables | yes          |
| **004**   | **adds columns to forecasts/decisions/etc.** | **no** |
| 005       | creates `signals` | yes                |
| 006       | creates 4 memory tables | yes          |
| 007       | creates `strategies` | yes             |
| 008       | creates 3 playbook tables | yes        |
| **009**   | **adds `memory_node_embeddings` table** | yes (table-create)   |
| **010**   | **adds risk-unit columns** | **no**     |

(Migration 009 was listed as column-only in the bead description, but
inspection shows it creates a table — the diagnostic catches it.
Migrations 004 and 010 are the genuine gap.)

## Choices considered

1. **Out-of-scope**: document the limitation; rely on the operator
   reading the SQLite DDL error and matching it to the migration.
   *Cost:* free.
   *Carrying risk:* operators recovering under stress lose minutes to
   raw `sqlite3.OperationalError` traces.

2. **Column presence**: extend `_MIGRATION_TABLES_CREATED` to a richer
   `_MIGRATION_SCHEMA_FINGERPRINT` mapping that lists, per migration,
   `{table: [columns_added]}`. The diagnostic then walks not-yet-run
   migrations and asserts none of those columns already appear in
   `PRAGMA table_info(<table>)`.
   *Cost:* one constant + a `PRAGMA table_info` per affected table
   when the check runs (init time).
   *Carrying risk:* the constant must be kept in sync with the
   migration body. A new migration that adds columns without updating
   the constant silently re-opens the gap; CI catches it only if a
   test explicitly diffs migration SQL against the constant.

3. **Trigger presence**: enumerate trigger names per migration and
   check `sqlite_master` for them.
   *Cost:* similar to (2).
   *Carrying risk:* trigger DDL can be rewritten by future migrations,
   making exact-name matching brittle.

4. **Full schema hash**: snapshot the post-migration schema as a
   SHA-256 of canonical DDL, store it in `meta`, and compare on init.
   *Cost:* fingerprinting / canonicalization machinery.
   *Carrying risk:* over-broad — any whitespace change in a migration
   body invalidates the hash. Too tight for the recovery use case.

## Recommendation

Adopt **option (2): column presence**, scoped narrowly.

- Add `_MIGRATION_COLUMNS_ADDED: list[tuple[int, dict[str, list[str]]]]`
  alongside `_MIGRATION_TABLES_CREATED`. Migrations 004 and 010 get
  explicit `(version, {table: [col, …]})` entries; all others map to
  `{}`.
- Extend `_assert_schema_matches_meta` to walk both constants: for
  each not-yet-run migration, raise `SchemaMetaMismatchError` (with a
  new `unexpected_columns: dict[str, list[str]]` field) if any of the
  documented columns already exist in `PRAGMA table_info(table)`.
- Triggers are explicitly **out of scope** for this iteration. The
  trigger surface is small enough (no run of a column-only migration
  touches them in the historical set), and adding trigger fingerprints
  re-opens the brittleness question for negligible additional coverage.
- Update `docs/architecture/operability.md` §4 to mention the new
  column-fingerprint check so an operator who hits the diagnostic
  knows where to look.

### Why not strict-fail on unknown columns?

The diagnostic must remain **conservative**. If a future migration
adds a column that's not in the fingerprint constant, the check
silently misses it — but the existing "raw DDL error" failure mode is
preserved unchanged. We never want this check to fail on a legitimate
schema in production, so it errs toward false negatives, not false
positives.

## Validation plan (follow-up bead)

- A new regression test seeds a v3 (post-ledger-tables) DB, manually
  ALTERs in the migration 004 columns, then resets `meta.schema_version
  = 3` to simulate a "lost migration" scenario. `apply_pending_migrations`
  must raise `SchemaMetaMismatchError` carrying the offending columns,
  NOT the raw SQLite "duplicate column name" error.
- The existing migration policy tests in
  `tests/integration/test_migrations.py` must continue to pass.
- `mypy src` and `ruff check src tests` clean.

## Out of scope

- Trigger fingerprinting (see "Recommendation").
- Auto-repair of stale meta. The diagnostic is "tell the operator
  what's wrong"; repair is `tt journal restore` plus optional
  documented manual steps in operability.md §4.
- Schema hashes for full canonical-DDL comparison.
