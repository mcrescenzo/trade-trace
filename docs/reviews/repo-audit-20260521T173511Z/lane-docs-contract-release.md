# Lane report: docs-contract-release

Audit run: `repo-audit-20260521T173511Z`  
Scope fingerprint: `1901b8097953e720`  
Lane: `docs-contract-release`  
Mode: read-only audit; only this lane artifact was written.

## Method / commands and searches

- Parsed `manifest-coverage-ledger.yaml` for the 51 rows where `owner_lane: docs-contract-release`.
- Directly opened core release/docs surfaces with `read_file`: `README.md`, `SECURITY.md`, `AGENTS.md`/`CLAUDE.md` excerpts via script, `pyproject.toml`, `src/trade_trace/version.py`, `docs/RELEASE_CHECKLIST.md`, `docs/RELEASE_PROOF.md`, `docs/RELEASE_FINAL_GATE.md`.
- Source-scoped/static probes:
  - `python` manifest extraction for assigned rows.
  - `python` status-header scan over all assigned docs.
  - `python` assigned-doc markdown local-link checker: **0 broken local links** in assigned docs.
  - `python` AGENTS/CLAUDE similarity/excerpt probe.
  - `search_files` for release/status/current/TODO/deferred terms in tracked docs.
  - `search_files` in `src/` for documented tool names (`resolve.record`, `journal.bundle.status`, `report.mistakes`, `report.strengths`).
  - `git log --oneline --since='2026-05-19 23:59' -5`, `git rev-parse HEAD`, `git status --short` to ground release-proof staleness relative to the dated gate.
- No package-manager, formatter, destructive, Beads, push, publish, or shared-service mutation commands were run.

## Executive summary

Found **one accepted candidate**: a release/process contract bug in `docs/RELEASE_FINAL_GATE.md`. The document correctly labels its proof as historical and points readers to rerun the checklist, but its closing statement says the release is “shippable the moment” the operator runs the history rewrite and approves publish. Current HEAD has moved since the 2026-05-19 proof snapshot, so that line can bypass the checklist’s explicit current-HEAD validation requirement.

No accepted stale-contract findings were identified in README, SECURITY, AGENTS/CLAUDE, MCP setup docs, current architecture docs, or the assigned plan doc. Several docs are intentionally design/decision/historical artifacts and are marked as such with `Status:` headers.

## Candidate records

### DCR-20260521-001 — Final release gate says “shippable” after history rewrite without restating current-HEAD release proof

- **Title:** Release final gate can be read as allowing publish after history rewrite without rerunning current-HEAD proof
- **Lens(es):** bughunt / technical debt / release-process contract
- **remediation_track:** release-process-docs
- **owner_track:** docs-contract-release
- **Affected paths/symbols:**
  - `docs/RELEASE_FINAL_GATE.md` final usage/closure language
  - `docs/RELEASE_CHECKLIST.md` current validation gates
  - `docs/RELEASE_PROOF.md` dated proof artifact
- **Observed facts with evidence:**
  - `docs/RELEASE_FINAL_GATE.md:38-42` labels the final-gate proof snapshot as historical and says to rerun `docs/RELEASE_CHECKLIST.md` before publishing.
  - `docs/RELEASE_FINAL_GATE.md:93-94` again states the release proof snapshot is historical and says to rerun the checklist for current proof.
  - `docs/RELEASE_FINAL_GATE.md:103-105` then states: “The release is **shippable** the moment the operator runs the plan in `docs/RELEASE_HISTORY_REWRITE.md` and approves the publish workflow.” This omits the fresh current-HEAD proof precondition.
  - `docs/RELEASE_CHECKLIST.md:22-30` requires current pre-publish checks from a clean checkout: `ruff check src tests`, `mypy src`, `pytest -q`, `python -m build`, and `python -m twine check dist/*`.
  - `docs/RELEASE_CHECKLIST.md:52-55` explicitly says not to treat dated pytest counts in older release proof documents as current proof; rerun `pytest -q` for current HEAD or label reused counts as historical.
  - `docs/RELEASE_PROOF.md:3-7` is a proof artifact recorded 2026-05-19 against a prior post-piav commit and says upload is gated on operator execution/approval.
  - `git log --oneline --since='2026-05-19 23:59' -5` shows later commits at current HEAD, including `a1023ea Clean up Trade Trace init docs`; `git rev-parse HEAD` returned `a1023ea4f2d498e916acbcbe25eecc0570d873bf`.
- **Inferences:**
  - The final sentence is a stale/over-broad release contract because it can be read to make history rewrite + publish approval the only remaining blockers, even though the same doc/checklist require fresh validation for later HEADs.
  - This is process debt rather than a runtime code bug; the risk is accidental publish/tag decision based on historical proof after intervening commits.
