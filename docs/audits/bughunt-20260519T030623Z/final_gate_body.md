Context:
Synthesis/final-verification gate for exhaustive repo bughunt 2026-05-19.

Scope:
- Normalize all lane outputs into the central candidate matrix.
- Dedupe by failure mode/root cause/fix surface.
- Run advisor or independent substitute gate before materialization.
- Persist mutation audit and final verification readbacks.
- Confirm artifact disposition and Beads graph hygiene.

Validation:
- Candidate matrix has disposition for every raw candidate.
- Accepted bug beads are related to the root epic and carry required labels/evidence/acceptance.
- `bd dep cycles` is clean.
- Duplicate scan has a durable disposition.
- Final report artifact names coverage, findings, Beads readbacks, and caveats.
