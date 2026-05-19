Context:
cli-mcp-contracts-tools / src/trade_trace/cli.py, src/trade_trace/tools/admin.py, tests/integration/test_admin_tools.py

Observed behavior:
journal.config_set writes persistent config without --confirm and no preview metadata.

Expected behavior:
Without --confirm, preview only; with --confirm, persist.

Evidence:
primary_evidence.txt: config_set without confirm wrote config row [(x,y)]; CLI help/admin docs say config_set requires --confirm and otherwise preview_only.

Failure mode / impact:
Operational safety contract is false for config changes.

## Steps to Reproduce
Temp-home journal init + journal config_set --key x --value y; query config table should have no row until --confirm.

Duplicate check:
Compared against existing open Beads and the exhaustive bughunt candidate matrix after `bd find-duplicates` preflight. Not a duplicate because this candidate has a distinct root cause/failure mode/fix surface. Possible overlap: none.

Suggested fix direction:
Implement the smallest fix that makes observed behavior match the stated contract. For static-only candidates, first add a failure-injection or targeted regression test proving the risk.

Validation:
Temp-home journal init + journal config_set --key x --value y; query config table should have no row until --confirm.

Acceptance criteria:
- Concrete failure no longer occurs
- Regression test or equivalent validation covers the case
- Related contract/docs/tests remain consistent

Provenance:
Discovered by repo-bughunt candidate CAND-002 in domain cli-mcp-contracts-tools.
Advisor gate: accepted after advisor critique; static-only candidates scoped with validation gap where applicable.
Disposition reason: Evidence spot-checked by coordinator; concrete failure mode; not a duplicate after root-cause/fix-surface comparison..
