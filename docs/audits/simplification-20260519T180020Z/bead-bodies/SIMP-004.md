Context:
Materialized from repo-simplification-review row SIMP-004 (SIM-STORAGE-002 + SIM-XCUT-003) under epic trade-trace-mea1. Domain: storage. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Investigate central schema-governed enum and timestamp registries without weakening explicit audits. Complexity class: duplicate-logic.

Evidence:
- Event/enum/timestamp knowledge is duplicated across storage/policy.py OPEN_ENUMS and closed enums, events/semantic_keys.py SEMANTIC_KEYS, exporter.py _STATIC_EVENT_TOOL_MAP, migrations.py CHECK constraints, and timestamps.py TIMESTAMP_API_GOVERNED_COLUMNS.
- The duplication is partly intentional as a safety boundary; automatic derivation could silently bless new timestamp columns.

Why this is investigation/design-first:
The candidate touches behavior-sensitive or high-risk surfaces. The first deliverable is characterization/findings and a safe downstream plan, not refactor implementation.

Target simplification:
Investigation/design only: inventory duplicated schema-governed values and decide which may be single-sourced while preserving explicit audit semantics.

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
- python -m pytest tests/contracts/test_event_enum_coverage.py tests/integration/test_semantic_keys.py tests/test_timestamps.py tests/integration/test_migration_policy.py tests/integration/test_outbox_export.py
- Close with a decision record separating safe constants extraction from intentionally explicit audit lists.

Acceptance criteria:

- Findings/decision record documents exact current behavior, risks, and whether downstream implementation should be created.
- No implementation refactor is performed unless behavior characterization and validation commands are explicit.
- Any proposed follow-up tasks reference this bead and include concrete validation.

Provenance:
Discovered by repo-simplification-review candidate SIMP-004 from source candidate(s) SIM-STORAGE-002 + SIM-XCUT-003. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
