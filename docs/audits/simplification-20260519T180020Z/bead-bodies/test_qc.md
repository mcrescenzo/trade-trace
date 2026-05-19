Context:
Gate for materialized simplification epic trade-trace-mea1.

Purpose:
Run/record test-support behavior preservation after fixture/builder/security-test helper simplifications. Verify isolation, direct-SQL intentionality, MCP setup parity, and no-network enforcement variants.

Acceptance criteria:
- All blocking simplification beads are closed with evidence.
- Required validation/readback output is appended to this bead or the audit artifact.
- No deferred/rejected matrix rows are silently promoted.
- Graph checks (`bd dep cycles`, `bd graph trade-trace-mea1`) remain healthy.

Provenance:
User-authorized materialization of repo-simplification-review artifacts at /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.