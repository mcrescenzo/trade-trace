Read-only storage-events-models simplification review complete.

What I did:
- Confirmed repo/workdir and commit:
  - /home/hermes/code/trade-trace
  - HEAD 6f62a5f7a83cec823302bbe80892172b1e6936cb
- Read the simplification domain map:
  - /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z/domain-map.json
- Exhaustively inspected all 16 files listed for storage-events-models:
  - src/trade_trace/events/__init__.py
  - src/trade_trace/events/log.py
  - src/trade_trace/events/semantic_keys.py
  - src/trade_trace/events/unit_of_work.py
  - src/trade_trace/exporter.py
  - src/trade_trace/models/__init__.py
  - src/trade_trace/models/ledger.py
  - src/trade_trace/models/memory.py
  - src/trade_trace/projections.py
  - src/trade_trace/security/keyring.py
  - src/trade_trace/storage/__init__.py
  - src/trade_trace/storage/database.py
  - src/trade_trace/storage/edge_audit.py
  - src/trade_trace/storage/migrations.py
  - src/trade_trace/storage/paths.py
  - src/trade_trace/storage/policy.py
- Sampled prior audit artifacts for duplicate avoidance:
  - deadcode 2026-05-18
  - no-tech-debt 20260519T180002Z
  - bughunt 20260519T175941Z
- Did not edit files, create/update Beads, install, format, push, or publish.

Coverage accounting:
- Domain files listed: 16
- Domain files inspected: 16
- Domain files not inspected: 0
- Total inspected domain LOC by file count command: 3,888 lines
- Existing duplicate/open-work notes observed from artifacts:
  - trade-trace-cpz2: idempotency-key enforcement on write tools; avoid filing idempotency enforcement bugs/simplifications against write-tool surface.
  - trade-trace-mky / deadcode CRT-002: unused events.write_event wrapper already tracked; current src/trade_trace/events/log.py shows wrapper removed and comment retained, so no new candidate.
  - trade-trace-7e2 / trade-trace-m8c: exporter.SECRET_PATTERNS compatibility alias bug previously tracked/mentioned; current exporter has alias, no new candidate.
  - trade-trace-re4: forecast.supersede data-integrity bug; out of simplification scope and avoid duplicate.
  - open dogfood/schema bugs: source.add schema/example mismatch, decision.add schema for watch/skip, missing tool schemas; avoided filing schema-drift candidates for CLI/MCP tool surface.
  - console epic trade-trace-1kkv: no direct duplicate found in inspected storage files/artifacts.

Commands/tools run:
- git rev-parse HEAD && pwd && git status --short && find docs/audits/simplification-20260519T180020Z ...
- read_file domain-map.json
- python3 line-count script over the 16 domain files
- read_file over all 16 listed domain files, including chunked reads for migrations.py
- search_files over prior audit artifacts for idempotency/schema/migration/projection/event/exporter/outbox/semantic/keyring/model-stub duplicate signals
- git status --short final verification

Candidate records:

Candidate SIM-STORAGE-001

id:
SIM-STORAGE-001

title:
Split storage/migrations.py into versioned migration modules plus shared DDL helpers

evidence:
- src/trade_trace/storage/migrations.py is 1,277 lines, by far the largest file in this domain.
- It mixes multiple responsibilities in one file:
  - FTS5 availability error/check: lines 22-53
  - migration DDL for schema versions 001-010: lines 57-1117
  - migration registry: lines 1119-1130
  - table-created metadata for stale-meta detection: lines 1133-1156
  - SchemaMetaMismatchError and schema/meta assertion: lines 1159-1213
  - current_version/apply_pending_migrations runner: lines 1216-1277
- Migration 003 alone contains most M1 ledger schema creation plus indexes and append-only triggers: lines 153-578.
- Append-only trigger construction is duplicated in several shapes:
  - generic table loop in migration 003: lines 539-577
  - signals trigger block: lines 701-725
  - memory_nodes and memory_recall_events trigger loops: lines 792-806 and 854-868
  - playbook tables trigger loop: lines 1013-1024
  - events trigger block: lines 1053-1077
