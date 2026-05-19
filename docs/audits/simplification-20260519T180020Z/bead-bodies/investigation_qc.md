Context:
Gate for materialized simplification epic trade-trace-mea1.

Purpose:
Verify all investigation-first simplification beads closed with findings/decision records before any downstream implementation refactors are created. No behavior-changing refactor may proceed without explicit characterized behavior and validation plan.

Acceptance criteria:
- All blocking simplification beads are closed with evidence.
- Required validation/readback output is appended to this bead or the audit artifact.
- No deferred/rejected matrix rows are silently promoted.
- Graph checks (`bd dep cycles`, `bd graph trade-trace-mea1`) remain healthy.

Provenance:
User-authorized materialization of repo-simplification-review artifacts at /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.