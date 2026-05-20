Context:
Final verification gate for repo-simplification-review 20260520 under epic trade-trace-w3vs.

Current complexity:
This gate ensures the materialized backlog remains behavior-preserving, non-duplicative with the closed 20260519 simplification backlog, and graph-readable.

Required verification:
- Confirm all materialized SIMP20 task/investigation beads are closed, deferred with explicit reasons, or superseded.
- Confirm investigation-first beads closed with findings before any implementation refactor work was created.
- Confirm residual reconciliation bead resolved duplicate/reopen decisions for qs5v/qnxt/x0po overlap.
- Run graph/readback hygiene:
  - bd lint
  - bd orphans
  - bd dep cycles
  - bd dep list trade-trace-w3vs
  - bd graph trade-trace-w3vs
  - bd find-duplicates --status open --threshold 0.45 --limit 100 --json
- Confirm representative `bd show` readbacks preserve evidence, validation, acceptance criteria, and provenance.
- Confirm git status and any repo-local audit artifacts are committed/pushed if the active session scope requires it.

Acceptance criteria:
- No open material simplification row is left without a disposition.
- Duplicate/reconciliation decisions are recorded.
- Final graph/readback/lint/orphan checks are recorded.
- Epic trade-trace-w3vs is ready to close only after this gate passes.

Provenance:
Created by repo-simplification-review 20260520 materialization.
