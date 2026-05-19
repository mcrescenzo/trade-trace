# Advisor review — deadcode hunt 2026-05-18

Advisor approved/directed these dispositions before materialization:

- CRT-001: owner-confirmation only, not confirmed cleanup.
- CRT-002: owner-confirmation only, not confirmed cleanup.
- TST-001: safe cleanup task if line-level evidence is included.
- TST-002: do not create; duplicate/merge existing P0 trade-trace-7e2.
- DOC-001: keep separate mechanical link-rot bug; do not split into 113 beads.
- DOC-002: split into two bugs because validation differs:
  - DOC-002A: packaging/install dependency docs stale vs pyproject.
  - DOC-002B: CLI/tool-surface docs stale vs registry/help.
- DOC-003/DOC-004: keep matrix-only.
- Final gate should depend only on materialized candidates, excluding duplicate/matrix-only rows.

Missing evidence requested by advisor and supplied before mutation:
- Artifact paths: markdown-link-check.json, registered-tools.txt, candidate-matrix.json.
- Line refs included in bead bodies.
- `bd show trade-trace-7e2` confirmed duplicate coverage.
- Fresh open/duplicate/cycle snapshot captured before mutation.
