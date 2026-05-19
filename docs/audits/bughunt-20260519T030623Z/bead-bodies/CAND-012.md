Context:
docs-packaging-ci-ops / README.md, docs/PRD.md, docs/architecture/memory-layer.md, pyproject.toml, src/trade_trace/core.py

Observed behavior:
Users following docs run unknown command.

Expected behavior:
Docs use implemented command or implementation adds tested alias.

Evidence:
primary_evidence.txt: CLI catalog has journal config_set and no config set; docs use `tt config set embeddings.provider ...`.; CAND-013 merged: memory-layer quickstart says tt init && tt mcp, CLI catalog has neither and pyproject scripts expose only tt/trade-trace.

Failure mode / impact:
Embeddings/offline opt-in/out instructions fail.

## Steps to Reproduce
CLI catalog inspection plus grep for `tt config set`; documented command succeeds or docs corrected.

Duplicate check:
Compared against existing open Beads and the exhaustive bughunt candidate matrix after `bd find-duplicates` preflight. Not a duplicate because this candidate has a distinct root cause/failure mode/fix surface. Possible overlap: none.

Suggested fix direction:
Implement the smallest fix that makes observed behavior match the stated contract. For static-only candidates, first add a failure-injection or targeted regression test proving the risk.

Validation:
CLI catalog inspection plus grep for `tt config set`; documented command succeeds or docs corrected.

Acceptance criteria:
- Concrete failure no longer occurs
- Regression test or equivalent validation covers the case
- Related contract/docs/tests remain consistent
- Docs no longer advertise tt init or tt mcp unless those commands are implemented/tested.

Provenance:
Discovered by repo-bughunt candidate CAND-012 in domain docs-packaging-ci-ops.
Advisor gate: accepted after advisor critique; static-only candidates scoped with validation gap where applicable.
Disposition reason: Evidence spot-checked by coordinator; concrete failure mode; not a duplicate after root-cause/fix-surface comparison..
