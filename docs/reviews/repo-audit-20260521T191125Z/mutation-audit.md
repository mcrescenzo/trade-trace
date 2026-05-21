# Mutation audit — repo-audit-20260521T191125Z

## Applied mutation
- Reused `trade-trace-4ju9`.
- Created `trade-trace-ckcv`, `trade-trace-6otj`, and `trade-trace-2qia`.
- Related bugs/gate to epic; gate depends on both bugs.
- Updated `trade-trace-od93` with merged test-gap note.

## Verification
- `bd dep cycles`: no cycles.
- `bd lint`: no warnings after Steps-to-Reproduce repair.
- `bd orphans`: none.
- `bd find-duplicates`: count 0.
- Artifacts parse as JSON/YAML.
- Targeted tests: 53 passed.
