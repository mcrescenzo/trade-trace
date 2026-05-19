Context:
Final verification / truthfulness gate for exhaustive Trade Trace bughunt refresh `20260519T175941Z`.

Acceptance criteria:
- Candidate matrix maps every raw candidate to accept/merge/reject/defer.
- Accepted candidates are either materialized as one canonical bug bead or merged into an existing bead with a durable note.
- Epic membership is relation-based and read back with `bd dep list <epic-id>` / label query.
- Duplicate scan dispositions are recorded.
- `bd dep cycles`, `bd lint || true`, `bd orphans || true`, representative `bd show` readbacks, and git status are saved under `docs/audits/bughunt-20260519T175941Z/verification/`.
- Final report artifact captures coverage, counts, IDs, caveats, artifact disposition, and push/persistence truth.

This gate is a short-lived evidence container and should be closed only after live graph verification succeeds.