- The file is intentionally forward-only, but the current shape makes review of new migrations require scanning old DDL, runner logic, policy checks, FTS preflight, and append-only trigger text together.

behavior contract:
- Preserve forward-only migration behavior exactly.
- Preserve MIGRATIONS order and len(MIGRATIONS) semantics.
- Preserve current_version() behavior for missing/corrupt meta values.
- Preserve apply_pending_migrations() transaction behavior and target_version validation.
- Preserve SchemaMetaMismatchError behavior and _MIGRATION_TABLES_CREATED semantics.
- Preserve every emitted DDL statement, CHECK constraint, index, trigger name/message, and table/column name unless deliberately handled in a separate behavior-changing issue.
- Preserve public imports from trade_trace.storage and trade_trace.storage.migrations.

complexity cost/benefit:
- Cost today:
  - One “god migration” file couples stable historical DDL with active runner/policy code.
  - New migration reviews are noisy because unrelated old schema text dominates the diff context.
  - Append-only trigger idioms are repeated with slightly different strings and loops, increasing chance of inconsistent trigger policy.
  - Tests for runner/meta behavior and tests for DDL content are forced through one module.
- Benefit of simplification:
  - Versioned migration modules make additions append-only at the module/registry level.
  - Shared helpers for append-only triggers reduce repeated string-building while keeping trigger names/messages explicit.
  - Runner/meta logic becomes easier to reason about and test independently from historical DDL.

bounded shape:
- Create an internal migration package, for example:
  - src/trade_trace/storage/migrations/__init__.py or keep compatibility shim at migrations.py
  - src/trade_trace/storage/migrations/runner.py
  - src/trade_trace/storage/migrations/v001_meta.py ... v010_strategy_id.py
  - src/trade_trace/storage/migrations/_ddl.py for helper functions such as create_append_only_triggers()
- Keep src/trade_trace/storage/migrations.py as a compatibility module if changing file-to-package would risk import churn, or make a package only if import compatibility is verified.
- Move only code; do not change schema.
- Optional helper extraction:
  - _create_append_only_triggers(conn, table, update_msg, delete_msg)
  - _create_no_delete_trigger(conn, table, msg)
- Leave migration numbering/order explicit in one registry.

non-goals:
- Do not rewrite historical migrations.
- Do not squash migrations.
- Do not change schema_version values.
- Do not change table structures, constraints, indexes, or trigger names.
- Do not alter idempotency-key enforcement; trade-trace-cpz2 already owns write-tool enforcement.
- Do not introduce a migration framework dependency.

behavior preservation:
- Use byte/SQL-level assertions where practical for trigger names, table names, and index names.
- Existing tests expected to cover:
  - tests/integration/test_migrations.py
  - tests/integration/test_migration_policy.py
  - tests/integration/test_append_only.py
  - tests/integration/test_schema.py
  - tests/integration/test_projection_rebuild.py
- Add/adjust a compatibility import test if file-to-package conversion is chosen.

validation:
- python3 -m pytest tests/integration/test_migrations.py tests/integration/test_migration_policy.py tests/integration/test_append_only.py tests/integration/test_schema.py -q
- python3 -m pytest tests/integration/test_projection_rebuild.py tests/integration/test_outbox_export.py tests/integration/test_idempotency.py -q
- python3 -m pytest tests/contracts/test_event_enum_coverage.py -q
- Optional schema smoke: initialize an empty DB before/after refactor and compare sqlite_master table/index/trigger names and schema_version.

size/risk/priority/confidence:
- size: M
- risk: Medium, because migration imports and exact DDL behavior are load-bearing.
- priority: P2
- confidence: High

why not taste:
- This is not merely style: the 1,277-line file mixes historical DDL, migration runner behavior, mismatch diagnostics, FTS preflight, trigger-generation patterns, and policy-facing metadata. The cost appears in reviewability and consistency of future append-only migration changes.

