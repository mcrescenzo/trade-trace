# Lane report: build-package-ci-config + prior-audit-artifacts-reconciliation

Audit run: `repo-audit-20260521T173511Z`  
Scope fingerprint: `1901b8097953e720`  
Lane owner: `build-package-ci-config`, `prior-audit-artifacts-reconciliation`  
Mode: read-only audit; only this artifact was written.

## Executive summary

Reviewed all 67 assigned manifest rows: 11 build/package/CI/config rows and 56 tracked prior-audit artifact rows. I found **no additive candidate recommended for new Bead materialization** in this lane.

Main conclusions:

- Python packaging is consistent with dynamic versioning and existing release-workflow bug `trade-trace-nkfz` appears remediated: `pyproject.toml` uses `dynamic = ["version"]` and `workflow.yml` verifies tag equality against `src/trade_trace/version.py`, not a nonexistent `project.version` field (`pyproject.toml:5-7`, `pyproject.toml:115-116`, `.github/workflows/workflow.yml:28-38`).
- CI quality gates are centralized through reusable `_test.yml`: PR/main CI and tag publish both call it (`.github/workflows/ci.yml:26-29`, `.github/workflows/workflow.yml:12-16`, `.github/workflows/_test.yml:13-41`).
- Console frontend package dependencies are currently referenced by source/tests; the prior deadcode finding for unused `@radix-ui/react-tabs` / `@tanstack/react-virtual` is no longer present in `package.json`, and source imports cover the remaining direct dependencies (`frontend/console/package.json:12-20`; search evidence below).
- Static console provenance closure for prior SIMP20-022/023 is present: Vite emits `provenance.json` (`frontend/console/vite.config.ts:21-45`) and Python contract tests check source and packaged-asset hashes (`tests/contracts/test_console_shell.py:81-98`).
- Prior audit artifacts are historical/backlog reconciliation inputs, not current runtime contracts; their own summaries show materialization/merge/closeout and provide overlap anchors for current candidates (`docs/audits/deadcode-20260520T172715Z/final-summary.md:14-35`, `docs/audits/deadcode-20260520T172715Z/final-summary.md:71-84`, `docs/audits/simplification-20260520T181054Z/candidate-matrix.md:6-14`, `docs/audits/simplification-20260520T181054Z/candidate-matrix.md:16-30`).

## Commands / searches performed

Read-only/static probes:

- Parsed `manifest-coverage-ledger.yaml` for assigned rows: 67 rows for these lanes.
- Direct file reads for all 11 build/package/CI/config rows.
- Direct/key artifact reads for prior-audit summaries, candidate matrices, duplicate disposition, and representative bead bodies.
- `git grep -n "npm\|frontend/console" -- .github/workflows || true` — no workflow-level npm/frontend command references found; evaluated as non-candidate because provenance tests are included in Python pytest and prior SIMP20-023 acceptance allows test/build/release-gate coverage.
- `git grep -n "@radix-ui/react-tabs\|@tanstack/react-virtual" -- frontend/console ':!frontend/console/package-lock.json' || true` — no current non-lock references/package entries for previously dead dependencies.
- Source import search for current console direct dependencies under `frontend/console/src` found imports for tooltip, react-query, react-router, react-table, echarts, lucide-react, react, and react-dom.
- Inventory search for build/package/CI/release/frontend overlap in `existing-audit-family-inventory.json`.

No package installs, test runs, formatters, destructive commands, Beads writes, pushes, or service mutations were run.

## Coverage treatment by assigned manifest row

Treatment values: `opened` means directly read; `contract-checked` means reconciled through summary/matrix/readback artifacts rather than treated as a live contract.

### build-package-ci-config (11/11)

