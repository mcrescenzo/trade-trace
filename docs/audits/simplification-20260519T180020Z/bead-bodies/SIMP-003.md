Context:
Materialized from repo-simplification-review row SIMP-003 (SIM-STORAGE-001) under epic trade-trace-mea1. Domain: storage. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Investigate splitting monolithic SQLite migrations into versioned modules without changing schema. Complexity class: god-object.

Evidence:
- src/trade_trace/storage/migrations.py is 1,277 lines and combines FTS5 checks, schema versions 001-010, append-only triggers, migration registry, schema/meta mismatch diagnostics, and runner logic.
- Migration 003 alone spans the core ledger schema, indexes, and append-only triggers; trigger patterns recur across migrations.

Why this is investigation/design-first:
The candidate touches behavior-sensitive or high-risk surfaces. The first deliverable is characterization/findings and a safe downstream plan, not refactor implementation.

Target simplification:
Investigation/design only: produce a schema-equivalence harness and split plan before any refactor. Preserve public imports and exact migration behavior.

Non-goals:
- Do not change CLI/MCP contracts, storage semantics, report schemas, security posture, or agent-facing workflow policy.
- Do not perform broad rewrites or introduce generic frameworks beyond the bounded helper/decision described here.
- Do not absorb deferred/rejected matrix rows into this work without a new explicit decision.

Behavior preservation:
- Preserve current observable behavior for all cited public/tool/test surfaces.
- For investigation rows, preserve behavior by not refactoring until the findings record defines exact current behavior and validation evidence.

Risks / intentional complexity check:
Some duplication is intentional for compatibility, auditability, release safety, or security boundaries. Keep intentional explicitness where the validation plan cannot prove an equivalent simpler shape.

Validation:
- python -m pytest tests/integration/test_migrations.py tests/integration/test_migration_policy.py tests/integration/test_schema.py tests/integration/test_append_only.py
- Close with findings documenting old-vs-new schema SQL/meta equivalence criteria and whether file-to-package compatibility is safe.

Acceptance criteria:

- Findings/decision record documents exact current behavior, risks, and whether downstream implementation should be created.
- No implementation refactor is performed unless behavior characterization and validation commands are explicit.
- Any proposed follow-up tasks reference this bead and include concrete validation.

Provenance:
Discovered by repo-simplification-review candidate SIMP-003 from source candidate(s) SIM-STORAGE-001. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
