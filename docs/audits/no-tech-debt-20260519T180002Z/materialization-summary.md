# No-tech-debt reduced materialization 2026-05-19

Epic: trade-trace-gm28
Final gate: trade-trace-rznf

## New narrowed Beads
- trade-trace-qasx: Add release distribution metadata validation before PyPI publish (maintenance, P3)
- trade-trace-3elt: Investigate schema/meta diagnostics for non-table migrations (investigation, P2)
- trade-trace-gkt3: Decide semantic-key event policy alignment (design, P3)
- trade-trace-40dz: Validate memory.link playbook_version endpoints against playbook_versions (maintenance, P2)
- trade-trace-dew2: Design JSONL replay taxonomy for landed write surfaces (design, P2)
- trade-trace-arcx: Validate memory.retain meta_json object shape at direct retain boundary (maintenance, P2)
- trade-trace-iip4: Investigate projection rebuild diagnostics for corrupt memory recall JSON (investigation, P2)
- trade-trace-7h2u: Decide position_id reopen semantics for replay and projections (design, P1)
- trade-trace-8n98: Harden log redaction behavior beyond secret scan input cap (maintenance, P2)

## Existing Beads reused instead of duplicated
- trade-trace-kynj: CLI unknown-command JSON envelope — Merged instead of fresh no-tech-debt bead; live bughunt bead already owns the concrete bug.
- trade-trace-pybt: CLI argument grammar/parser behavior — Merged/related; live bughunt bead owns repeated/comma array parser contract failure.
- trade-trace-68ew: Golden parity developer-home leak — Merged into existing golden parity/test-harness bug.
- trade-trace-boqe: Golden/NDJSON stale review.bundle expectation — Merged into existing test expectation bug rather than generic coverage debt.
- trade-trace-3i33: MCP stdio/schema/help coverage — Related rather than duplicated; existing bead owns missing tool schemas/help for agent-safe MCP usage.
- trade-trace-0tdt: PRD embeddings flag docs drift — Merged into existing docs-truth bug for journal.init --enable-embeddings no-op.
- trade-trace-mehh: Embeddings/sqlite-vec docs capability drift — Merged into existing deadcode/docs-truth bead.
- trade-trace-ftnu: Residual report/watch docs drift — Merged into existing stale report docs bead.
- trade-trace-cs0r: Report compare docs/API contract drift — Merged into existing public API stale-contract bug.

## Deferred / not materialized
- test fixture idempotency enforcement: Deferred/merge-only due live dirty-history contamination and existing idempotency work; do not create fresh until clean-tree reproduction.
- markdown/link checker gap: Weak without concrete broken anchor/link evidence or release gate failure.
- dogfood fixture isolation: Weak without concrete cross-test contamination evidence.
- security match offset semantics: Design/API semantics; not materialized with redaction-cap task.
- edge-audit playbook_version orphan coverage: Split from direct memory.link endpoint validation; create later only if separate edge-audit evidence warrants it.

## Notes
- This is a reduced materialization after advisor/user review, not a claim that the repo has no tech debt.
- Idempotency fixture debt was not freshly materialized because the prior `bd show trade-trace-cpz2` probe was denied and must not be retried in this session.
- Relation-based epic membership is used for navigation; final-gate blocking dependencies are used for closeout sequencing.
