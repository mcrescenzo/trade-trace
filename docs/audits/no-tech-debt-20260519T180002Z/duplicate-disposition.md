# Duplicate / overlap disposition

Run: repo-no-tech-debt 20260519T180002Z
Epic: trade-trace-gm28
Final gate: trade-trace-rznf

Advisor/user gate rejected bulk creation of the original accepted set. The reduced materialization deliberately reused existing canonical owner Beads where the no-tech row overlapped bughunt/deadcode/docs-truth work.

## Merged into existing Beads instead of duplicated

- CLI unknown-command JSON envelope -> trade-trace-kynj. Existing bughunt bead owns the concrete bug.
- CLI argument grammar/parser behavior -> trade-trace-pybt. Existing bughunt bead owns repeated/comma array parser contract failure.
- Golden parity developer-home leak -> trade-trace-68ew. Existing test-harness bug owns this failure.
- Golden/NDJSON stale review.bundle expectation -> trade-trace-boqe. Existing bug owns stale test expectation.
- MCP stdio/schema/help coverage -> trade-trace-3i33. Existing bead owns missing tool schemas/help for agent-safe MCP usage; no fresh generic coverage bead was created.
- PRD embeddings flag docs drift -> trade-trace-0tdt. Existing docs-truth bug owns this exact drift.
- Embeddings/sqlite-vec capability drift -> trade-trace-mehh. Existing deadcode/docs-truth bead owns this theme.
- Residual report/watch docs drift -> trade-trace-ftnu. Existing stale report docs bead owns this theme.
- report.compare docs/API contract drift -> trade-trace-cs0r. Existing public API stale-contract bug owns this theme.

## Deferred / not materialized

- Test fixture idempotency enforcement: not created fresh. Current session received a tool/user denial for `bd show trade-trace-cpz2`; do not retry that probe. Also the row had contamination risk from concurrent idempotency/test changes. Treat as merge-only/deferred until clean-tree reproduction is available.
- Markdown/link checker gap: weak without concrete broken anchor/link evidence or release/docs gate failure.
- Dogfood fixture isolation: weak without concrete cross-test contamination evidence.
- Security match offset semantics: API/design semantics not bundled into the log-redaction cap task.
- Edge-audit playbook_version orphan coverage: split from direct memory.link endpoint validation; create a separate investigation only if edge-audit evidence warrants it.

## Duplicate scan note

`bd find-duplicates --status open --threshold 0.45 --limit 100 --json` returned many high-similarity pairs dominated by concurrent simplification backlog items and template-style QC/final-gate titles. The no-tech rows above were checked manually against the live open list and canonical owner IDs; no newly-created no-tech Bead is intended as a duplicate of those owner Beads.