| path | treatment | notes |
|---|---|---|
| `.claude/settings.json` | opened | Hooks run `bd prime` on `PreCompact` and `SessionStart` (`.claude/settings.json:1-25`). No audit candidate; internal agent config only. |
| `.codex/hooks.json` | opened | Hook runs `bd prime` on `PreCompact` (`.codex/hooks.json:1-15`). No candidate. |
| `.github/workflows/_test.yml` | opened | Reusable workflow runs matrix Python 3.11/3.12/3.13, installs `.[dev]`, then ruff, mypy, pytest (`_test.yml:13-41`). |
| `.github/workflows/ci.yml` | opened | PR/main push delegates to `_test.yml` (`ci.yml:13-29`). |
| `.github/workflows/workflow.yml` | opened | Tag publish delegates tests, builds distributions, runs strict twine check, publishes via trusted publishing; version check uses `version.py` (`workflow.yml:12-77`). |
| `.gitignore` | opened | Explicitly excludes `.beads/`, `.dolt/`, runtime DBs, `docs/audits/`, Python caches/builds, frontend node/modules/build-info (`.gitignore:1-42`). Current tracked prior artifacts are historical exceptions already in manifest; no live candidate from ignore policy. |
| `frontend/console/package.json` | opened/searched | Scripts and dependencies checked (`package.json:6-36`); current direct deps all have source/test references; prior unused-deps finding is not current. |
| `frontend/console/tsconfig.json` | opened | Strict TS config includes `src`, references node config (`tsconfig.json:1-21`). No candidate. |
| `frontend/console/tsconfig.node.json` | opened | Includes Vite/Vitest configs (`tsconfig.node.json:1-11`). No candidate. |
| `frontend/console/vite.config.ts` | opened | Build writes package static app and provenance manifest; server proxy local-only (`vite.config.ts:21-45`, `vite.config.ts:49-71`). Prior static provenance simplification appears implemented. |
| `pyproject.toml` | opened | Dynamic version, package data, extras, ruff/pytest config reviewed (`pyproject.toml:5-116`). No new candidate. |

### prior-audit-artifacts-reconciliation (56/56)

All rows below were treated as `contract-checked`: historical reconciliation artifacts only, not current runtime/docs contracts unless separately referenced by live docs. Representative evidence is called out after the table.

