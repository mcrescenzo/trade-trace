# trade-trace-ldru — Deadcode refresh 2026-05-19: materialize stale-code/docs cleanup backlog

Status: open
Type: epic
Priority: P2
Labels: dead-code, deadcode-hunt, deadcode:refresh-20260519, epic

## Description

Context:
Exhaustive refresh of the Trade Trace deadcode/stale-contract audit against the current tracked-file manifest.

Goal:
Build a durable, evidence-backed backlog for newly observed dead-code, stale-code, stale-docs, and owner-confirmation cleanup candidates since the closed 2026-05-18 exhaustive deadcode audit.

Scope:
- Repo: /home/hermes/code/trade-trace
- Branch at preflight: main
- Current tracked manifest: docs/audits/deadcode-20260519T180524Z/tracked-manifest.json (330 files)
- Prior same-scope closed audit: docs/audits/deadcode-2026-05-18, epic trade-trace-5lx
- Historical audit artifacts under audits/** and docs/audits/** are treated as docs-historical/grouped unless actively invoked by docs/CI/settings.

Disposition model:
- confirmed: concrete internal dead code with reference scope and validation path
- cleanup-candidate: likely cleanup with low risk or validation gap
- needs-owner-confirmation: public/importable/exported/dynamic surface that may be intentionally retained
- docs-truth bug: stale command/dependency docs with a concrete user/operator failure mode
- matrix-only-defer: retained in matrix without an executable bead to avoid speculative/noisy backlog

Graph rule:
This epic is the narrative/root index, not the executable cleanup task. Relation-based membership is used for navigation. `bd children <epic>` may be empty by design. Task-to-task dependencies and the final verification gate are authoritative for execution readiness.

Canonical artifacts and queries:
- Candidate matrix: docs/audits/deadcode-20260519T180524Z/candidate-matrix.json
- Coverage ledger: docs/audits/deadcode-20260519T180524Z/coverage-ledger.jsonl
- Lane packets: docs/audits/deadcode-20260519T180524Z/lane-packets.md
- Label query: `bd list --status open --flat --limit 0 --sort id | grep 'deadcode:refresh-20260519'`
- Navigation: `bd dep list <epic-id>` and `bd graph <epic-id>`

Rule for adding candidates:
New items must cite evidence, reference-search scope, public/dynamic caveats, safe-removal validation or explicit validation gap, duplicate rationale, and provenance back to the candidate matrix.

Final close rule:
Close the final verification gate first after every materialized candidate is closed/deferred/superseded with notes and the matrix/materialized-ID readback is updated. Then close this epic.


## Notes



## Acceptance

Refresh backlog is navigable by relation/label, candidate dispositions are durable, and final verification gate closes after all materialized candidates are resolved.
