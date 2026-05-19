Context:
Final verification/readback gate for exhaustive deadcode hunt epic trade-trace-5lx.

Purpose:
Block hunt closeout until all active materialized candidate cleanup/bug beads have been read back and the audit artifacts, graph, duplicates, and persistence story are coherent.

Active materialized blocker IDs:
- CRT-001: trade-trace-xeq
- CRT-002: trade-trace-mky
- TST-001: trade-trace-bmf
- DOC-002A: trade-trace-rzb
- DOC-002B: trade-trace-ahz

Merged/closed duplicate dispositions:
- DOC-001: originally materialized as trade-trace-cey, then closed/unwired as duplicate of concurrent bughunt bead trade-trace-1zl.
- TST-002: duplicate of existing trade-trace-7e2 and concurrent bughunt bead trade-trace-m8c; no new deadcode blocker.

Matrix-only / non-blocker dispositions:
- DOC-003: keep_no_bead due agent-doc/project-policy caveats.
- DOC-004: keep_no_bead due generated/generic .beads README caveat.

Validation steps:
- Re-read candidate matrix and confirm every row disposition matches materialization status.
- Run bd dep cycles.
- Run bd lint and explain unrelated/pre-existing warnings.
- Run bd orphans and explain unrelated/pre-existing orphans.
- Run bd find-duplicates for open issues and disposition mechanical overlaps.
- Run bd dep list and bd graph for epic trade-trace-5lx.
- Run bd dep list for this final gate and verify it depends on the active materialized candidates above only.
- Run body-integrity readback for every active materialized candidate bead plus this gate.
- Verify audit artifacts are present and committed/pushed when repo policy permits.
- Run scoped project validation appropriate to audit artifacts.

Acceptance criteria:
- Active materialized candidate beads include evidence, reference-search scope, public/dynamic caveats, duplicate rationale, validation/gap, acceptance criteria, labels, and provenance back to the matrix.
- Relation-based navigation from epic trade-trace-5lx is complete.
- This final gate blocks only active materialized candidate work, not rejected/keep/duplicate rows.
- Dependency graph has no cycles.
- Candidate matrix, lane packets, advisor packet, mutation audit, and final summary artifacts are durable.
- Beads local readback, Dolt remote sync if required/attempted, and Git commit/push status are reported separately.

Provenance:
Created by repo-deadcode-hunt exhaustive run 2026-05-18. Updated after concurrent duplicate resolution at 2026-05-19T03:22:28.554278Z.
