## Context
Final verification gate for repo-audit refresh `repo-audit-20260521T191125Z`.

## Scope
- `trade-trace-ckcv` current_exposure filter scope bug.
- `trade-trace-6otj` current_exposure anomaly bucket key bug.

## Success Criteria
- Both finding Beads are closed with validation notes.
- Candidate matrix maps accepted rows to live Bead IDs.
- Graph has no cycles and duplicate scan dispositions are recorded.