intentional complexity/false positive:
- Intentional complexity:
  - Forward-only migrations and append-only/replay contracts require explicit historical DDL.
  - SchemaMetaMismatchError and _MIGRATION_TABLES_CREATED are deliberate operability safeguards.
  - FTS5 preflight is deliberate because memory recall depends on FTS5.
- False-positive guard:
  - Do not reduce explicitness by hiding all DDL in opaque builders. Keep versioned migration files readable.

duplicate notes:
- Not a duplicate of trade-trace-cpz2; this is about migration module shape, not idempotency enforcement.
- Not a duplicate of prior deadcode CRT-002/trade-trace-mky; that concerned removed events.write_event wrapper.
- Not a bughunt duplicate; no behavior bug claimed.
- No Bead created due read-only lane contract.

proposed Bead body/acceptance:
Body:
Refactor storage migration organization to reduce god-file drag without changing schema behavior. Current src/trade_trace/storage/migrations.py is 1,277 lines and combines DDL for migrations 001-010, append-only trigger definitions, FTS5 preflight, schema/meta mismatch diagnostics, migration registry, and runner logic. Split into versioned migration modules plus a small runner/registry and shared DDL helpers for repeated append-only trigger patterns. Preserve public imports and exact migration behavior.

Acceptance:
- Existing public imports of MIGRATIONS, current_version, apply_pending_migrations, SchemaMetaMismatchError, and FTS5UnavailableError continue to work.
- Applying migrations to an empty DB produces the same schema_version and same sqlite_master table/index/trigger names as before.
- Trigger names and append-only error messages remain unchanged unless explicitly documented.
- Existing migration, append-only, schema, projection rebuild, outbox, and idempotency tests pass.
- No schema_version is squashed, removed, reordered, or rewritten.

disposition recommendation:
Create simplification task under trade-trace-mea1.

Candidate SIM-STORAGE-002

id:
SIM-STORAGE-002

title:
Generate or centralize duplicated enum/event registries across policy, semantic idempotency, exporter, and schema DDL

evidence:
- Event types are listed in multiple places:
  - storage/policy.py OPEN_ENUMS["events.event_type"]: lines 94-121
  - events/semantic_keys.py SEMANTIC_KEYS: lines 36-267
  - exporter.py _STATIC_EVENT_TOOL_MAP partial mapping: lines 101-121
  - storage/migrations.py events.event_type is open in policy but not CHECK-constrained in DDL; other enum constraints are directly embedded in DDL.
- Closed enum values are duplicated between code and DDL:
  - decisions.type in storage/policy.py lines 27-42 and migrations.py lines 346-349
  - outcomes.status in policy.py lines 44-52 and migrations.py lines 395-397
  - memory_nodes.node_type in policy.py line 54 and migrations.py lines 763-764
  - signals.severity in policy.py line 64 and migrations.py line 681
  - forecasts.scoring_state/scoring_support in policy.py lines 59-60 and migrations.py lines 284-287
- Pydantic enum/model surfaces duplicate some enum/schema concepts:
  - models/ledger.py DecisionType lines 19-32 duplicates decisions.type
  - models/ledger.py OutcomeStatus lines 35-41 duplicates outcomes.status
  - models/memory.py NodeType lines 17-20 duplicates memory_nodes.node_type
- The existing tests likely check coverage, but simplification opportunity remains: adding/changing a type currently requires coordinated edits in several source files.

behavior contract:
- Preserve all current enum values and open/closed enum policy.
- Preserve default-deny event writer behavior: EventWriter.write refuses event types not present in SEMANTIC_KEYS.
- Preserve exporter behavior:
  - source.attached remains payload-disambiguated.
  - system-only event types default to event_type when no user-callable tool exists.
  - JSONL shape and reserved transport keys unchanged.
- Preserve migration DDL CHECK constraints exactly for existing DB schema; do not retroactively change historical DDL.
- Preserve Pydantic public classes and enum names.

