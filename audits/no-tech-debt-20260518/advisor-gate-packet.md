# Advisor evidence packet — no-tech-debt 20260518

Repo: /home/hermes/code/trade-trace
Initial preflight commit: a33e676ec9d22d6ec268686424521a3d2586f9dd
Final target commit: e56c1883f3d8701c719e7c89a6e42ff004168328 (a concurrent/local mypy-fix commit landed during the run; final verification is scoped here)

Artifacts:
- coverage ledger: audits/no-tech-debt-20260518/coverage-ledger.jsonl
- lane reports: audits/no-tech-debt-20260518/lane-reports/lane-0.md .. lane-7.md
- central matrix: audits/no-tech-debt-20260518/central-debt-matrix.json
- mutation map: audits/no-tech-debt-20260518/mutation-map-prewrite.json
- validation: audits/no-tech-debt-20260518/verification/validation-current.txt

Coverage summary:
- 158 tracked files classified and assigned to lanes.
- Eight read-only lanes inspected docs/config/CI, contracts/CLI/MCP, storage/events/models, domain tools, reports/exporter, tests, and security.
- All raw lane summaries are preserved.

Validation truth:
- ruff check src tests: pass.
- mypy src: pass.
- python3 -m pytest -q: fails collection due stale tests/security/test_redacted_exports.py importing SECRET_PATTERNS from exporter.
- targeted version tests fail because current version is 0.0.1rc0 but tests assert 0.0.1.

Disposition after advisor reductions:
- accepted: 37
- merged: 4
- deferred: 1
- rejected: 1

High-risk/design/investigation rows:
- DEBT-001 [P1 bug]: Fix stale hard-coded package version assertions in smoke/golden tests
- DEBT-002 [P1 bug]: Repair stale SECRET_PATTERNS import in redacted export security test
- DEBT-008 [P2 design]: Choose strict or extensible semantics for ToolContext.meta_hints unknown keys
- DEBT-011 [P1 design]: Harden events table with SQLite append-only triggers
- DEBT-012 [P2 design]: Enforce or explicitly grandfather strategy_id references after strategies table exists
- DEBT-013 [P2 investigation]: Make FTS5 dependency explicit or gracefully optional for memory migrations
- DEBT-014 [P2 design]: Add storage-level timestamp invariant coverage or explicit delegation policy
- DEBT-015 [P3 investigation]: Add schema/meta consistency checks for migration recovery
- DEBT-016 [P2 design]: Validate polymorphic edge endpoints and audit orphan edges
- DEBT-017 [P1 bug]: Make memory.reflect node + about-edge write truly atomic
- DEBT-019 [P1 bug]: Add replay-safe idempotency to strategy.update
- DEBT-021 [P1 design]: Define and enforce supported ReportFilter semantics per report
- DEBT-022 [P1 bug]: Define signed quantity convention and fix projection realized P&L sign coverage
- DEBT-035 [P2 design]: Decide and cover secret scanning for all persisted free-text and metadata surfaces
- DEBT-036 [P1 bug]: Cover explicit metadata_json credential injection in no-credentials policy
- DEBT-039 [P2 design]: Pin future MCP stdio security boundary before transport implementation
- DEBT-041 [P3 investigation]: Guard or scope runtime secret regex registration against ReDoS

Graph plan:
- Create one narrative epic labelled tech-debt, repo-no-tech-debt, debt-run:20260518-no-tech-debt.
- Create one final verification task; final gate depends on every materialized accepted row (bd dep add <final-gate> <candidate-id>).
- Relate every materialized row to the no-tech-debt epic. Relate bug-track rows to existing bughunt epic trade-trace-2d3 as sibling visibility.
- Keep merged rows as matrix-only dispositions and, where appropriate, add notes to existing beads trade-trace-74b/trade-trace-0r7.
