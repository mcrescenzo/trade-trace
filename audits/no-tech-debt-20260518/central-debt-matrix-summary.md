# No-tech-debt central matrix summary

Run: no-tech-debt-20260518
Repo: /home/hermes/code/trade-trace
Initial preflight commit: a33e676ec9d22d6ec268686424521a3d2586f9dd
Final target commit: e56c1883f3d8701c719e7c89a6e42ff004168328

Rows: 43
Dispositions: {'accept': 37, 'merge': 4, 'defer': 1, 'reject': 1}
Accepted track counts: {'bug': 8, 'maintenance': 18, 'design': 8, 'investigation': 3}

Lossless matrix: central-debt-matrix.json
Mutation map: mutation-map-prewrite.json

## Rows
- DEBT-001: accept [bug/P1] Fix stale hard-coded package version assertions in smoke/golden tests
- DEBT-002: accept [bug/P1] Repair stale SECRET_PATTERNS import in redacted export security test
- DEBT-003: accept [maintenance/P2] Run quality gates before release tags, not only inside PyPI publish workflow
- DEBT-004: accept [maintenance/P2] Fix broken relative links across README, PRD, and architecture docs
- DEBT-005: accept [maintenance/P2] Scope AGENTS/CLAUDE session-close rules for read-only and no-push workflows
- DEBT-006: accept [maintenance/P2] Reconcile README/PRD vector dependency claims with pyproject and deferred embeddings posture
- DEBT-007: accept [maintenance/P2] Reject stray positional CLI tokens after valid command resolution
- DEBT-008: accept [design/P2] Choose strict or extensible semantics for ToolContext.meta_hints unknown keys
- DEBT-009: merge [maintenance/P2] Merge registry json_schema null coverage into existing inputSchema bead
- DEBT-010: merge [maintenance/P3] Merge write-tool example completeness into agent-ready QC backlog
- DEBT-011: accept [design/P1] Harden events table with SQLite append-only triggers
- DEBT-012: accept [design/P2] Enforce or explicitly grandfather strategy_id references after strategies table exists
- DEBT-013: accept [investigation/P2] Make FTS5 dependency explicit or gracefully optional for memory migrations
- DEBT-014: accept [design/P2] Add storage-level timestamp invariant coverage or explicit delegation policy
- DEBT-015: accept [investigation/P3] Add schema/meta consistency checks for migration recovery
- DEBT-016: accept [design/P2] Validate polymorphic edge endpoints and audit orphan edges
- DEBT-017: accept [bug/P1] Make memory.reflect node + about-edge write truly atomic
- DEBT-018: accept [maintenance/P2] Reconcile memory.reflect docs/API shape with implementation
- DEBT-019: accept [bug/P1] Add replay-safe idempotency to strategy.update
- DEBT-020: accept [maintenance/P3] Replace signal.scan JSON LIKE dedupe with structured related-ref matching
- DEBT-021: accept [design/P1] Define and enforce supported ReportFilter semantics per report
- DEBT-022: accept [bug/P1] Define signed quantity convention and fix projection realized P&L sign coverage
- DEBT-023: accept [bug/P2] Preserve true source_quality diagnostic counts before sample truncation
- DEBT-024: accept [bug/P2] Propagate calibration record-id truncation to top-level/meta truncated flag
- DEBT-025: accept [maintenance/P3] Unify report.coach raw/wrapped group extraction for mistakes and strengths
- DEBT-026: accept [maintenance/P3] Capture one as_of clock instant inside report.watchlist
- DEBT-027: accept [maintenance/P2] Handle malformed event payload JSON per outbox row during export drain
- DEBT-028: accept [maintenance/P3] Sanitize event_type before using it in JSONL export filenames
- DEBT-029: accept [maintenance/P3] Clarify low-level report output metric semantics for playbook adherence and P&L coverage
- DEBT-030: merge [maintenance/P3] Clarify report.pnl data_coverage for closed vs open positions
- DEBT-031: accept [maintenance/P2] Remove nested full-suite pytest subprocess from default dogfood verification test
- DEBT-032: defer [maintenance/P3] Consolidate repeated CLI/MCP/test data helpers into shared fixtures
- DEBT-033: accept [maintenance/P3] Make scoring “property” tests exercise production behavior or rename them
- DEBT-034: accept [maintenance/P3] Move fixture_seed wall-clock performance assertion out of default functional suite
- DEBT-035: accept [design/P2] Decide and cover secret scanning for all persisted free-text and metadata surfaces
- DEBT-036: accept [bug/P1] Cover explicit metadata_json credential injection in no-credentials policy
- DEBT-037: accept [maintenance/P3] Clarify and harden export secret-warning and shareable-export boundary
- DEBT-038: accept [maintenance/P2] Expand no-network default tests beyond journal.init/status/schema
- DEBT-039: accept [design/P2] Pin future MCP stdio security boundary before transport implementation
- DEBT-040: accept [maintenance/P2] Extend file-permission tests to directories, temp files, WAL/SHM, and backups
- DEBT-041: accept [investigation/P3] Guard or scope runtime secret regex registration against ReDoS
- DEBT-042: merge [maintenance/P2] Clarify full-local raw export vs shareable/redacted export boundary
- DEBT-043: reject [investigation/P4] Deferred P1 import/review_bundle/embeddings stubs are intentionally not materialized here