- **Assumptions:**
  - The current audit HEAD is later than the 2026-05-19 proof snapshot, as suggested by the git log probe and the audit plan’s HEAD.
  - Release docs are intended to be executable guidance, not purely archival narrative.
- **Open questions:**
  - Should `docs/RELEASE_FINAL_GATE.md` be converted to an explicitly historical artifact, with `docs/RELEASE_CHECKLIST.md` as the only live release gate?
  - Should a machine-checkable release proof template be added so future proofs cannot omit the current HEAD SHA?
- **Validation command/gap:**
  - Static validation performed: direct file read and `git log`/`git rev-parse` proof of current HEAD.
  - Gap: did not run release gates (`ruff`, `mypy`, `pytest`, `build`, `twine`) because lane is read-only audit and the finding is about documentation contract wording, not whether current HEAD actually passes.
- **prior_match_status:** new
- **Duplicate/overlap notes:**
  - Related closed release/backlog items exist: `trade-trace-piav` (public HEAD scrub), `trade-trace-nkfz` (publish workflow versioning), and release gate/proof docs reference `trade-trace-a468`/`trade-trace-ox5c`. None in the provided inventory appears to cover this exact contradiction between final-gate wording and current-proof requirements.
- **Recommended disposition:** accept as small docs/process bug; fix wording, no product code change.
- **Proposed Bead:**
  - **Title:** Clarify final release gate requires fresh current-HEAD proof before publish
  - **Type:** bug
  - **Labels:** `repo-audit`, `audit-run:20260521T173511Z`, `track:release-process-docs`, `domain:docs-release`, `process-debt`
  - **Acceptance:**
    1. `docs/RELEASE_FINAL_GATE.md` no longer states the release is shippable solely after history rewrite + publish approval.
    2. Final-gate language explicitly requires rerunning `docs/RELEASE_CHECKLIST.md` on the exact commit to be tagged/published, or states that the document is historical and non-authoritative for later HEADs.
    3. Any release proof referenced for publish includes the exact git SHA and command outcomes for the publish candidate.

## Non-accepted observations / no-action notes

- `README.md:15-23` and `SECURITY.md:3-15` both describe the project as `0.0.x` pre-release; `src/trade_trace/version.py:1` is `0.0.1rc3`, so the broad status is consistent.
- `README.md:126-146` security claims cite specific tests. At least `tests/security/test_no_network_default.py` exists; deeper runtime verification belongs to source/security lanes.
- `AGENTS.md` and `CLAUDE.md` intentionally duplicate the generated Beads block but have different agent-specific framing. `AGENTS.md:3-8` documents this split; no simplification candidate accepted.
- Architecture docs broadly carry Status headers distinguishing shipped, partial, design, and decision artifacts. The status scan found no current architecture doc lacking a status marker in the assigned set.
- Assigned-doc local markdown link check found 0 broken relative links. Broken links from `frontend/console/node_modules/**` were ignored as generated/vendor dependency content outside this lane’s decisive scope.

## Per-assigned-manifest-row coverage

Treatment key: `opened` = directly opened with `read_file` or excerpt probe; `contract-checked` = included in status/link/search contract probes; `searched` = included in source-scoped content searches.

