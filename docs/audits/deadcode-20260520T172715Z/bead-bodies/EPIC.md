Context:
Exhaustive repo-deadcode-hunt refresh for Trade Trace at HEAD 73aee82 on 2026-05-20.

Goal:
Materialize the evidence-backed cleanup/docs-truth backlog discovered in the current tracked-file manifest.

Repo / branch / scope:
- Repo: /home/hermes/code/trade-trace
- Branch: main
- Manifest: docs/audits/deadcode-20260520T172715Z/tracked-manifest.json
- Coverage ledger: docs/audits/deadcode-20260520T172715Z/coverage-ledger.jsonl
- Candidate matrix: docs/audits/deadcode-20260520T172715Z/candidate-matrix.json
- Lane packets: docs/audits/deadcode-20260520T172715Z/lane-packets.md

Dead-code definition:
Evidence-backed unreachable, unreferenced, stale, misleading, obsolete, duplicate, unused, or owner-confirmation cleanup surfaces. Grep absence alone was not accepted; candidates needed reference-search scope, entrypoint/public/dynamic caveats, validation command/gap, duplicate disposition, and advisor review.

Disposition model:
- confirmed: concrete repo-local dead/stale evidence with low false-positive risk.
- cleanup-candidate: repo-local non-use but public/future/dynamic caveats require careful implementation.
- needs-owner-confirmation: public/exported/product-intent question before removal.
- merge: candidate merged into an existing open bead instead of duplicated.
- keep/reject: durable matrix-only disposition; no implementation bead.

Bug vs cleanup rule:
Stale docs/CLI contract failures are bugs only when they cause concrete operator/agent command failure. Ordinary unused code is task/cleanup, not bug.

Membership model:
Relation-based narrative epic. Use `bd dep list <this-epic>` or label query; `bd children <this-epic>` may be empty by design.

Canonical query:
`bd list --status open --flat --limit 0 --sort id | grep 'deadcode:exhaustive-20260520'`

Graph rule:
This epic is the root index. The final verification gate depends on materialized candidate beads. Matrix-only/merged/rejected rows are recorded in artifacts and not blockers.

Rule for future candidates:
Do not add speculative cleanup. Add only with evidence + reference-search scope + public/dynamic caveats + safe-removal validation/gap + duplicate check + relation to this epic.

Final close rule:
Close materialized candidate beads first or explicitly merge/defer them. Then run final readback/body-integrity checks and close the final verification gate before closing this epic.
