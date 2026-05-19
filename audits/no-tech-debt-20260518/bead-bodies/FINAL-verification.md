Context:
Final verification gate for no-tech-debt run no-tech-debt-20260518.

Purpose:
Keep no-tech-debt closeout blocked until all materialized accepted debt rows are resolved, deferred with notes, or explicitly superseded. This gate is not proof by itself; it is the sequencing checkpoint for graph/readback/hygiene verification.

Root epic: trade-trace-joz

Evidence:
- Coverage and candidate evidence are persisted in audits/no-tech-debt-20260518/coverage-ledger.jsonl, lane-reports/lane-*.md, and central-debt-matrix.json.
- Beads materialization/readback evidence is persisted in audits/no-tech-debt-20260518/mutation-audit-postwrite.json and verification/*.txt/json.
- This gate is intentionally blocked by every materialized candidate via `bd dep add trade-trace-kez5 <candidate-id>`; relation membership alone is not closeout proof.

Materialized candidates (37):
- DEBT-001: trade-trace-aq0
- DEBT-002: trade-trace-xpj
- DEBT-003: trade-trace-go2
- DEBT-004: trade-trace-05c
- DEBT-005: trade-trace-9zy
- DEBT-006: trade-trace-tka
- DEBT-007: trade-trace-r5k
- DEBT-008: trade-trace-30u
- DEBT-011: trade-trace-dhm
- DEBT-012: trade-trace-z4q
- DEBT-013: trade-trace-qis
- DEBT-014: trade-trace-wmz
- DEBT-015: trade-trace-0ib
- DEBT-016: trade-trace-amc
- DEBT-017: trade-trace-1up
- DEBT-018: trade-trace-m0h
- DEBT-019: trade-trace-aec
- DEBT-020: trade-trace-c2h
- DEBT-021: trade-trace-d4k
- DEBT-022: trade-trace-drt
- DEBT-023: trade-trace-iyt
- DEBT-024: trade-trace-zgz
- DEBT-025: trade-trace-d7a
- DEBT-026: trade-trace-bew
- DEBT-027: trade-trace-eo4
- DEBT-028: trade-trace-qc7
- DEBT-029: trade-trace-9gs
- DEBT-031: trade-trace-4rp
- DEBT-033: trade-trace-dff
- DEBT-034: trade-trace-29u0
- DEBT-035: trade-trace-7j1l
- DEBT-036: trade-trace-qfxw
- DEBT-037: trade-trace-67sg
- DEBT-038: trade-trace-2ifs
- DEBT-039: trade-trace-pqp2
- DEBT-040: trade-trace-ljl9
- DEBT-041: trade-trace-14iy

Required final verification before closing this gate:
- Re-read central-debt-matrix.json and confirm every accepted row maps to one bead and every merge/defer/reject row has a durable disposition.
- Run bd dep cycles.
- Run bd lint and bd orphans; fix or explicitly scope pre-existing warnings.
- Run bd find-duplicates and persist/disposition mechanical overlaps.
- Run bd dep list / graph for root epic trade-trace-joz.
- Run bd dep list for this final gate and verify every materialized candidate blocks it.
- Read back every materialized bead body for evidence, carrying cost/risk, bounded paydown, non-goals, validation/gap, duplicate rationale, labels, acceptance, and provenance.
- Verify artifacts are committed/pushed according to repo policy and distinguish Git sync from Beads local/Dolt persistence.

Acceptance criteria:
- All materialized no-tech-debt candidate beads are closed, deferred with explicit reason, or superseded.
- Candidate matrix and Beads readback reconcile exactly.
- Graph has no cycles and relation navigation works.
- Duplicate scan has durable disposition.
- Final report names coverage, blind spots, validation, and persistence truth.
