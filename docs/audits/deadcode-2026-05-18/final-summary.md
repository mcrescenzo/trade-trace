# Exhaustive deadcode hunt final summary

Generated: 2026-05-19T03:26:19Z
Repo: `/home/hermes/code/trade-trace`
Scope: exhaustive tracked-file deadcode backlog/materialization/readback phase for manifest `docs/audits/deadcode-2026-05-18/tracked-manifest.json`.

## Coverage

- Tracked files in manifest: 158
- Coverage ledger rows: 158
- Classifications: source 59, test 75, docs-contract 16, config 6, deploy 1, packaging 1
- Owner lanes: core-runtime 27, tools-transports 19, reports-memory 12, tests-fixtures 75, packaging-ci-docs 20, beads-tracking 4, misc 1
- Discovery lanes: core runtime, tools/transports, reports/memory, tests/fixtures/security, packaging/CI/docs, Beads/config surfaces
- Reachability lenses: entrypoint map, reference search, public/importable surface review, dynamic/plugin surface caveats, docs/tests contract comparison, safe-removal validation/gap recording

This is exhaustive over the tracked-file manifest/coverage ledger; it is not a guarantee that no dead code remains.

## Findings and dispositions

- Raw candidate rows: 9
- Confirmed active materialized candidates: 3
  - `TST-001` -> `trade-trace-bmf` — remove unused `_all_columns` helper from credential security tests
  - `DOC-002A` -> `trade-trace-rzb` — reconcile package/dependency docs with current pyproject embeddings posture
  - `DOC-002B` -> `trade-trace-ahz` — reconcile docs that advertise unregistered CLI/tool command surfaces
- Needs owner confirmation / public-surface cleanup candidates: 2
  - `CRT-001` -> `trade-trace-xeq` — decide disposition for unused process-global clock accessors
  - `CRT-002` -> `trade-trace-mky` — decide disposition for unused `events.write_event` wrapper
- Merged/duplicate dispositions: 2
  - `TST-002` -> existing `trade-trace-7e2`; also overlaps concurrent `trade-trace-m8c`; no new deadcode blocker
  - `DOC-001` -> initially `trade-trace-cey`, then closed/unwired as duplicate of `trade-trace-1zl`
- Kept matrix-only: 2
  - `DOC-003` generic agent instructions; no bead
  - `DOC-004` generic `.beads` README; no bead

## Beads graph

- Epic: `trade-trace-5lx`
- Final gate: `trade-trace-6vd`
- Membership model: relation-based epic navigation, not parent-child readiness
  - `bd children trade-trace-5lx` returns `[]` by design
  - `bd dep list trade-trace-5lx` shows the final gate plus five active materialized candidates via `relates-to`
- Execution/readiness gate: `trade-trace-6vd` depends only on active materialized blockers:
  - `trade-trace-ahz`
  - `trade-trace-bmf`
  - `trade-trace-mky`
  - `trade-trace-rzb`
  - `trade-trace-xeq`

## Verification

Latest corrected readback artifact: `docs/audits/deadcode-2026-05-18/final-readback-after-duplicate-repair.txt`

- `bd dep cycles`: no dependency cycles detected
- `bd lint`: no template warnings found
- `bd orphans`: no orphaned issues found
- Duplicate scan: 100 mechanical pairs reported across the wider Beads DB; none involve the active deadcode candidate IDs or final gate. DOC-001 and TST-002 duplicate dispositions are recorded in the candidate matrix and final gate body.
- Body-integrity readback: `docs/audits/deadcode-2026-05-18/body-integrity-readback.json` covers the five active candidate beads plus final gate and passed required-section checks.
- Advisor gates:
  - Candidate disposition advisor review saved at `docs/audits/deadcode-2026-05-18/advisor-review.md`
  - Final-check advisor approved reporting the local backlog/materialization/readback phase complete, with caveats that cleanup implementation, remote Beads sync, and artifact publication must not be overclaimed.

## Artifact packet

Primary artifacts:

- `tracked-manifest.json`
- `coverage-ledger.csv`
- `domain-map.md`
- `lane-packets.md`
- `static-analysis.json`
- `markdown-link-check.json`
- `advisor-evidence-packet.md`
- `advisor-review.md`
- `candidate-matrix.json`
- `mutation-audit.md`
- `mutation-command-log.json`
- `bead-bodies/*.md`
- `body-integrity-readback.json`
- `final-readback-raw.txt`
- `final-readback-after-duplicate-repair.txt`
- `final-summary.md`

## Persistence status

- Beads persistence: local Beads DB readback passed. No `bd dolt push` was attempted.
- Git artifact persistence: this summary is intended to be committed with the audit artifacts.

## Caveats / remaining work

- Cleanup/removal is not done. This phase produced and verified the backlog.
- Public/importable candidates `CRT-001` and `CRT-002` require owner confirmation before removal.
- Security tests are known red because `trade_trace.exporter.SECRET_PATTERNS` is missing; this is tracked separately as `trade-trace-7e2` / concurrent `trade-trace-m8c` and was not fixed by this deadcode hunt.
- Broken link and docs-contract findings are materialized as bugs for follow-up, not repaired here.
