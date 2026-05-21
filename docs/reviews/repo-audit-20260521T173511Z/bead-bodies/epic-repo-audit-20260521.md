## Purpose
Consolidated repo-audit backlog for `repo-audit-20260521T173511Z` at scope fingerprint `1901b8097953e720` and commit `a1023ea4f2d498e916acbcbe25eecc0570d873bf`.

This epic indexes the materialized findings from the comprehensive read-only audit across bughunt, deadcode, technical-debt, simplification, docs-contract, tests, console, storage/security, CLI/MCP, reports/memory, and build/package lanes.

## Audit artifacts
- Plan: `docs/reviews/repo-audit-20260521T173511Z/audit-plan.md`
- Coverage ledger: `docs/reviews/repo-audit-20260521T173511Z/manifest-coverage-ledger.yaml`
- Candidate matrix: `docs/reviews/repo-audit-20260521T173511Z/candidate-matrix.json`
- Lane reports: `docs/reviews/repo-audit-20260521T173511Z/lane-*.md`
- Existing audit-family inventory: `docs/reviews/repo-audit-20260521T173511Z/existing-audit-family-inventory.json`

## Matrix summary after advisor gates
- Raw candidates: 11
- Accepted/materialized findings: 5
- Deferred/report-only: 2
- Rejected/covered/resolved: 4

## Membership model
Relation-based: this epic `relates-to` each finding bead and the closeout gate. The candidate-to-Bead crosswalk is persisted in `docs/reviews/repo-audit-20260521T173511Z/materialization-crosswalk.json`.

## Audit caveat
Exhaustive coverage accounting means every tracked in-scope surface has an assigned coverage treatment. It does not prove all possible defects were found.
## Success Criteria
- The five materialized finding beads are related to this epic and retain audit-run/domain/track labels.
- The closeout gate remains blocked by all finding beads until implementation evidence is recorded.
- Candidate matrix and crosswalk stay reconciled with live Bead IDs.
- Deferred/rejected rows remain report-only unless explicitly promoted by a later decision.
