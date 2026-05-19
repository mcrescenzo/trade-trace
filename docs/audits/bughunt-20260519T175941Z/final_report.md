# Exhaustive repo bughunt refresh — 20260519T175941Z

Status: materialized and locally verified.

## Scope and coverage

- Repo: `/home/hermes/code/trade-trace`
- Branch: `main`
- Mode: Exhaustive repo bughunt refresh
- Tracked files assigned: 330 / 330
- Excluded files: 0
- Historical audit artifacts: 143 grouped as docs-historical/context-only, not treated as fresh product-source coverage.
- Product/source/config/docs/tests coverage: direct read, search-hit review, runtime-tested probes, and lane packet evidence as recorded in:
  - `manifest.json`
  - `coverage_ledger.jsonl`
  - `coverage_summary.json`
  - `lane-packets/lane-0.md` through `lane-5.md`

Coverage summary by lane:

- `cli-mcp-contracts-tools`: 10 read-directly
- `storage-events-integrity`: 15 read-directly
- `reports-memory-strategy-playbook`: 25 read-directly
- `security-config-ops`: 8 read-directly, 20 search-hit-reviewed
- `docs-packaging-ci-contracts`: 7 read-directly, 14 search-hit-reviewed
- `tests-fixtures-crosscutting`: 2 runtime-tested, 86 search-hit-reviewed
- `historical-audit-artifacts`: 143 grouped-not-read-with-rationale

## Candidate disposition

Candidate matrix: `candidate_matrix.json`
Candidate-to-bead map: `candidate_to_bead_map.json`
Primary evidence: `primary_evidence.txt`

- Raw candidates: 13
- Accepted/materialized: 12
- Merged into existing bead: 1 of the 12 accepted (`CAND-003` -> `trade-trace-3i33`)
- Deferred / needs more evidence: 1 (`CAND-007`)
- Rejected as speculative/fixed/duplicate: 0 beyond the explicit merge/defer decisions above

Accepted related bug findings:

- `trade-trace-kynj` — Unknown CLI commands bypass the JSON error-envelope contract
- `trade-trace-pybt` — CLI parser documents repeated/comma array flags but passes strings or last value
- `trade-trace-3i33` — Fill missing tool schemas and CLI help for agent-safe MCP usage (existing bead updated/merged)
- `trade-trace-ug7p` — forecast.supersede idempotent retry creates extra replacement forecasts and edges
- `trade-trace-ld6l` — forecast.supersede skips late auto-score when a resolved_final outcome already exists
- `trade-trace-vzmq` — reflection.prompt_for_outcome can attach the wrong forecast/thesis for multi-forecast instruments
- `trade-trace-cs0r` — report.compare advertises group_by values that are rejected at runtime
- `trade-trace-l24k` — journal.restore trusts manifest paths and can write outside TRADE_TRACE_HOME
- `trade-trace-9oxn` — Fresh direct import of trade_trace.tools.admin fails with circular ImportError
- `trade-trace-0tdt` — PRD documents journal.init --enable-embeddings, but the flag is a silent no-op
- `trade-trace-68ew` — journal.status golden parity test reads the developer default Trade Trace home
- `trade-trace-boqe` — NDJSON exit-code test expects review.bundle to be unsupported after it became implemented

Deferred:

- `CAND-007` — reflection.prompt_for_outcome omits strategy-scoped prior reflections despite documented packet scope. Deferred as `needs-more-evidence`; no implementation-ready bead created.

## Beads graph

- Epic: `trade-trace-4c4i`
- Final verification gate: `trade-trace-ck50`
- Membership model: relation-based. `bd children trade-trace-4c4i` returning `[]` is expected.
- Canonical navigation:
  - `bd dep list trade-trace-4c4i`
  - `bd list --status open --flat --limit 0 --sort id | grep 'bughunt:exhaustive-refresh-20260519'`
  - `bd graph trade-trace-4c4i`

## Duplicate disposition

The final duplicate scan reported mechanical/title-similarity pairs. Disposition:

- `trade-trace-ug7p` vs `trade-trace-ld6l`: not duplicates. Both touch `forecast.supersede`, but one is idempotent replay creating extra replacement forecasts/edges; the other is late auto-score omission when `resolved_final` already exists. Different failure modes and validation paths.
- `trade-trace-boqe` vs `trade-trace-68ew`: not duplicates. Both are test failures, but one is stale NDJSON exit-code expectation for `review.bundle`; the other is journal.status golden parity leaking developer default home schema state.
- `trade-trace-kynj` vs `trade-trace-0tdt`: not duplicates. Unknown CLI command JSON-envelope behavior differs from PRD-documented no-op flag behavior.
- `trade-trace-l24k` vs `trade-trace-68ew`: not duplicates. Journal restore path traversal is a security/write-boundary bug; golden parity default-home leakage is test isolation.
- `trade-trace-cs0r` vs `trade-trace-yv9z`: probable cross-audit overlap with a deadcode/backlog item about stale `DOCUMENTED_GROUP_BY`; current bug bead is behavior-first API-contract/runtime evidence. Keep separate unless remediation later proves same fix surface.
- Cross-epic title-similarity pairs involving deadcode/simplification/no-tech-debt epics are mechanical noise, not current bughunt finding duplicates.

## Verification snapshots

- Pre-mutation snapshot: `verification/pre_mutation_snapshot.txt`
- Post-materialization snapshot: `verification/final_verification_preclose.txt`
- Final verification snapshot after gate close/push should be recorded at `verification/final_verification_postclose.txt`.

Latest verified facts before this report:

- `bd dep cycles`: no dependency cycles.
- `bd children trade-trace-4c4i --json`: `[]`, expected for relation-based membership.
- `bd dep list trade-trace-4c4i`: shows 12 open related bug findings plus the final verification gate before closure.
- `bd orphans`: no orphaned issues.
- `bd lint`: remaining warnings are pre-existing/out-of-scope except `trade-trace-3i33`, which was repaired by adding `## Steps to Reproduce`; rerun final snapshot for exact post-repair state.
- Secret scan over the run artifact found only synthetic/filename false positives (`api_keyring.py`, `secret_pattern_writes.py`), not credential material.

## Caveats

- This is coverage-enumerated, not proof that all possible bugs were found.
- Historical audit artifacts were grouped for context/deduplication and not reread as fresh product behavior evidence.
- Two pytest failures were observed and materialized as bug findings: `test_journal_status_parity` and `test_exit_code_one_on_other_error`.
- No implementation fixes were made by this bughunt; temporary source/test edits from probes were restored before finalization.