complexity cost/benefit:
- Cost today:
  - Event/enum knowledge is manually synchronized across policy.py, semantic_keys.py, exporter.py, migrations.py, and models.
  - Tests catch some drift after the fact, but readers must inspect several files to answer “what are valid event types and how are they exported/idempotently compared?”
  - Future event additions require edits in multiple places with different failure modes: KeyError in EventWriter, exporter fallback to event_type, policy drift, model/schema drift.
- Benefit:
  - A single source of truth or generated constants reduces drift and review load.
  - Event additions become a small declarative change plus explicit semantic/export policy.
  - Keeps intentional default-deny semantics while reducing repeated literal sets.

bounded shape:
- Introduce a central internal registry, for example:
  - src/trade_trace/events/registry.py for event type metadata:
    - event_type
    - semantic key spec
    - optional tool mapping
    - system/audit-only flag
  - src/trade_trace/storage/enums.py or contracts/enums.py for closed/open enum constants shared by policy, models, and tests.
- Re-export existing SEMANTIC_KEYS and SemanticKeySpec from semantic_keys.py for compatibility.
- Have exporter resolve tool mapping from the event registry, preserving source.attached special case.
- Have policy.py derive OPEN_ENUMS/CLOSED_ENUMS from shared enum constants where feasible.
- Do not alter migrations.py historical DDL in-place except possibly importing constants for future migrations; historical SQL strings may remain literal to preserve reviewable DDL.

non-goals:
- Do not change event semantics or idempotency field sets.
- Do not enforce event_type with a database CHECK; current open enum behavior should remain.
- Do not close open enums.
- Do not remove Pydantic model classes.
- Do not address missing idempotency key enforcement in write tools; that belongs to trade-trace-cpz2.
- Do not change CLI/MCP schemas; open dogfood/schema bugs own that surface.

behavior preservation:
- Existing tests should remain unchanged or become stricter around one-registry derivation.
- EventWriter.write must still use SEMANTIC_KEYS default-deny.
- resolve_tool_for_event must produce identical outputs for all currently known event types and source.attached payload variants.
- policy.check_enum_extension behavior must be byte-equivalent from caller perspective for existing enum values.

validation:
- python3 -m pytest tests/contracts/test_event_enum_coverage.py -q
- python3 -m pytest tests/integration/test_semantic_keys.py tests/integration/test_idempotency.py tests/integration/test_outbox_export.py -q
- python3 -m pytest tests/integration/test_migration_policy.py tests/integration/test_schema.py -q
- Optional focused script: iterate SEMANTIC_KEYS keys, policy OPEN_ENUMS["events.event_type"], and exporter mappings to assert intentional subset/superset relationships.

size/risk/priority/confidence:
- size: M
- risk: Medium, because default-deny idempotency and exporter/import compatibility are contract-sensitive.
- priority: P2
- confidence: Medium-High

why not taste:
- This is not naming/style preference. The same event/enum contract is represented as literal values in multiple modules that enforce different runtime behaviors. The simplification reduces concrete drift risk and future maintenance drag.

intentional complexity/false positive:
- Intentional:
  - Semantic idempotency registry is deliberately default-deny; do not weaken it.
  - Exporter’s partial map is partly intentional because some events are system/audit-only and should not redispatch.
  - Migration DDL literals are intentionally historical and reviewable.
- False-positive guard:
  - Do not over-abstract DDL into unreadable generators. Centralize active registries and future-facing constants, not necessarily every historical SQL string.

duplicate notes:
- Avoids trade-trace-cpz2; not about enforcing idempotency_key presence in handlers.
- Avoids dogfood/schema issues; not about MCP schema/examples.
- Related to but not duplicate of tests/contracts/test_event_enum_coverage.py; this is simplification of source-of-truth, not just coverage.
- No Bead created due read-only lane contract.

proposed Bead body/acceptance:
Body:
Reduce duplicated event/enum registries across storage policy, semantic idempotency, exporter tool resolution, and model enums. Today event types and enum values are manually repeated in policy.py, semantic_keys.py, exporter.py, migrations.py, and models. Introduce central internal registries/constants while preserving default-deny EventWriter behavior, exporter output, open/closed enum policy, and public model classes.

