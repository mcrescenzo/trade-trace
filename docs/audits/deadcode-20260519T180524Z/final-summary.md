# Deadcode refresh 2026-05-19 final summary

Coverage:
- Mode: exhaustive refresh over current tracked manifest, with historical audit artifact exclusions.
- Tracked files: 330 (`tracked-manifest.json`).
- Domains: storage-docs, tools-tests, reports-public-api, docs-reports, docs-historical/audit artifacts.
- Discovery lanes: 5 lane packets captured in `lane-packets.md`.

Findings:
- Raw candidates: 5.
- Materialized new cleanup/owner-confirmation/docs-truth beads: 3 (`trade-trace-mehh`, `trade-trace-8bdd`, `trade-trace-ftnu`).
- Merged into existing canonical bead: 1 (`DC-REFRESH-003` -> `trade-trace-cs0r`; closed duplicate `trade-trace-yv9z`).
- Matrix-only/deferred: 1 (`DC-REFRESH-005`).
- Confirmed safe immediate deletion tasks: 0; all cleanup remains task-backed with validation/owner gates.

Beads:
- Epic: `trade-trace-ldru`.
- Final verification gate: `trade-trace-cap6`.
- Membership model: relation-based epic plus final gate blockers. `bd children trade-trace-ldru` is empty by design.
- Navigation: `bd dep list trade-trace-ldru`; execution gate: `bd dep list trade-trace-cap6`.

Verification:
- `bd dep cycles`: no cycles.
- `bd orphans`: no orphaned issues.
- `bd lint`: only four pre-existing unrelated bug template warnings remain.
- Duplicate scan: no open duplicate remains for the deadcode `DOCUMENTED_GROUP_BY` candidate after merge; remaining duplicate hits are unrelated/mechanical, including audit epic overlap.
- Body integrity keyword guard: passed for materialized candidates and final gate.

Artifacts:
- Candidate matrix: `docs/audits/deadcode-20260519T180524Z/candidate-matrix.json`.
- Coverage ledger: `docs/audits/deadcode-20260519T180524Z/coverage-ledger.jsonl`.
- Mutation audit: `docs/audits/deadcode-20260519T180524Z/mutation-audit.md`.
- Final raw readback: `docs/audits/deadcode-20260519T180524Z/final-readback-raw.txt`.
- Body integrity readback: `docs/audits/deadcode-20260519T180524Z/body-integrity-readback.json`.

Caveats:
- `trade-trace-mehh` and `trade-trace-cs0r` require owner/public-surface confirmation before removal/deprecation.
- `watch.stale` may be a planned alias; if so docs must mark it future/deferred or implementation must register/test it.
- This materializes a cleanup/docs-truth backlog; it does not remove code.
