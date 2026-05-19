# Lane packets — exhaustive deadcode hunt 2026-05-18

This file is a durable lossless-enough summary of the read-only delegated lanes. Parent transcript contains the full child summaries; this artifact preserves assigned scope, commands/search classes, candidates, keep/reject leads, and coordinator verification notes.

## Lane core-runtime
Assigned files: 27 tracked source files under src/trade_trace excluding tools/reports transport-specific lane files.
Commands/searches reported: git ls-files; Python AST inventory/token count; searches for default_clock/set_default_clock/FixedClock/SystemClock/Clock; trade_trace.clock imports; find_existing/is_additive_only/new_request_id; write_event(.
Candidates:
- CRT-001: unused process-global clock accessors src/trade_trace/clock.py:49-60 (`_DEFAULT_CLOCK`, `default_clock`, `set_default_clock`). Evidence: repo searches find only definitions for default_clock/set_default_clock; runtime uses tools._helpers.CLOCK_OVERRIDE. Caveat: importable public surface/docs mention injectable clock; FixedClock/SystemClock are test-used. Recommendation: needs-owner-confirmation.
- CRT-002: unused module-level events.write_event wrapper src/trade_trace/events/log.py:311-332 and re-export in events/__init__.py. Evidence: search for `write_event(` finds only definition; active writes use EventWriter/UnitOfWork. Caveat: exported public API. Recommendation: cleanup-candidate + needs-owner-confirmation.
Keep/reject leads: core.new_request_id active via dispatch; EventWriter.find_existing active via tools/_helpers; EnumChange.is_additive_only test-covered; exporter/storage/models/security/timestamps/version active.

## Lane tools-transports
Assigned files: 19 tracked files: cli.py, mcp_server.py, tools/*.py. Verified pyproject scripts, default_registry, live registry with 61 tools, docs/tests for stubs.
Candidates: none.
Keep/reject leads: cli.py live via pyproject scripts; mcp_call live in tests; serve_stdio is intentional placeholder covered by open trade-trace-46p; import.validate/import.commit, review.bundle, model.import/model.warm/memory.reindex, journal.rescan_scoring are intentional deferred public/stub surfaces and duplicate existing roadmap/open themes; decision_matrix and _examples are live via ledger/tool.schema; all register_* tool modules are dynamically live.

## Lane reports-memory
Assigned files: 12 tracked report modules. Verified register_report_tools, reports.__all__, docs/architecture/reports.md, tests.
Candidates: none.
Keep/reject leads: all report modules/functions/constants are registered, public-exported, tested, or internally called. Private helpers are internally used; root exports are public API.

## Lane tests-fixtures
Assigned files: 75 tracked tests/* files. Commands/searches: git ls-files tests/*; pytest collect-only; AST inventory; searches for helper refs; inspected conftest and representative contracts/golden/integration/property/security tests.
Candidates:
- TST-001: unused test helper tests/security/test_no_credentials.py:55-61 `_all_columns`; search finds only definition (plus generated audit artifact), and same file inlines PRAGMA scan in test_no_table_column_resembles_credential. Recommendation: confirmed cleanup.
Duplicate/merge lead:
- TST-002: tests/security/test_redacted_exports.py imports missing exporter.SECRET_PATTERNS; pytest collection fails. Existing bead trade-trace-7e2 already tracks this P0 bug. Recommendation: duplicate/merge into trade-trace-7e2, no new bead.
Keep/reject leads: empty tests __init__.py package markers keep; conftest auto-discovered; broad test suite live by pytest collection despite one collection error.

## Lane packaging-ci-docs + beads/misc
Assigned files: 26 tracked non-source files. Commands/searches: read all assigned files; source/registry searches; live registry print; markdown local-link checker; version consistency check; attempted bd list --label was blocked and not retried.
Candidates:
- DOC-001: broken markdown local links after docs path moves. README links ./VISION.md and ./PRD.md though files are docs/VISION.md and docs/PRD.md; docs/PRD.md links ./docs/architecture/... resolving to docs/docs/...; docs/architecture/*.md link ../../PRD.md/../../VISION.md resolving to repo root. Link checker found missing targets.
- DOC-002: README/PRD package/vector dependency contradiction. pyproject runtime deps only pydantic; README and PRD say base wheel ships sqlite-vec/sentence-transformers once M3 lands while README status says M3 shipped; memory-layer.md says those deps land with a4p.
- DOC-003: README quickstart stale current tool schema/commands: uses forecast outcome key `label` where current schema/tests use `outcome_label`; mentions `tt config set embeddings.provider local` but registry has `journal.config_set`, not config.set.
- DOC-004: docs name unregistered/stale tool surfaces: export.drain/config.toml in persistence/operability; top-level `tt backup`/`tt restore` in operability; dogfood protocol names forecast.show/decision.show/edges.list though registry lacks those tools.
- DOC-005: AGENTS.md/CLAUDE.md generic duplicated Beads/push instructions and CLAUDE placeholders; recommendation from lane was cleanup/owner-confirmation, but coordinator flags this as lower-confidence because project policy currently explicitly requires push.
- DOC-006: .beads/README.md generic bootstrap doc in initialized repo; recommendation lane suggested optional replace/keep. Coordinator flags as low-value keep/no bead.
Keep/reject leads: CI workflow coherent with pyproject/version; pyproject scripts live; .gitignore and .beads config/metadata coherent; LICENSE ok.