Acceptance:
- SEMANTIC_KEYS remains import-compatible and EventWriter still rejects unregistered event types.
- resolve_tool_for_event returns identical values for current event types and source.attached variants.
- OPEN_ENUMS/CLOSED_ENUMS expose the same values and check_enum_extension behavior remains unchanged.
- Pydantic public enums/classes remain import-compatible.
- Event enum coverage, semantic key, idempotency, outbox export, migration policy, and schema tests pass.
- Historical migration DDL is not rewritten in a way that changes existing schema output.

disposition recommendation:
Create simplification task under trade-trace-mea1.

Candidate SIM-STORAGE-003

id:
SIM-STORAGE-003

title:
Clarify or remove “model stubs” layer if runtime schema is SQLite/tool-driven

evidence:
- models/__init__.py docstring says models are representative M1/M3 stubs and “full schema fidelity” arrives later: lines 1-14.
- models/ledger.py docstring says “M1 ledger model stubs” and constraint enforcement lands elsewhere: lines 1-7.
- models/memory.py docstring says “Memory layer model stubs” and M3 later lights these up with real validation: lines 1-6.
- The actual runtime constraints are in SQLite migrations and tool handlers, not these Pydantic models:
  - migrations.py defines CHECK constraints, FKs, append-only triggers, and table columns.
  - EventWriter/UnitOfWork enforce event/idempotency behavior.
- Models duplicate only part of schema:
  - ledger.py has Snapshot, Thesis, Forecast, Decision, Outcome, Source, Strategy but not all tables/columns from migrations.py.
  - memory.py has MemoryNode only, not recall events/stats/embeddings.
- The stubs are public API per models/__init__.py lines 8-13, so removal may be breaking. The simplification opportunity is to make their role explicit or generate them from a canonical schema if they remain.

behavior contract:
- Preserve public imports:
  - from trade_trace.models import Decision, Forecast, MemoryNode, etc.
- Preserve JSON schema generation behavior if journal.schema or tool.schema relies on model_json_schema().
- Preserve lenient ConfigDict(extra="allow") where current importer/tests depend on it.
- Do not move validation from tool/SQLite boundary into models unless separately specified.

complexity cost/benefit:
- Cost today:
  - A partial “stub” model layer can be mistaken for authoritative schema, while actual behavior lives in migrations and tools.
  - Duplicate enum/type definitions can drift from migrations/policy.
  - The layer may create maintenance work without owning enforcement.
- Benefit of simplification:
  - Either explicitly mark it as schema/introspection DTOs and keep it minimal, or generate/derive from a central schema source so drift is reduced.
  - Reduces confusion for future contributors deciding whether to update models, migrations, policy, tool schemas, or all of them.

bounded shape:
Option A, documentation/contract clarification:
- Rename docstrings/comments from “stubs” to “public schema DTOs for import/schema introspection”.
- Add explicit comments that SQLite/tool handlers are authoritative for enforcement.
- Add small tests asserting intended partial coverage so future readers do not treat missing tables as bugs.

Option B, registry-derived simplification:
- Centralize enum constants shared with policy.
- Use those constants in Pydantic StrEnums.
- Consider deriving model schemas used by journal.schema from the same registry/tool contract used elsewhere.

Option C, deprecation path if truly unused:
- Only if search and owner approval confirm no public/API dependence, deprecate unused model classes over a compatibility window.
- Do not immediately remove because models/__init__.py declares public import contract.

non-goals:
- Do not rewrite all SQLite schema into Pydantic.
- Do not enforce all DB constraints at model construction.
- Do not remove public model imports without owner-confirmed deprecation.
- Do not change tool input schemas or MCP behavior.

behavior preservation:
- Public imports continue to succeed.
- Existing model_json_schema() callers continue to receive compatible schemas.
- Existing tests involving journal.schema/tool schema continue to pass.
- Runtime validation remains at tool/SQLite boundary.

validation:
- python3 -m pytest tests/integration/test_schema.py tests/contracts/test_json_schema_derivation.py -q
- python3 -m pytest tests/contracts/test_event_enum_coverage.py tests/integration/test_migration_policy.py -q
- Search for trade_trace.models imports and confirm no removed public names.