| artifact | treatment | reconciliation note |
|---|---|---|
| `docs/audits/deadcode-20260520T172715Z/advisor-review.md` | contract-checked | prior deadcode gate artifact; no live candidate by itself |
| `docs/audits/deadcode-20260520T172715Z/bead-bodies/DC-20260520-001.md` | contract-checked | maps to unused frontend deps; closed/current package no longer has the named unused deps |
| `docs/audits/deadcode-20260520T172715Z/bead-bodies/DC-20260520-002.md` | contract-checked | maps to JSONL serialization; closed per final-summary addendum |
| `docs/audits/deadcode-20260520T172715Z/bead-bodies/DC-20260520-005.md` | contract-checked | maps to `trade_detail`; closed per final-summary addendum |
| `docs/audits/deadcode-20260520T172715Z/bead-bodies/DC-20260520-006.md` | contract-checked | maps to keyring delete/revoke path; closed per final-summary addendum |
| `docs/audits/deadcode-20260520T172715Z/bead-bodies/EPIC.md` | contract-checked | historical epic body |
| `docs/audits/deadcode-20260520T172715Z/bead-bodies/FINAL.md` | contract-checked | historical final gate body |
| `docs/audits/deadcode-20260520T172715Z/body-integrity-readback.json` | contract-checked | body-integrity artifact |
| `docs/audits/deadcode-20260520T172715Z/candidate-matrix.json` | contract-checked | matrix shows materialized/merged/rejected dispositions |
| `docs/audits/deadcode-20260520T172715Z/coverage-ledger.jsonl` | contract-checked | historical coverage ledger |
| `docs/audits/deadcode-20260520T172715Z/domain-map.md` | contract-checked | historical domain map |
| `docs/audits/deadcode-20260520T172715Z/evidence-snippets.txt` | contract-checked | historical evidence snippets |
| `docs/audits/deadcode-20260520T172715Z/final-readback-raw.txt` | contract-checked | historical readback |
| `docs/audits/deadcode-20260520T172715Z/final-summary.md` | contract-checked | closeout source for deadcode reconciliation |
| `docs/audits/deadcode-20260520T172715Z/lane-assignments.json` | contract-checked | historical lane plan |
| `docs/audits/deadcode-20260520T172715Z/lane-packets.md` | contract-checked | historical lane packets |
| `docs/audits/deadcode-20260520T172715Z/materialized-id-map.json` | contract-checked | ID reconciliation artifact |
| `docs/audits/deadcode-20260520T172715Z/mutation-audit.md` | contract-checked | mutation log summary |
| `docs/audits/deadcode-20260520T172715Z/mutation-command-log.json` | contract-checked | historical command log |
| `docs/audits/deadcode-20260520T172715Z/post-push-status.txt` | contract-checked | historical closeout status |
| `docs/audits/deadcode-20260520T172715Z/preflight-truth.md` | contract-checked | historical preflight |
| `docs/audits/deadcode-20260520T172715Z/tracked-manifest.json` | contract-checked | historical manifest |
| `docs/audits/simplification-20260520T181054Z/all-new-bead-readbacks-and-git.txt` | contract-checked | simplification readback/git artifact |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-004.md` | contract-checked | accepted prior simplification; closed inventory overlap only |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-005.md` | contract-checked | accepted prior simplification; closed inventory overlap only |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-009.md` | contract-checked | accepted prior investigation; closed inventory overlap only |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-011.md` | contract-checked | accepted prior simplification; closed inventory overlap only |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-012.md` | contract-checked | accepted prior simplification; closed inventory overlap only |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-017.md` | contract-checked | accepted prior investigation; closed inventory overlap only |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-019.md` | contract-checked | accepted prior simplification; closed inventory overlap only |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-020.md` | contract-checked | accepted prior investigation; closed inventory overlap only |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-021.md` | contract-checked | accepted prior simplification; closed inventory overlap only |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-022-023.md` | contract-checked | static/route provenance prior finding; current tests/provenance indicate closure |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-029.md` | contract-checked | accepted prior simplification; closed inventory overlap only |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-FINAL.md` | contract-checked | historical final gate body |
| `docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-REC.md` | contract-checked | residual reconciliation body |
| `docs/audits/simplification-20260520T181054Z/candidate-matrix.md` | contract-checked | matrix/disposition source |
| `docs/audits/simplification-20260520T181054Z/domain-map.md` | contract-checked | historical domain map |
| `docs/audits/simplification-20260520T181054Z/duplicate-disposition.md` | contract-checked | duplicate posture source |
| `docs/audits/simplification-20260520T181054Z/final-verification-transcript.txt` | contract-checked | historical verification transcript |
| `docs/audits/simplification-20260520T181054Z/forecast-add-supersede-write-kernel-investigation.md` | contract-checked | investigation artifact for SIMP20-009 |
| `docs/audits/simplification-20260520T181054Z/lane-reports/trade_trace_simplification_lane_0.md` | contract-checked | source lane report |
| `docs/audits/simplification-20260520T181054Z/lane-reports/trade_trace_simplification_lane_1.md` | contract-checked | source lane report |
| `docs/audits/simplification-20260520T181054Z/lane-reports/trade_trace_simplification_lane_2.md` | contract-checked | source lane report |
| `docs/audits/simplification-20260520T181054Z/lane-reports/trade_trace_simplification_lane_3.md` | contract-checked | source lane report |
| `docs/audits/simplification-20260520T181054Z/lane-reports/trade_trace_simplification_lane_4.md` | contract-checked | source lane report |
| `docs/audits/simplification-20260520T181054Z/lane-reports/trade_trace_simplification_lane_5.md` | contract-checked | source lane report |
| `docs/audits/simplification-20260520T181054Z/materialize_simplification_beads_20260520.py` | contract-checked | historical materialization helper; not current product code |
| `docs/audits/simplification-20260520T181054Z/materialized-id-map.json` | contract-checked | ID reconciliation artifact |
| `docs/audits/simplification-20260520T181054Z/memory-recall-decomposition-investigation.md` | contract-checked | investigation artifact for SIMP20-017 |
| `docs/audits/simplification-20260520T181054Z/mutation-audit.md` | contract-checked | mutation audit artifact |
| `docs/audits/simplification-20260520T181054Z/mutation-command-log.json` | contract-checked | historical command log |
| `docs/audits/simplification-20260520T181054Z/preflight-truth.md` | contract-checked | historical preflight |
| `docs/audits/simplification-20260520T181054Z/readback-samples.txt` | contract-checked | readback samples |
| `docs/audits/simplification-20260520T181054Z/residual-report-test-helper-reconciliation.md` | contract-checked | residual reconciliation artifact |
| `docs/audits/simplification-20260520T181054Z/trade-trace-alwf-helper-grouping.md` | contract-checked | helper-grouping artifact |

## Candidate records

### CAND-BPCI-001 — Frontend build is not run directly by GitHub Actions

