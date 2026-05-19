# Simplification duplicate disposition

Materialization was user-authorized for epic `trade-trace-mea1` after the original moving-target report-only closeout.

Semantic dedupe source of truth is `candidate-matrix.json` / `candidate-matrix-summary.json`, not mechanical title/body similarity. Rows were deduped by root complexity cause, affected behavior, fix surface, owner, validation path, and risk profile.

Materialized:
- 11 direct behavior-preserving simplification task rows.
- 5 investigation/design-first task rows with `investigation` and `needs-more-evidence` labels.
- 4 QC gate beads and 1 final verification gate.

Not materialized:
- SIMP-002, SIMP-005, SIMP-010 deferred.
- SIMP-017 rejected intentional-complexity guardrail.

Expected duplicate-scan caveat:
Generated Beads share common provenance, behavior-preservation, and validation prose. Mechanical duplicate scans may over-report similarity. Do not close/merge generated simplification beads from similarity alone; compare row IDs, evidence, validation command, and owner surface first.