size/risk/priority/confidence:
- size: S-M depending on option
- risk: Low for doc/constant clarification, Medium for deprecation/generation
- priority: P3
- confidence: Medium

why not taste:
- The issue is not “I dislike stubs”; the files themselves describe a partial, non-authoritative model layer while the actual schema and validation live elsewhere. That split creates concrete schema-drift and contributor-confusion risk.

intentional complexity/false positive:
- Intentional:
  - Public model import stability is load-bearing according to models/__init__.py.
  - Lenient models may be useful for import/schema introspection and avoiding circular foundation churn.
- False-positive guard:
  - Do not remove or “complete” models just because they are partial. Choose clarification or central constants unless owner confirms a deprecation path.

duplicate notes:
- Not a duplicate of open dogfood/schema bugs; those focus MCP/tool schemas.
- Not a duplicate of deadcode CRT-002; model layer was previously noted as active/kept in deadcode lane.
- No Bead created due read-only lane contract.

proposed Bead body/acceptance:
Body:
Clarify and simplify the public models layer. The current Pydantic model files describe themselves as stubs and intentionally do not enforce full SQLite/tool constraints. This can be mistaken for authoritative schema and duplicates enum/type knowledge. Decide whether these are stable public schema DTOs, generated/constant-backed model schemas, or candidates for owner-approved deprecation. Preserve public imports unless deprecation is explicitly chosen.

Acceptance:
- Public imports from trade_trace.models remain compatible unless a documented deprecation path is approved.
- Docstrings/comments clearly state whether SQLite/tool handlers or Pydantic models are authoritative for validation.
- Shared enum constants are used or drift tests document intentional duplication.
- journal.schema/tool schema tests continue to pass.
- No runtime write validation behavior changes.

disposition recommendation:
Create lower-priority simplification task under trade-trace-mea1, or fold into SIM-STORAGE-002 if the parent wants one registry-focused task.

Non-candidate / intentional complexity notes:
- EventWriter + UnitOfWork complexity appears intentional and contract-bearing:
  - append-only event log, outbox queue, idempotent replay/conflict behavior, request metadata, dry-run rollback, and projection callbacks are cohesive.
  - I do not recommend simplifying by adding another event write wrapper; prior deadcode work already removed/closed that path.
- projections.py complexity appears mostly behavior-driven:
  - position replay has non-trivial signed quantity/PnL invariants and deterministic rebuild contract.
  - memory_node_stats rebuild is small and clear.
  - No simplification candidate filed because reducing this risks changing replay semantics.
- exporter.py has security/atomicity complexity that is intentional:
  - tmp/rename/fsync, chmod, orphan cleanup, secret warnings, outbox failure isolation.
  - No simplification candidate filed beyond registry/map centralization above.
- keyring.py security checks are intentional:
  - lazy import, insecure backend refusal, no secret logging. No simplification candidate.
- edge_audit.py UNION-based polymorphic endpoint audit is intentional:
  - SQLite cannot express polymorphic FK; read-only audit helper is bounded and clear.
- storage/database.py permission/WAL/sqlite-vec logic is intentional security/operability complexity.
- storage/paths.py and package __init__.py files are small; no simplification candidate.

Files created or modified:
- None by me.
- Final git status showed pre-existing/unrelated workspace changes/untracked artifacts:
  - M tests/contracts/test_grammar.py
  - ?? audits/no-tech-debt-20260519T180002Z/
  - ?? docs/audits/bughunt-20260519T175941Z/
  - ?? docs/audits/simplification-20260519T180020Z/

Issues encountered:
- Attempted to run `bd list --status open --json` for live duplicate checking, but the command was blocked by environment policy (“User denied. Do NOT retry.”). I did not retry. I used existing audit/preflight artifacts for duplicate avoidance instead.
- `python` was not available; reran the line-count script with `python3`.
- Did not run pytest because this is a read-only review lane and tests may write caches/temp artifacts; validation commands are proposed only.