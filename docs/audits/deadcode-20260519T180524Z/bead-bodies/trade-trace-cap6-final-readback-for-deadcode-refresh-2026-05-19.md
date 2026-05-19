# trade-trace-cap6 — Final readback for deadcode refresh 2026-05-19

Status: open
Type: task
Priority: P2
Labels: dead-code, deadcode-hunt, deadcode:refresh-20260519, final-verification, gate

## Description

Context:
Final verification gate for the 2026-05-19 exhaustive deadcode refresh backlog.

Purpose:
Verify that every materialized candidate from docs/audits/deadcode-20260519T180524Z/candidate-matrix.json has been resolved, deferred, or superseded with proof, and that matrix-only candidates remain intentionally non-executable.

Materialized blockers:
- Align optional embeddings docs and sqlite-vec capability reporting
- Remove unused internal test and decision-matrix helpers
- Decide disposition for stale exported DOCUMENTED_GROUP_BY
- Reconcile residual watch.stale docs with registered report.watchlist surface

Validation steps:
- Re-run candidate-specific validation commands from each blocker.
- Re-read docs/audits/deadcode-20260519T180524Z/candidate-matrix.json and confirm `materialized_bead_id` / matrix-only dispositions match live Beads.
- Run `bd dep cycles`, `bd lint`, `bd orphans`, and duplicate scan.
- Run `bd dep list <refresh-epic-id>` and `bd dep list <this-gate-id>` to verify relation navigation and real blockers.
- Run targeted tests/ruff for any code/test cleanup and registry/docs readbacks for docs-truth fixes.

Acceptance criteria:
- All materialized candidate beads are closed, deferred with owner-confirmation notes, or superseded with a concrete canonical owner.
- Matrix-only CLAUDE.md placeholder row remains non-blocking or has been intentionally promoted with matrix update.
- No dependency cycles or unexpected orphaned program work.
- Final summary artifact is refreshed and cites current git/Beads status.

Provenance:
Created by repo-deadcode-hunt refresh run docs/audits/deadcode-20260519T180524Z.


Evidence / reference-search readback for this gate:
- Canonical evidence artifacts: `docs/audits/deadcode-20260519T180524Z/candidate-matrix.json`, `coverage-ledger.jsonl`, `final-readback-raw.txt`, and `body-integrity-readback.json`.
- Reference-search scope is delegated to each materialized blocker and summarized in the candidate matrix.
- Final gate closure must confirm every materialized blocker still has evidence, reference-search scope, public/dynamic caveats, duplicate rationale, validation/gap, and provenance.

Reference search scope for the final gate: delegated to each materialized blocker and summarized in candidate-matrix.json; gate closure must verify each candidate retains reference search evidence.


## Notes

Closeout blocker noted 2026-05-19T18:19Z: local Beads graph/readback exists, but repo artifact publication is blocked by unrelated git state (main ahead by unrelated bughunt artifact commit and dirty tests/conftest.py). Do not close this gate until deadcode artifacts are regenerated/committed in scope and git/Beads persistence is reconciled.

## Acceptance

All materialized candidates are closed/deferred/superseded with proof; matrix/readback refreshed; Beads hygiene checks pass or caveats recorded.
