Read-only technical-debt review completed for:
- src/trade_trace/storage/*.py
- src/trade_trace/events/*.py
- src/trade_trace/models/*.py
- src/trade_trace/core.py
- src/trade_trace/clock.py
- src/trade_trace/timestamps.py
- src/trade_trace/version.py
- assigned integration/unit tests

Repository state:
- HEAD verified: a33e676ec9d22d6ec268686424521a3d2586f9dd
- Existing uncommitted changes were present before review in events/reports plus audits/docs; I did not modify anything.

Validation run:
- pytest -q tests/integration/test_migrations.py tests/integration/test_schema.py tests/integration/test_transactions.py tests/integration/test_idempotency.py tests/integration/test_append_only.py tests/integration/test_jsonl_atomic_write.py tests/integration/test_jsonl_contract.py tests/integration/test_jsonl_replay_readiness.py tests/test_timestamps.py
- Result: 92 passed in 0.84s

Files created/modified:
- None.

Candidates found:

1) Event log rows are mutable/deletable at the SQLite layer despite being the durable audit log

Disposition recommendation:
- Design / hardening debt. Possibly bug if the project’s append-only guarantee is intended to cover the events table itself.

Evidence:
- src/trade_trace/storage/migrations.py:42-104 creates events and outbox.
- src/trade_trace/storage/migrations.py:498-517 append-only trigger list includes snapshots, theses, forecasts, forecast_outcomes, forecast_scores, decisions, decision_tags, outcomes, sources, edges, position_events, but not events.
- src/trade_trace/storage/migrations.py:501-504 explicitly says events/outbox are not in the M1 append-only trigger list and have “own append-only rules in M0 migration 002”; however migration 002 does not create no-update/no-delete triggers for events.
- tests/integration/test_append_only.py:21-34 APPEND_ONLY_TABLES omits events and includes outbox mutability only as an exception test at lines 151-175.

Risk:
- The primary audit/event stream can be altered or deleted by any code path with SQLite write access, while ledger tables are protected. This weakens replay, JSONL export, idempotency investigation, and forensic trust.
- Outbox needs mutation, but events does not appear to.

Paydown:
- Add migration creating BEFORE UPDATE and BEFORE DELETE triggers on events only.
- Keep outbox mutable.
- Consider an explicit policy comment/test explaining why outbox remains mutable.

Validation:
- Add tests that UPDATE/DELETE on events raise “append-only invariant”.
- Re-run append-only, idempotency, JSONL replay/export tests.
- Confirm EventWriter inserts still work and outbox state transitions remain allowed.

Duplicate notes:
- Distinct from existing open themes: not embeddings/sqlite-vec/provider/reindex; not MCP/input schemas.

Proposed bead info:
- Title: Harden events table with SQLite append-only triggers
- Type: design / debt
- Priority: high
- Area: storage-persistence-events-schema
- Acceptance:
  - Migration adds events no-update/no-delete triggers.
  - tests/integration/test_append_only.py covers events mutation rejection.
  - outbox exporter mutation remains covered and passing.
  - Existing idempotency and JSONL tests still pass.


2) Strategy references remain unenforced after strategies table exists

Disposition recommendation:
- Design / schema debt with legacy-compat implications.

Evidence:
- src/trade_trace/storage/migrations.py:131-133 says strategy_id columns are reserved nullable TEXT with no FK because strategies table is M3.
- src/trade_trace/storage/migrations.py:223, 326 add strategy_id columns to theses/decisions in migration 003.
- src/trade_trace/storage/migrations.py:841-881 creates strategies in migration 007, but does not add FK enforcement or validation triggers to existing strategy_id columns.
- tests/integration/test_schema.py:245-270 explicitly asserts arbitrary decision.strategy_id is allowed even after all migrations are applied.

Risk:
- decisions/theses can reference nonexistent strategies, causing report.compare, strategy reports, and audit trails to group or link stale/orphan IDs.
- Once rows with arbitrary IDs exist, future FK migration requires cleanup/backfill policy.

Paydown:
- Decide legacy policy:
  - strict: rebuild affected tables with FK REFERENCES strategies(id), after orphan cleanup;
  - compatibility: add BEFORE INSERT triggers for new rows only and leave historical orphans flagged;
  - soft validation: write-tool validation plus orphan-report, but document DB does not enforce.
- If using triggers, cover both decisions.strategy_id and theses.strategy_id.

Validation:
- Test insertion with nonexistent strategy_id fails after migration or returns typed validation error via write tools.
- Test NULL strategy_id still allowed.
- Test existing historical rows behavior is intentional and documented.
- Test valid strategy_id succeeds.

Duplicate notes:
- Distinct from agent-ready input schema and embeddings themes.

Proposed bead info:
- Title: Enforce or explicitly grandfather strategy_id references now that strategies table exists
- Type: design / debt
- Priority: medium-high
- Area: storage-schema-core-models
- Acceptance:
  - A documented policy exists for legacy orphan strategy_id values.
  - New decisions/theses cannot silently point to nonexistent strategies unless explicitly grandfathered.
  - Tests cover valid, null, and invalid strategy_id cases.


3) Memory-layer migration unconditionally requires FTS5 although runtime has a detection helper

Disposition recommendation:
- Ops-deploy debt.

Evidence:
- src/trade_trace/storage/database.py:90-101 defines has_fts5(conn) by attempting to create a temp FTS5 table.
- src/trade_trace/storage/migrations.py:766-785 migration 006 unconditionally executes CREATE VIRTUAL TABLE memory_node_fts USING fts5(...).
- tests currently pass in this environment, but there is no fallback path in migration code if SQLite lacks FTS5.

Risk:
- SQLite builds without FTS5 cannot initialize or migrate the database at all, even if memory BM25 recall could degrade gracefully.
- This is especially relevant for distro/minimal Python builds, embedded environments, or constrained deployment targets.

Paydown:
- Choose required vs optional:
  - required: fail early with a clearer preflight error before partial migration attempts, and document package/system requirement;
  - optional: gate memory_node_fts creation on has_fts5 and store capability in meta/config, with recall returning UNSUPPORTED_CAPABILITY or using non-FTS fallback.
- Avoid silent half-capability: make report/init output expose FTS availability.

Validation:
- Monkeypatch/simulate CREATE VIRTUAL TABLE ... fts5 failure in migration test.
- Assert clear STORAGE_ERROR/UNSUPPORTED_CAPABILITY or successful degraded migration depending on chosen policy.
- Keep current FTS-enabled path covered.

Duplicate notes:
- This is FTS5/BM25 storage capability, not sqlite-vec/embeddings provider/reindex, so it should not duplicate the existing embeddings theme.

Proposed bead info:
- Title: Make FTS5 dependency explicit or gracefully optional for memory migrations
- Type: ops-deploy debt
- Priority: medium
- Area: storage-migrations-memory
- Acceptance:
  - Migration behavior is deterministic when FTS5 is unavailable.
  - journal.init or migration tests surface a clear capability error or degraded mode.
  - Memory recall behavior documents and tests the no-FTS path.


4) Timestamp invariants are enforced mainly at tool/helper boundary, not in storage schema

Disposition recommendation:
- Design / type-schema debt.

Evidence:
- src/trade_trace/timestamps.py:23-59 implements UTC ISO8601 normalization and rejects naive timestamps.
- Storage schema in src/trade_trace/storage/migrations.py stores many *_at fields as TEXT NOT NULL/nullable without CHECK constraints or validation triggers.
- Tests insert timestamp strings directly through sqlite3 in tests/integration/test_schema.py and test_append_only.py; they use valid Z strings, but schema itself does not reject invalid or naive text.
- tests/test_timestamps.py covers helper behavior, not database constraints.

Risk:
- Any direct SQLite path, future importer, migration seed, or test fixture can persist non-UTC/naive/malformed *_at values.
- Lexicographic ordering/indexes on created_at/resolved_at/captured_at can become unreliable if mixed formats enter storage.
- Bi-temporal validity filters can misbehave with malformed TEXT timestamps.

Paydown:
- Add a storage-level validation strategy for timestamp columns:
  - SQLite CHECK pattern for canonical Z format where practical;
  - or BEFORE INSERT triggers using strict glob/length patterns;
  - or centralized write API invariant plus schema-audit test if DB-level validation is intentionally avoided.
- Prioritize high-value columns: events.created_at, outbox.exported_at, decisions.created_at, outcomes.resolved_at/created_at, memory_nodes.valid_from/created_at.

Validation:
- Add tests that direct DB insert of naive/malformed created_at is rejected, or add explicit schema-audit tests documenting that DB layer intentionally delegates validation.
- Ensure to_utc_iso8601 tests remain passing.
- Verify report queries using ORDER BY created_at remain stable.

Duplicate notes:
- Distinct from MCP/input schema theme; this is persistence-layer invariant coverage.

Proposed bead info:
- Title: Add storage-level timestamp invariant coverage or explicit delegation policy
- Type: design / debt
- Priority: medium
- Area: storage-schema-timestamps
- Acceptance:
  - Timestamp enforcement boundary is documented.
  - Tests cover malformed/naive timestamp behavior at that boundary.
  - If DB-level enforcement is chosen, critical *_at columns reject invalid formats.


5) Migration idempotency is version-gated but individual later migration steps are not reentrant

Disposition recommendation:
- Migration robustness / recovery debt.

Evidence:
- src/trade_trace/storage/migrations.py docstring lines 3-7 says migrations are idempotent because version checks short-circuit and partial crashes are rolled back.
- apply_pending_migrations runs all pending migrations in one BEGIN/COMMIT at lines 1038-1050.
- Later migrations use plain CREATE TABLE, CREATE INDEX, CREATE TRIGGER, ALTER TABLE ADD COLUMN without IF NOT EXISTS / existence checks, e.g. migration 003 tables/triggers and migration 004 ALTER TABLE ADD COLUMN at lines 559-580.
- tests/integration/test_migrations.py covers clean application, reapply after schema_version advanced, and rollback on an exception in the same transaction. It does not cover partially-created schema with stale/missing meta caused by out-of-band corruption, manual recovery, or SQLite DDL edge cases.

Risk:
- If meta.schema_version is lost, edited backward, or a migration is partially applied outside the runner, recovery re-run may fail on “table already exists”, “duplicate column”, or “trigger already exists”.
- Operators get an opaque storage failure rather than a repair/audit path.

Paydown:
- Add a schema consistency/audit routine that compares meta.schema_version against actual schema objects before migrating.
- Either:
  - make migrations defensively reentrant where SQLite supports it; or
  - explicitly fail with actionable “schema/meta mismatch” guidance.
- Keep forward-only policy intact; this is not downgrade support.

Validation:
- Tests for meta.schema_version lower than actual tables.
- Tests for partial object existence before migration.
- Assert error message identifies schema/meta mismatch and suggested backup/repair path.

Duplicate notes:
- Not duplicative of existing themes.

Proposed bead info:
- Title: Add schema/meta consistency checks for migration recovery
- Type: investigation / debt
- Priority: medium
- Area: storage-migrations
- Acceptance:
  - Corrupt/stale meta is detected before raw DDL failures.
  - Error points to backup/repair guidance.
  - Clean migration and idempotent no-op behavior remain unchanged.


6) Polymorphic edges lack endpoint referential integrity

Disposition recommendation:
- Design / schema debt, probably intentional MVP tradeoff but should be tracked.

Evidence:
- src/trade_trace/storage/migrations.py:423-449 creates edges with source_kind/source_id/target_kind/target_id and CHECK enums, but no FK can enforce polymorphic targets.
- Comments at lines 417-422 describe endpoint kind enums expanding across milestones.
- No triggers validate that source_id/target_id exist in their corresponding table.

Risk:
- Edges can point to nonexistent rows, weakening source attachments, supersedes correction chains, playbook lineage, and memory graph traversal.
- Reports that join through edges may silently drop or misrepresent orphan edges.

Paydown:
- Add write-tool endpoint validation for all edge creation paths if not already complete.
- Add optional DB triggers per endpoint kind for core tables, or a schema-audit command/report listing orphan edges.
- Consider a normalized edge endpoint registry table if polymorphic triggers become unwieldy.

Validation:
- Tests inserting/creating edge to nonexistent endpoint fails via write tool.
- Add orphan-edge audit test/query.
- Ensure valid cross-entity edges still succeed.

Duplicate notes:
- Adjacent to schema/input validation, but persistence-specific; avoid duplicating agent-ready MCP/input-schema backlog unless that already covers edge endpoint existence.

Proposed bead info:
- Title: Validate polymorphic edge endpoints and audit orphan edges
- Type: design / debt
- Priority: medium
- Area: storage-events-ledger-models
- Acceptance:
  - Edge write paths reject nonexistent endpoints or document compatibility exception.
  - Orphan-edge audit exists.
  - Tests cover valid and invalid endpoint kinds/ids.


Coverage accounting:
- Reviewed storage connection/path/policy/migration code, event writer/UoW/semantic key code, ledger/memory models, dispatcher core, clock/timestamps/version, and assigned integration/unit tests.
- Executed all assigned tests; all passed.
- No read/write mutation was performed beyond running tests; no files changed.
- Existing repo working tree had unrelated preexisting modifications and untracked audit/doc files; left untouched.