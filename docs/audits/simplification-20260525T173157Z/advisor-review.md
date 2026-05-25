# Advisor/review gate

Advisor result: proceed with conservative selective materialization.

Key review constraints applied:
- Direct tasks must include explicit behavior-preservation contracts and validation commands.
- CLCM-001 must preserve CLI numeric-bound-only policy versus MCP stdio full-schema validation exactly.
- TLMW-01 must pin idempotency, event ordering, and UnitOfWork boundaries.
- RPT-A/RPT-B require registration/cursor characterization before refactor.
- AMS-002 requires endpoint-policy, retry, timeout, and scrubbing validation.
- STORAGE-003, RPT-D, and AMS-003 are investigation/design-first because direct refactors could alter replay/timestamp/schema contracts.
- STORAGE-002 is deferred because projection streaming is behavior-heavy and current performance pressure is not proven.

Prior-overlap readbacks checked:
- `trade-trace-0apb`: JSONL serialization path decision; STORAGE-001 row hydration remains additive.
- `trade-trace-eijx`: schema/event registry investigation; STORAGE-003 must be reconciliation/investigation only.
- `trade-trace-4v31`: source.attach metadata/registration; TLMW-01 targets remaining write-kernel duplication.
- `trade-trace-qnxt`, `trade-trace-73w6`, `trade-trace-s904`, `trade-trace-2drt`: prior report row/envelope/filter/helper work; RPT-A/B/C/D are distinct or investigation-only as marked.


## Final live-state overlap note

After materializing the simplification backlog, final live Beads verification showed concurrently opened `bughunt:exhaustive-20260525` issues that were not present in the compact pre-materialization open list used for duplicate screening. Most are separate bughunt findings, not simplification duplicates. One overlap was actionable:

- `trade-trace-6fx7` (Polymarket Retry-After handling can stall adapter calls) intersects simplification bead `trade-trace-17k1` / `AMS-002` (Polymarket retry-loop consolidation). `trade-trace-17k1` now depends on `trade-trace-6fx7` and has an overlap note requiring the bug to be fixed or explicitly folded before simplification.

Other new bughunt issues (`trade-trace-dzcf`, `trade-trace-2wwa`, `trade-trace-e0my`, `trade-trace-q3li`, `trade-trace-k3ug`, `trade-trace-z6ml`, `trade-trace-te6p`) were treated as separate defect/remediation tracks rather than semantic simplification duplicates. Future implementers should re-run `bd list --status open --flat --limit 0 --sort id` before claiming simplification beads.