- **Title:** Frontend build/provenance is validated indirectly by Python pytest, not by an explicit CI npm build step.
- **remediation_track:** none / reject as additive Bead.
- **owner_track:** build-package-ci-config.
- **affected paths/symbols:** `.github/workflows/_test.yml`, `.github/workflows/ci.yml`, `.github/workflows/workflow.yml`, `frontend/console/package.json`, `frontend/console/vite.config.ts`, `tests/contracts/test_console_shell.py`.
- **Observed facts:**
  - `_test.yml` installs Python package with dev extras and runs `ruff check src tests`, `mypy src`, and `pytest` (`.github/workflows/_test.yml:29-41`).
  - CI/publish workflows delegate to `_test.yml` (`.github/workflows/ci.yml:26-29`, `.github/workflows/workflow.yml:12-16`).
  - No workflow file contains `npm` or `frontend/console` commands (read-only `git grep` returned no matches).
  - The frontend package has build/test/typecheck scripts (`frontend/console/package.json:6-10`).
  - Vite build writes package static app plus provenance (`frontend/console/vite.config.ts:21-45`).
  - Python pytest includes a static provenance contract that fails when source hashes or packaged asset hashes drift (`tests/contracts/test_console_shell.py:81-98`).
- **Inferences:** Explicit npm build in CI would be a stronger frontend-only signal, but the prior acceptance criterion for static asset guard was “checked by test, build, or release gate,” and current Python tests provide that guard.
- **Assumptions:** CI executes the full pytest suite from `_test.yml`; no path filtering skips `tests/contracts/test_console_shell.py`.
- **Open questions:** Whether maintainers want a separate Node matrix for faster frontend-only failure diagnostics. This is a process preference, not an uncovered audit bug from current evidence.
- **Validation command/gap:** `pytest tests/contracts/test_console_shell.py -q` would directly verify the provenance guard; not run to preserve bounded read-only lane time. `npm --prefix frontend/console run build` not run because it mutates generated static assets/provenance.
- **prior_match_status:** `covered-by-closed` / `not-additive`.
- **Duplicate/overlap notes:** Prior SIMP20-022/023 explicitly targeted static source/build drift and required a provenance or release-gate check (`docs/audits/simplification-20260520T181054Z/bead-bodies/SIMP20-022-023.md:18-40`). Inventory has the closed item “Single-source Console route catalog and static asset provenance guard” (`existing-audit-family-inventory.json:594-604`).
- **Recommended disposition:** Reject as new Bead; at most note as optional CI hardening if a future release-process lane wants direct npm build coverage.
- **Proposed Bead if accepted:** none. If maintainers override: type `task`, title `Add explicit frontend npm build/test gate to CI`, labels `repo-audit`, `audit-run:20260521T173511Z`, `track:ci`, `domain:console-frontend`, acceptance: CI runs `npm --prefix frontend/console run typecheck`, `npm --prefix frontend/console run test`, and a non-mutating provenance freshness check or documented build-dirty check.

### CAND-BPCI-002 — Prior release workflow project.version bug

- **Title:** PyPI publish workflow should not read nonexistent static `project.version` under dynamic versioning.
- **remediation_track:** none / already remediated.
- **owner_track:** build-package-ci-config.
- **affected paths/symbols:** `pyproject.toml`, `.github/workflows/workflow.yml`, `src/trade_trace/version.py`.
- **Observed facts:**
  - `pyproject.toml` declares `dynamic = ["version"]` (`pyproject.toml:5-7`) and maps dynamic version to `trade_trace.version.__version__` (`pyproject.toml:115-116`).
  - Publish workflow reads `src/trade_trace/version.py` with a regex and compares it to stripped tag, rather than reading `project.version` (`.github/workflows/workflow.yml:28-38`).
  - Existing audit inventory contains closed bug `trade-trace-nkfz`, “PyPI publish workflow reads nonexistent pyproject project.version despite dynamic versioning” (`existing-audit-family-inventory.json:20-31`).
- **Inferences:** The current workflow addresses the closed bug’s core failure mode.
- **Assumptions:** The regex remains sufficient for the simple `__version__ = "..."` source shape; source file itself was outside assigned lane and not re-opened for current line evidence.
- **Open questions:** None for this lane.
- **Validation command/gap:** `python -m build` and a tag-dry-run workflow simulation would be stronger; not run because not necessary for an already-covered candidate and `python -m build` writes `dist/`.
- **prior_match_status:** `covered-by-closed`.
- **Duplicate/overlap notes:** Existing `trade-trace-nkfz`; simplification matrix also merged release workflow dynamic version check into that open/prior release-gate work (`docs/audits/simplification-20260520T181054Z/candidate-matrix.md:65-66`).
- **Recommended disposition:** Reject as duplicate/resolved; do not materialize.
- **Proposed Bead if accepted:** none.

