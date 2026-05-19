Context:
Exhaustive no-tech-debt backlog materialization for /home/hermes/code/trade-trace.

Repo / commit:
- Initial preflight commit: a33e676ec9d22d6ec268686424521a3d2586f9dd
- Final target commit: e56c1883f3d8701c719e7c89a6e42ff004168328 (a concurrent/local mypy-fix commit landed during the review; final verification is scoped to this commit)
- Branch/status before materialization: see audits/no-tech-debt-20260518/verification/preflight-current.txt

Scope:
- All tracked files from git ls-files were classified in audits/no-tech-debt-20260518/coverage-ledger.jsonl.
- Source, tests, docs-contract files, config, CI, packaging, storage/migrations, CLI/MCP contracts, reports/exporter, security, and Beads metadata were assigned to read-only lanes.
- Runtime/generated/cache artifacts were excluded unless tracked.

Debt definition:
Accepted rows require concrete evidence, carrying cost/risk, bounded paydown action, non-goals/boundaries, validation path or explicit gap, duplicate disposition, and remediation track.
This backlog does not prove the repo is debt-free; it records covered surfaces and materialized debt found in this run.

Routing:
- maintenance: bounded debt paydown task.
- bug: concrete failure mode; bug rows are also related to existing bughunt epic trade-trace-2d3 for sibling visibility.
- design/investigation: schema/security/deploy/API/migration/public-surface uncertainty must resolve blast radius before implementation.
- deadcode/simplification findings were not materialized here unless proof/routing justified it.

Evidence:
- Live Beads/materialization/readback evidence is persisted under audits/no-tech-debt-20260518/verification/ and mutation-audit-postwrite.json.
- Coverage and candidate evidence are in coverage-ledger.jsonl, lane-reports/lane-*.md, and central-debt-matrix.json.

Artifacts:
- coverage ledger: audits/no-tech-debt-20260518/coverage-ledger.jsonl
- coverage summary: audits/no-tech-debt-20260518/coverage-summary.json
- domain map: audits/no-tech-debt-20260518/domain-map.json
- lane reports: audits/no-tech-debt-20260518/lane-reports/lane-*.md
- central matrix: audits/no-tech-debt-20260518/central-debt-matrix.json
- mutation map: audits/no-tech-debt-20260518/mutation-map-prewrite.json
- advisor packet: audits/no-tech-debt-20260518/advisor-gate-packet.md

Graph rule:
This epic is a narrative/root index. Relation links and labels are for navigation. The final verification gate blocks on every materialized accepted row; relation membership alone is not closeout proof.

Canonical navigation:
- bd list --label repo-no-tech-debt --label debt-run:20260518-no-tech-debt --status open --flat --limit 0 --sort id
- bd dep list <this-epic-id>
- bd graph <this-epic-id>
- bd dep list <final-gate-id>

Rule for adding new rows:
Add only with evidence + carrying cost + bounded paydown + validation/gap + duplicate check + relation to this epic. Use blocking dependencies only for real sequencing or final verification.
