Goal:
Run an exhaustive, coverage-enumerated repo-wide bughunt for /home/hermes/code/trade-trace on branch main at the current working tree/HEAD, focused on concrete defects suitable for remediation.

Scope:
- In scope: tracked source, tests, docs-contract files, project config, packaging, CI, CLI/MCP contracts, storage/migrations, domain models/events, reports/scoring, security/privacy boundaries, and operational docs.
- Exclusions/grouped: Beads internal metadata under .beads/, LICENSE boilerplate, and generated/cache/runtime artifacts not tracked by git. Existing untracked audits/no-tech-debt-20260518 is adjacent prior audit evidence, not a member of this bughunt unless explicitly referenced by a candidate.

Bug definition:
Report only concrete failure modes: incorrect behavior relative to code/docs/API/CLI/test contract, data loss/corruption or integrity risk, security/privacy issue, auth/session bug, concurrency/idempotency/timeout bug, broken deploy/build/test/package/install path, API/schema/serialization/config mismatch, user-visible CLI/MCP contract failure, misleading operational docs/backlog truth, or dead/unreachable code that creates a real risk. Reject pure style/naming, speculative cleanup, broad refactors, and feature requests.

Graph rule:
This epic is the narrative/root index, not the executable remediation task. Labels are indexes only. Task-to-task dependencies and gate beads are authoritative for sequencing. Membership model is relation-based: accepted bug beads are related to this epic with `bd dep relate <epic-id> <bug-id>`. `bd children <epic-id>` may correctly return [] in this model.

Canonical navigation:
- Open bughunt findings: `bd list --label bughunt:exhaustive-20260519 --label bug --status open --flat --limit 0 --sort id`
- All related members/gates: `bd dep list <epic-id>` and `bd graph <epic-id>`
- All labelled containers/gates/findings: `bd list --label bughunt:exhaustive-20260519 --status open,in_progress,closed --flat --limit 0 --sort id`
Counting rule: distinguish bug findings from this narrative epic and synthesis/final-verification gates even when labels overlap.

Artifacts:
- Run directory: docs/audits/bughunt-20260519T030623Z/
- Manifest: docs/audits/bughunt-20260519T030623Z/manifest.json
- Coverage ledger: docs/audits/bughunt-20260519T030623Z/coverage_ledger.json
- Domain map: docs/audits/bughunt-20260519T030623Z/domain_map.md
- Candidate matrix, advisor packet, mutation audit, and final verification packet will be persisted in the same run directory before finalization.

Rule for adding bug beads:
Every accepted bug bead must have labels `bug,bughunt,bughunt:exhaustive-20260519,domain:<domain>`, concrete evidence, duplicate rationale, acceptance criteria, validation command or explicit validation gap, and provenance to a candidate matrix row. New findings must be related to this epic.

Synthesis/dedupe rule:
All delegated findings must be normalized into a central candidate matrix before Beads writes. Dedupe by failure mode, root cause, affected behavior, and fix surface, not title similarity. Advisor or independent substitute review gates materialization.

Final verification and close rule:
Keep this epic open while related bug findings remain open. Close only after final verification confirms candidate disposition, relation/label readbacks, duplicate disposition, dependency-cycle check, lint/orphan status, and artifact disposition.

Truthfulness:
This is an exhaustive coverage-enumerated bughunt over the stated tracked-file manifest, not proof that all bugs have been found.