| Path | Treatment | Notes |
|---|---|---|
| `AGENTS.md` | opened; searched; contract-checked | Agent entrypoint compared with `CLAUDE.md`; intentional generated-block overlap noted. |
| `CLAUDE.md` | opened; searched; contract-checked | Agent workflow/build pointers scanned; no accepted stale contract. |
| `LICENSE` | contract-checked | MIT license path exists and README links to it. |
| `README.md` | opened; searched; contract-checked | Install/status/security/docs links checked; no accepted stale claim. |
| `SECURITY.md` | opened; searched; contract-checked | Supported-version/reporting posture checked against pre-release version. |
| `docs/AGENT_GUIDE.md` | contract-checked; searched | Tool names spot-checked in `src/`; no accepted stale contract. |
| `docs/AI_AGENT_MCP_GETTING_STARTED.md` | opened excerpt; contract-checked; searched | MCP setup/tool names spot-checked. |
| `docs/CLAUDE_CODE.md` | opened excerpt; contract-checked; searched | Client setup docs linked to canonical guide. |
| `docs/CLAUDE_DESKTOP.md` | opened excerpt; contract-checked; searched | Client setup docs linked to canonical guide. |
| `docs/CONSOLE.md` | searched; contract-checked | Status/release commands/provenance claims reviewed at docs-contract level. |
| `docs/IDE_MCP_SETUP.md` | opened excerpt; contract-checked; searched | Client setup docs linked to canonical guide. |
| `docs/PRD.md` | searched; contract-checked | Planning/status and deferred/live distinctions reviewed. |
| `docs/RELEASE_CHECKLIST.md` | opened; searched; contract-checked | Live release gate source of truth; used as candidate evidence. |
| `docs/RELEASE_FINAL_GATE.md` | opened; searched; contract-checked | Accepted candidate DCR-20260521-001. |
| `docs/RELEASE_HISTORY_REWRITE.md` | searched; contract-checked | Operator-gated destructive/shared-state plan; no commands run. |
| `docs/RELEASE_PROOF.md` | opened; searched; contract-checked | Historical proof artifact; used as candidate evidence. |
| `docs/VISION.md` | searched; contract-checked | North-star/planning status reviewed. |
| `docs/architecture/agent-workbench-dogfood-evidence.md` | contract-checked; searched | Status header present. |
| `docs/architecture/console-final-product-qa.md` | contract-checked; searched | Status header present. |
| `docs/architecture/console-ia-support-contract.md` | contract-checked; searched | Status header present. |
| `docs/architecture/console-release-gate.md` | contract-checked; searched | Status header present. |
| `docs/architecture/console-review.md` | contract-checked; searched | Status says shipped/superseded by clean-break React Console. |
| `docs/architecture/console-visual-review.md` | contract-checked; searched | Status header present. |
| `docs/architecture/console.md` | contract-checked; searched | Status header present. |
| `docs/architecture/contracts.md` | contract-checked; searched | Status/header and envelope references searched. |
| `docs/architecture/docs-taxonomy.md` | contract-checked; searched | Status header present. |
| `docs/architecture/dogfood-protocol.md` | contract-checked; searched | Status header present. |
| `docs/architecture/forecastbench-compatibility.md` | contract-checked; searched | Explicit design/not implemented status. |
| `docs/architecture/http-sse-subscribe.md` | contract-checked; searched | Explicit design/not implemented status. |
| `docs/architecture/imports.md` | contract-checked; searched | Status header present. |
| `docs/architecture/jsonl-replay-taxonomy.md` | contract-checked; searched | Decision/design status. |
| `docs/architecture/logging.md` | contract-checked; searched | Partial shipped-subset status. |
| `docs/architecture/market-scan-contract.md` | contract-checked; searched | Status header present. |
| `docs/architecture/memory-layer.md` | contract-checked; searched | Shipped/legacy draft status coexistence noted; no accepted issue. |
| `docs/architecture/migrations-split-investigation.md` | contract-checked; searched | Decision/investigation status. |
| `docs/architecture/operability.md` | contract-checked; searched | Status header present. |
| `docs/architecture/opportunity-analysis.md` | contract-checked; searched | Partial shipped-subset status. |
| `docs/architecture/persistence.md` | contract-checked; searched | Status header present. |
| `docs/architecture/position-reopen-semantics.md` | contract-checked; searched | Decision status. |
| `docs/architecture/release-gate-consolidation.md` | contract-checked; searched | Decision/plan status. |
| `docs/architecture/reporting-product.md` | contract-checked; searched | Decision status. |
| `docs/architecture/reports.md` | contract-checked; searched | Status header present. |
| `docs/architecture/review-bundle-decomposition-investigation.md` | contract-checked; searched | Decision status. |
| `docs/architecture/risk-units.md` | contract-checked; searched | Partial shipped-subset status. |
| `docs/architecture/schema-meta-diagnostics.md` | contract-checked; searched | Decision/investigation status. |
| `docs/architecture/schema-registry-investigation.md` | contract-checked; searched | Decision/investigation status. |
| `docs/architecture/scoring.md` | contract-checked; searched | Status header present. |
| `docs/architecture/security-adapter-investigation.md` | contract-checked; searched | Decision/plan status. |
| `docs/architecture/security.md` | contract-checked; searched | Status header present. |
| `docs/architecture/semantic-key-policy.md` | contract-checked; searched | Decision status. |
| `docs/plans/2026-05-21-trades-page-overhaul.md` | contract-checked; searched | Implemented architecture note; historical sequence marked. |

## Caveats

- This lane did not perform full runtime validation of every architecture claim; it checked docs contracts, status labeling, local links, and representative source references. Runtime/code correctness belongs to the source/test lanes.
- The workspace showed untracked `docs/reviews/` artifacts in `git status --short`; that is expected for this audit artifact directory. No product/source/test/docs files outside this lane report were modified.
