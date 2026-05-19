Goal:
Exhaustive refresh bughunt for Trade Trace at repo `/home/hermes/code/trade-trace` on `main`, run `20260519T175941Z`.

Scope:
- Current tracked product source, tests, docs-contract, config/packaging/workflow files.
- Prior audit artifacts were assigned to historical-audit-artifacts and grouped for duplicate/context only.

Bug definition:
Concrete failure modes only: incorrect behavior vs code/docs/API/CLI/test contract, data/security/integrity risk, broken test/build/package path, API/schema/config mismatch, user-visible report/memory/CLI behavior, or misleading operational docs.

Non-goals:
- No implementation fixes in this bughunt.
- No speculative cleanup-only issues.
- No claim that all possible bugs were found.

Graph rule:
This epic is a narrative/root index, not executable remediation work. Membership is relation-based: use `bd dep list <this-epic-id>` and label query. `bd children <this-epic-id>` may be empty by design. Labels are an index only; task dependencies/gates are authoritative if later remediation is planned.

Canonical queries:
- Open findings/gates: `bd list --status open --flat --limit 0 --sort id | grep 'bughunt:exhaustive-refresh-20260519'`
- Relation navigation: `bd dep list <epic-id>` and `bd graph <epic-id>`
- Counts must distinguish bug findings from this epic and final-verification gate.

Run artifacts:
- Manifest: `docs/audits/bughunt-20260519T175941Z/manifest.json`
- Coverage ledger: `docs/audits/bughunt-20260519T175941Z/coverage_ledger.jsonl`
- Coverage summary: `docs/audits/bughunt-20260519T175941Z/coverage_summary.json`
- Lane packets: `docs/audits/bughunt-20260519T175941Z/lane-packets/`
- Candidate matrix: `docs/audits/bughunt-20260519T175941Z/candidate_matrix.json`
- Primary evidence: `docs/audits/bughunt-20260519T175941Z/primary_evidence.txt`
- Mutation audit: `docs/audits/bughunt-20260519T175941Z/mutation_audit.md`

Rule for adding more findings:
Add labels `bug,bughunt,bughunt:exhaustive-refresh-20260519,domain:<domain>`, include evidence + duplicate check + acceptance criteria + validation command, and relate the bug to this epic. Do not parent children unless readiness semantics are reverified.

Finalization:
This epic remains open while related bug findings remain open. The final verification gate records materialization/readback truth for this bughunt run.
