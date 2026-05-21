# Repo audit plan — repo-audit-20260521T173511Z

## Preflight truth packet

- Requested target: implicit current working directory.
- Tool cwd / resolved git root: `/home/hermes/code/trade-trace`.
- Initial HEAD: `a1023ea4f2d498e916acbcbe25eecc0570d873bf`.
- Branch/state before audit artifacts: `main...origin/main`, clean short status.
- Beads root: `/home/hermes/code/trade-trace/.beads` using `bd version 1.0.3`.
- Beads stats: 471 total, 10 open, 0 in progress, 6 blocked, 461 closed, 4 ready.
- Current open Beads are a product feature program for `current-exposure-open-trades`; no open audit-family Beads in the inventory.
- Relevant closed audit-family inventory: 174 related closed issues, including 11 closed epics across bughunt, deadcode, no-tech-debt, and simplification runs on 2026-05-18 through 2026-05-20. Inventory artifact: `existing-audit-family-inventory.json`.
- Duplicate pre-scan: `bd find-duplicates --status open --threshold 0.35 --limit 100 --json` returned 20 mechanical pairs, all within the current-exposure feature program; not audit-family duplicates.
- Beads mutation syntax verified: `bd create --body-file`, `bd dep relate`, and `bd children` help were inspected; relation membership is available.

## Mode decision

Mode: `full` comprehensive repo-audit discovery with **delta-sensitive materialization**.

Rationale:
- Michael invoked `repo-audit`, so run all four lenses under one controller and one matrix.
- There is no open canonical `repo-audit` epic, but there are many recent closed sibling-domain audit backlogs. Therefore every candidate must be compared against `existing-audit-family-inventory.json` and routed as `merge-into-existing`, `redirect`, `reject`, or `delta-only` when already covered.
- Only additive, sufficiently grounded candidates should be materialized into a new consolidated `repo-audit` epic after matrix + advisor gates. If no additive candidates survive, stay report-only and do not create graph noise.

## Scope fingerprint and manifest

- `audit_run_id`: `repo-audit-20260521T173511Z`
- `scope_fingerprint`: `1901b8097953e720`
- Tracked files: 372 from `git ls-files`
- Coverage ledger: `manifest-coverage-ledger.yaml`
- Preflight summary: `preflight-summary.json`

Classification counts from the updated persisted ledger:

| classification | count |
| --- | ---: |
| source | 113 |
| test | 135 |
| docs-contract | 51 |
| docs-historical | 56 |
| packaging | 5 |
| config | 4 |
| deploy-service | 3 |
| generated-lockfile | 1 |
| asset-binary | 4 |

Generated/packaged assets and lock artifacts are grouped with rationale; tracked `docs/audits/*` prior-audit artifacts are separated from current docs-contract surfaces and used for reconciliation/overlap evidence only. All source/test/config/docs-contract/packaging/deploy-service paths require lane coverage by direct read, source-scoped search, or contract check.

## Lane map

| lane | assigned files | primary surfaces | lenses |
| --- | ---: | --- | --- |
| `core-storage-security` | 36 | storage, events, import/export, backup/restore, credentials/security helpers | bug, deadcode reachability, security/data-integrity debt, simplification |
| `cli-mcp-tooling` | 27 | CLI, MCP stdio, dispatcher/tool registry/schema/error envelopes | bug/API contract, deadcode public surface, config/tooling debt, simplification |
| `reports-memory-playbook` | 24 | reports, memory retain/recall/reflect, playbook, strategies, projections/positions | bug/data-contract, deadcode, debt, simplification |
| `console-frontend-backend` | 30 | FastAPI console, frontend source, packaged static app provenance, console runtime docs/tests by cross-reference | bug/UI/API contract, deadcode, deploy/package debt, simplification |
| `tests-harness-contracts` | 132 | integration/contract/security/property/golden/browser tests and fixtures | bug regression gaps, stale tests, test-debt, dead fixtures/helpers, simplification |
| `docs-contract-release` | 51 | README, SECURITY, AGENTS/CLAUDE, current docs/architecture, release checklist/history | docs-contract bugs, stale claims, release/process debt, simplification |
| `build-package-ci-config` | 11 | pyproject, GitHub Actions, package manifests, tool configs, hooks | packaging/deploy bugs, dependency/tooling debt, dead scripts/config, simplification |
| `prior-audit-artifacts-reconciliation` | 56 | tracked `docs/audits/*` prior audit artifacts | closed-backlog overlap and regression/supersession reconciliation |
| `grouped-assets-locks` | 5 | generated lock/static app assets/provenance | grouped asset/lock provenance only |