### CAND-BPCI-003 — Prior unused frontend dependencies

- **Title:** Remove unused Console frontend dependencies.
- **remediation_track:** none / already remediated or not current.
- **owner_track:** build-package-ci-config.
- **affected paths/symbols:** `frontend/console/package.json`, `frontend/console/package-lock.json`, frontend imports.
- **Observed facts:**
  - Prior deadcode matrix identified unused `@radix-ui/react-tabs` and `@tanstack/react-virtual` in `frontend/console/package.json` / lockfile (`docs/audits/deadcode-20260520T172715Z/candidate-matrix.json:3-24`).
  - Current `package.json` dependency list does not include those packages and lists only tooltip/query/router/table/echarts/lucide/react/react-dom (`frontend/console/package.json:12-20`).
  - Current source import search finds direct imports for each listed runtime dependency under `frontend/console/src`.
- **Inferences:** The specific prior deadcode candidate is no longer present in the current package manifest.
- **Assumptions:** Lockfile is generated and not decisive for source reachability; grouped-assets-locks owns line-by-line lockfile provenance.
- **Open questions:** None.
- **Validation command/gap:** `npm --prefix frontend/console run typecheck && npm --prefix frontend/console run test && npm --prefix frontend/console run build` would validate package health; not run because install/build may be slow/mutating and prior candidate is already closed.
- **prior_match_status:** `covered-by-closed`.
- **Duplicate/overlap notes:** Deadcode final summary materialized `trade-trace-hdlx` for unused Console frontend dependencies (`docs/audits/deadcode-20260520T172715Z/final-summary.md:29-33`), and later verification showed all materialized candidates closed (`docs/audits/deadcode-20260520T172715Z/final-summary.md:71-84`).
- **Recommended disposition:** Reject as resolved/covered; do not materialize.
- **Proposed Bead if accepted:** none.

## Prior-audit overlap synthesis

- The current audit must compare candidates against 174 closed audit-family Beads; plan artifact states inventory scope and duplicate-scan posture (`audit-plan.md:11-13`, `audit-plan.md:20-23`).
- Deadcode 20260520 produced 11 raw candidates, 4 new cleanup/investigation Beads, 2 merges into an existing docs-QC Bead, and 5 matrix-only/rejected rows (`docs/audits/deadcode-20260520T172715Z/final-summary.md:14-21`). Its addendum says the owner-confirmation candidates closed with validation (`final-summary.md:71-84`). Current build/package lane only overlaps DC-20260520-001, which is resolved in package manifest.
- Simplification 20260520 accepted only uncovered work and merged/folded/reconciled duplicate prior work by design (`docs/audits/simplification-20260520T181054Z/candidate-matrix.md:6-14`). Its matrix maps SIMP20-022/023 to static route/provenance guard and SIMP20-030 to release dynamic-version workflow bug merged into `trade-trace-nkfz` (`candidate-matrix.md:57-66`). Current files show the guard/dynamic-version changes in place.
- Duplicate disposition for SIMP20 reports no newly-created simplification Bead in the threshold duplicate scan and routes residual overlap through reconciliation rather than duplicate implementation Beads (`docs/audits/simplification-20260520T181054Z/duplicate-disposition.md:25-30`).

## Caveats

- I did not run full tests, `python -m build`, or npm commands. `npm run build` would mutate packaged static assets/provenance; build artifacts are outside read-only lane scope.
- Prior artifact review was reconciliation-oriented and sampled through summaries/matrices/readbacks plus representative bodies, not a semantic re-audit of every historical line as if it were current product documentation.
- `git status --short` before writing this file already showed `?? docs/reviews/`; this lane added/modified only the requested lane packet under that directory.

## Side-effect declaration

Created/modified exactly one allowed file:

- `docs/reviews/repo-audit-20260521T173511Z/lane-build-package-ci-prior-audit-reconciliation.md`

No Beads writes, no source/product/test/doc edits outside this report, no package-manager cleanup/install, no formatters, no pushes/publishes, and no destructive commands were performed.
