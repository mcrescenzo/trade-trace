# Duplicate / overlap disposition

Open-Beads duplicate scan before materialization returned only unrelated or expected pairs:
- `trade-trace-2vq5` / `trade-trace-4exy`: future reporting contract features, not simplification materialization.
- `trade-trace-hxcn` / `trade-trace-no6z`: different audit-family epics (deadcode vs bughunt), not simplification.
- `trade-trace-nf2k` / `trade-trace-no6z`: bughunt gate/epic similarity.

Semantic prior-backlog decisions:
- Do not duplicate closed test-helper, release-doc, broad memory/report, source.attach registration, report envelope/filter, or JSONL serialization candidates.
- New rows are additive only where the cited code surface was not already completed by prior beads.
- Generated Bead bodies will share a common template; any post-materialization mechanical duplicate scan should be interpreted against `candidate-matrix.json`, not body-template similarity alone.


## Final live-state overlap note

After materializing the simplification backlog, final live Beads verification showed concurrently opened `bughunt:exhaustive-20260525` issues that were not present in the compact pre-materialization open list used for duplicate screening. Most are separate bughunt findings, not simplification duplicates. One overlap was actionable:

- `trade-trace-6fx7` (Polymarket Retry-After handling can stall adapter calls) intersects simplification bead `trade-trace-17k1` / `AMS-002` (Polymarket retry-loop consolidation). `trade-trace-17k1` now depends on `trade-trace-6fx7` and has an overlap note requiring the bug to be fixed or explicitly folded before simplification.

Other new bughunt issues (`trade-trace-dzcf`, `trade-trace-2wwa`, `trade-trace-e0my`, `trade-trace-q3li`, `trade-trace-k3ug`, `trade-trace-z6ml`, `trade-trace-te6p`) were treated as separate defect/remediation tracks rather than semantic simplification duplicates. Future implementers should re-run `bd list --status open --flat --limit 0 --sort id` before claiming simplification beads.