Every non-grouped lane is reviewed through the four domain lenses. The grouped lane is checked for packaging/provenance drift by the console and build/package lanes rather than line-by-line. The large former tests/docs/release lane was split after the plan advisor gate to preserve explicit per-surface coverage.

## Delegation plan

Launch read-only subagent lanes after the advisor plan gate:

1. `core-storage-security` across all four lenses.
2. `cli-mcp-tooling` across all four lenses.
3. `reports-memory-playbook` across all four lenses.
4. `console-frontend-backend` across all four lenses.
5. `tests-harness-contracts` across all four lenses.
6. `docs-contract-release` across all four lenses.
7. `build-package-ci-config` across all four lenses.
8. `prior-audit-artifacts-reconciliation` for closed audit-family overlap, regression-of-closed, and prior-match classification.

Each lane must:
- do no edits, no Beads writes, no destructive commands, no package-manager cleanup, no pushes/publishes;
- inspect assigned files/searches before claims;
- return lane-return-envelope-compatible coverage and candidate records;
- separate observed facts, inferences, assumptions, open questions, recommendations, evidence handles;
- return per-assigned-manifest-row coverage treatment: `opened`, `searched`, `contract-checked`, `structurally-grouped-with-rationale`, `generated/binary-grouped`, `excluded-with-rationale`, or `not-covered/blocker`;
- use tracked-file/source-scoped searches and exclude generated/cache/build artifacts from decisive reachability claims;
- mark each candidate's prior-match status against closed audit-family inventory as `new`, `covered-by-closed`, `regression-of-closed`, `supersedes-closed`, or `needs-human`; no materialization from title similarity alone.

## Validation commands / probes likely relevant

Read-only or bounded verification only during audit:

- `python -m pytest -q` only if lane needs broad regression proof and runtime is reasonable; otherwise targeted pytest modules.
- `python -m pytest tests/contracts -q`, `python -m pytest tests/security -q`, `python -m pytest tests/console_browser -q` when relevant.
- `ruff check .`, `mypy src` if candidate claims involve static/tooling drift.
- `python -m build` only if release/package findings need proof.
- `npm test`/`npm run build` under `frontend/console` only if package scripts/deps are present and installed; otherwise record validation gap.
- Static probes: symbol/reference searches, import graph inspection, docs link/route catalog comparison, package data checks.

## Matrix and materialization gates

- Central matrix artifact: `candidate-matrix.yaml` using `repo-audit-backlog-scaffold/templates/base-candidate-matrix.yaml` fields.
- Advisor gates:
  1. Plan gate before delegation.
  2. Matrix/materialization gate after lane synthesis and coordinator verification.
  3. Final closeout gate after Beads/readback verification.
- Beads materialization only after matrix gate. Membership model: one narrative repo-audit epic with relation-based members; labels `repo-audit`, `audit-run:20260521T173511Z`, `track:<...>`, `domain:<...>` where accepted.
- Stop conditions: unresolved overlap requiring a canonical backlog choice; insufficient evidence; material repo/Beads state movement; inability to preserve coverage ledger; advisor blocking objection not resolved.

## Artifacts

- `docs/reviews/repo-audit-20260521T173511Z/manifest-coverage-ledger.yaml`
- `docs/reviews/repo-audit-20260521T173511Z/preflight-summary.json`
- `docs/reviews/repo-audit-20260521T173511Z/existing-audit-family-inventory.json`
- `docs/reviews/repo-audit-20260521T173511Z/audit-plan.md`
