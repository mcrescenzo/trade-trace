# Repo audit observation register — repo-audit-20260521T173511Z

This register preserves raw/promoted observations and lane no-finding statements separately from the candidate matrix, so the small materialized backlog can be audited without treating the matrix as the first place weak signals appeared.

## Funnel

- Tracked files in original scope: 372
- Raw/promoted lane observations captured here: 11 candidate/observation rows plus 3 lane-level no-finding summaries
- Materialized findings: 5
- Deferred/report-only: 2
- Rejected/covered/resolved: 4

## Candidate / observation rows

### CSS-20260521-001 — Fix SQLite read-only URI escaping for DB paths containing URI-reserved characters
- Source lane: `core-storage-security`
- Disposition: `accept`
- Materialized bead: `trade-trace-dlk6`
- Duplicate/covered by: `['trade-trace-l24k', 'trade-trace-d2jv', 'trade-trace-71zq']`
- Reason: New exact bug; related closed path/security items do not cover SQLite URI escaping.
- Evidence handle: `EV-CSS-20260521-001` — database.py:116-149; storage/paths.py:16-30; parent execute_code probe output: ReadOnlyDatabaseError unsupported_schema and files [db, db?x.sqlite].

### CFB-20260521-001 — Align Decisions page multi-select decision_type filter with backend route contract
- Source lane: `console-frontend-backend`
- Disposition: `accept`
- Materialized bead: `trade-trace-rtl6`
- Reason: Endpoint-specific scalar/multi-value mismatch not covered by related closed console-filter items.
- Evidence handle: `EV-CFB-20260521-001` — main.tsx:179-183,1743-1754; api.ts:189-199; serve.py:275-289; endpoints.py:300-318.

### THC-20260521-001 — Make CLI help contract tests launch tt portably instead of hard-coding .venv/bin/tt
- Source lane: `tests-harness-contracts`
- Disposition: `accept`
- Materialized bead: `trade-trace-bn02`
- Reason: Clear test portability bug; no exact closed duplicate found.
- Evidence handle: `EV-THC-20260521-001` — test_tool_schema_runtime_parity.py:172-179; pyproject.toml:82-85.

### THC-20260521-002 — Expand browser smoke coverage to navigate every shipped Console route
- Source lane: `tests-harness-contracts`
- Disposition: `accept`
- Materialized bead: `trade-trace-beqe`
- Reason: Regression-gap finding; related closed console/package items do not provide per-route browser navigation coverage.
- Evidence handle: `EV-THC-20260521-002` — conftest.py:1-20; test_overview_smoke.py:12-38; routeCatalog.json:1-19.

### THC-20260521-003 — Trim or privatize unused direct-SQL test seed builders
- Source lane: `tests-harness-contracts`
- Disposition: `defer`
- Reason: Downgraded after advisor gate: valid simplification lead but not enough proven failure mode/public reachability to spend a standalone Bead after SIMP-009; retain in report-only matrix.
- Evidence handle: `EV-THC-20260521-003` — tests/_direct_sql_builders.py:1-16,92-297; parent search output; existing inventory line for trade-trace-24ia/SIMP-009.

### DCR-20260521-001 — Clarify final release gate requires fresh current-HEAD proof before publish
- Source lane: `docs-contract-release`
- Disposition: `accept`
- Materialized bead: `trade-trace-efkg`
- Reason: New docs/process contradiction; related release docs issues do not cover this exact final sentence.
- Evidence handle: `EV-DCR-20260521-001` — RELEASE_FINAL_GATE.md:38-42,93-105; RELEASE_CHECKLIST.md:22-30,52-55.

### RMP-001 — Refresh stale memory model module contract now that the memory layer is implemented
- Source lane: `reports-memory-playbook`
- Disposition: `defer`
- Reason: Valid but below standalone repo-audit Bead threshold unless paired with nearby docs/source-contract cleanup.
- Evidence handle: `EV-RMP-001` — models/memory.py:1-6; tools/memory.py:1-24.

### CLI-MCP-OBS-001 — Some registered read/status/deferred tools have no explicit JSON schemas
- Source lane: `cli-mcp-tooling`
- Disposition: `reject`
- Duplicate/covered by: `trade-trace-3i33`
- Reason: Current source/tests indicate prior schema-help work landed; no additive issue.
- Evidence handle: `EV-CLI-MCP-OBS-001` — lane-cli-mcp-tooling.md:73-95.

### CAND-BPCI-001 — Frontend build is not run directly by GitHub Actions
- Source lane: `build-package-ci-config`
- Disposition: `reject`
- Duplicate/covered by: `trade-trace-10x6`
- Reason: Non-additive optional hardening; existing provenance guard/backlog covers material risk.
- Evidence handle: `EV-CAND-BPCI-001` — lane-build-package-ci-prior-audit-reconciliation.md:119-139.

### CAND-BPCI-002 — Prior release workflow project.version bug
- Source lane: `build-package-ci-config`
- Disposition: `reject`
- Duplicate/covered by: `trade-trace-nkfz`
- Reason: Existing closed bug is resolved in current workflow.
- Evidence handle: `EV-CAND-BPCI-002` — lane-build-package-ci-prior-audit-reconciliation.md:141-158.

### CAND-BPCI-003 — Prior unused Console frontend dependencies
- Source lane: `build-package-ci-config`
- Disposition: `reject`
- Duplicate/covered by: `trade-trace-hdlx`
- Reason: Specific prior dead dependencies are absent from current manifest.
- Evidence handle: `EV-CAND-BPCI-003` — lane-build-package-ci-prior-audit-reconciliation.md:160-177.

## Lane no-finding / keep statements

- `cli-mcp-tooling`: No additive candidates; 68 CLI/MCP/schema contract tests passed; read/status/deferred no-schema observation rejected as covered by prior schema-help work.
- `build-package-ci-config`: No additive candidates; packaging/version workflow and frontend dependency/provenance prior findings read back as remediated or covered.
- `prior-audit-artifacts-reconciliation`: No new work; 174 closed audit-family issues used for duplicate/overlap reconciliation.

## Coverage reference

- Final row-level coverage ledger: `docs/reviews/repo-audit-20260521T173511Z/manifest-coverage-ledger.yaml`.
