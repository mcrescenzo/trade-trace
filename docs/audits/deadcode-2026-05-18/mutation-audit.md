# Mutation audit — deadcode hunt 2026-05-18

Generated: 2026-05-19T03:19:41.973878Z
Repo: /home/hermes/code/trade-trace
Epic: trade-trace-5lx
Final gate: trade-trace-6vd

## Planned creates
- CRT-001 -> task P3, needs-owner-confirmation/public-api cleanup-candidate.
- CRT-002 -> task P3, needs-owner-confirmation/public-api cleanup-candidate.
- TST-001 -> task P4 cleanup-candidate.
- DOC-001 -> bug P2 docs-truth stale-contract.
- DOC-002A -> bug P2 docs-truth stale package dependency docs.
- DOC-002B -> bug P2 docs-truth stale CLI/tool-surface docs.

## Matrix-only / duplicate dispositions
- TST-002 -> duplicate of existing trade-trace-7e2; no new bead, no final-gate blocker.
- DOC-003 -> keep_no_bead (agent docs/project policy/generator caveats).
- DOC-004 -> keep_no_bead (generic Beads README/tool-generated boilerplate caveat).

## Planned graph
- Relate epic trade-trace-5lx to every new candidate bead.
- Make final gate trade-trace-6vd depend on each new candidate bead.
- Do not make final gate depend on TST-002/DOC-003/DOC-004.

## Pre-snapshot
See pre-mutation-snapshot.txt.

## Advisor gate
See advisor-review.md. Advisor requested splitting DOC-002 into DOC-002A/DOC-002B and keeping CRT items owner-confirmation only.

## Applied ID map
To be appended after mutation.

## Applied ID map
- CRT-001 -> trade-trace-xeq
- CRT-002 -> trade-trace-mky
- TST-001 -> trade-trace-bmf
- DOC-001 -> trade-trace-cey
- DOC-002A -> trade-trace-rzb
- DOC-002B -> trade-trace-ahz

## Command log summary
- bd create Decide disposition for unused process-global clock accessors --type task --priority P3 --labels dead-code,deadcode-hunt,deadcode:exhaustive-20260518,domain:core-runtime,needs-owner-confirmation,public-api,cleanup-candidate --body-file docs/audits/deadcode-2026-05-18/bead-bodies/CRT-001.md --acceptance See description acceptance criteria and candidate provenance. --json -> rc=0 stdout={
  "acceptance_criteria": "See description acceptance criteria and candidate provenance.",
  "created_at": "2026-05-19T03:20:10.34621108Z",
  "created_by": "Michael Crescenzo",
  "description": "Context:\nDomain: core-runtime\nAffected surface: trade_trace.clock.default_clock,set_default_clock,_DEF stderr=
- bd dep relate trade-trace-5lx trade-trace-xeq -> rc=0 stdout=✓ Linked trade-trace-5lx ↔ trade-trace-xeq stderr=
- bd dep add trade-trace-6vd trade-trace-xeq -> rc=0 stdout=✓ Added dependency: trade-trace-6vd (Final verification: exhaustive deadcode hunt 2026-05-18) depends on trade-trace-xeq (Decide disposition for unused process-global clock accessors) (blocks) stderr=
- bd create Decide disposition for unused events.write_event wrapper --type task --priority P3 --labels dead-code,deadcode-hunt,deadcode:exhaustive-20260518,domain:core-runtime,needs-owner-confirmation,public-api,cleanup-candidate --body-file docs/audits/deadcode-2026-05-18/bead-bodies/CRT-002.md --acceptance See description acceptance criteria and candidate provenance. --json -> rc=0 stdout={
  "acceptance_criteria": "See description acceptance criteria and candidate provenance.",
  "created_at": "2026-05-19T03:20:11.318598323Z",
  "created_by": "Michael Crescenzo",
  "description": "Context:\nDomain: core-runtime\nAffected surface: trade_trace.events.log.write_event / trade_trace.even stderr=
- bd dep relate trade-trace-5lx trade-trace-mky -> rc=0 stdout=✓ Linked trade-trace-5lx ↔ trade-trace-mky stderr=
- bd dep add trade-trace-6vd trade-trace-mky -> rc=0 stdout=✓ Added dependency: trade-trace-6vd (Final verification: exhaustive deadcode hunt 2026-05-18) depends on trade-trace-mky (Decide disposition for unused events.write_event wrapper) (blocks) stderr=
- bd create Remove unused _all_columns helper from credential security tests --type task --priority P4 --labels dead-code,deadcode-hunt,deadcode:exhaustive-20260518,domain:tests,cleanup-candidate --body-file docs/audits/deadcode-2026-05-18/bead-bodies/TST-001.md --acceptance See description acceptance criteria and candidate provenance. --json -> rc=0 stdout={
  "acceptance_criteria": "See description acceptance criteria and candidate provenance.",
  "created_at": "2026-05-19T03:20:12.113307407Z",
  "created_by": "Michael Crescenzo",
  "description": "Context:\nDomain: tests-fixtures\nAffected surface: tests.security.test_no_credentials._all_columns\nCa stderr=
- bd dep relate trade-trace-5lx trade-trace-bmf -> rc=0 stdout=✓ Linked trade-trace-5lx ↔ trade-trace-bmf stderr=
- bd dep add trade-trace-6vd trade-trace-bmf -> rc=0 stdout=✓ Added dependency: trade-trace-6vd (Final verification: exhaustive deadcode hunt 2026-05-18) depends on trade-trace-bmf (Remove unused _all_columns helper from credential security tests) (blocks) stderr=
- bd create Fix broken local markdown links after docs path moves --type bug --priority P2 --labels dead-code,deadcode-hunt,deadcode:exhaustive-20260518,domain:docs,bug,docs-truth,risk:stale-contract --body-file docs/audits/deadcode-2026-05-18/bead-bodies/DOC-001.md --acceptance See description acceptance criteria and candidate provenance. --json -> rc=0 stdout={
  "acceptance_criteria": "See description acceptance criteria and candidate provenance.",
  "created_at": "2026-05-19T03:20:12.835760269Z",
  "created_by": "Michael Crescenzo",
  "description": "Context:\nDomain: packaging-ci-docs\nAffected surface: local markdown links\nCandidate: DOC-001 from ex stderr=
- bd dep relate trade-trace-5lx trade-trace-cey -> rc=0 stdout=✓ Linked trade-trace-5lx ↔ trade-trace-cey stderr=
- bd dep add trade-trace-6vd trade-trace-cey -> rc=0 stdout=✓ Added dependency: trade-trace-6vd (Final verification: exhaustive deadcode hunt 2026-05-18) depends on trade-trace-cey (Fix broken local markdown links after docs path moves) (blocks) stderr=
- bd create Reconcile package/dependency docs with current pyproject embeddings posture --type bug --priority P2 --labels dead-code,deadcode-hunt,deadcode:exhaustive-20260518,domain:docs,bug,docs-truth,risk:stale-contract --body-file docs/audits/deadcode-2026-05-18/bead-bodies/DOC-002A.md --acceptance See description acceptance criteria and candidate provenance. --json -> rc=0 stdout={
  "acceptance_criteria": "See description acceptance criteria and candidate provenance.",
  "created_at": "2026-05-19T03:20:13.595892233Z",
  "created_by": "Michael Crescenzo",
  "description": "Context:\nDomain: packaging-ci-docs\nAffected surface: sqlite-vec/sentence-transformers package docs\nC stderr=
- bd dep relate trade-trace-5lx trade-trace-rzb -> rc=0 stdout=✓ Linked trade-trace-5lx ↔ trade-trace-rzb stderr=
- bd dep add trade-trace-6vd trade-trace-rzb -> rc=0 stdout=✓ Added dependency: trade-trace-6vd (Final verification: exhaustive deadcode hunt 2026-05-18) depends on trade-trace-rzb (Reconcile package/dependency docs with current pyproject embeddings posture) (blocks) stderr=
- bd create Reconcile docs that advertise unregistered CLI/tool command surfaces --type bug --priority P2 --labels dead-code,deadcode-hunt,deadcode:exhaustive-20260518,domain:docs,bug,docs-truth,risk:stale-contract --body-file docs/audits/deadcode-2026-05-18/bead-bodies/DOC-002B.md --acceptance See description acceptance criteria and candidate provenance. --json -> rc=0 stdout={
  "acceptance_criteria": "See description acceptance criteria and candidate provenance.",
  "created_at": "2026-05-19T03:20:14.367478199Z",
  "created_by": "Michael Crescenzo",
  "description": "Context:\nDomain: packaging-ci-docs\nAffected surface: config.set/export.drain/forecast.show/decision.s stderr=
- bd dep relate trade-trace-5lx trade-trace-ahz -> rc=0 stdout=✓ Linked trade-trace-5lx ↔ trade-trace-ahz stderr=
- bd dep add trade-trace-6vd trade-trace-ahz -> rc=0 stdout=✓ Added dependency: trade-trace-6vd (Final verification: exhaustive deadcode hunt 2026-05-18) depends on trade-trace-ahz (Reconcile docs that advertise unregistered CLI/tool command surfaces) (blocks) stderr=

## Concurrent duplicate repair
- Final duplicate scan showed trade-trace-cey duplicated concurrent bughunt bead trade-trace-1zl. Removed trade-trace-6vd dependency on trade-trace-cey, unlinked it from trade-trace-5lx, and closed trade-trace-cey as duplicate. DOC-001 now merges into trade-trace-1zl.
- DOC-002B partially overlaps trade-trace-17p on `tt config set`, but remains active for export.drain, backup/restore, forecast.show/decision.show/edges.list coverage not shown in trade-trace-17p.
