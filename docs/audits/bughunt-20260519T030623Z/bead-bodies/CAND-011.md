Context:
docs-packaging-ci-ops / README.md, docs/PRD.md, docs/architecture/contracts.md, docs/architecture/*.md

Observed behavior:
Core local docs links resolve to missing files.

Expected behavior:
Local links resolve to tracked files or are intentionally excluded.

Evidence:
primary_evidence.txt: README links ./PRD.md and ./VISION.md but files are docs/PRD.md and docs/VISION.md; docs/PRD.md links ./docs/architecture; architecture docs link ../../PRD.md.

Failure mode / impact:
README/PyPI/docs navigation fails for core design/ops docs.

## Steps to Reproduce
Run local markdown link checker over README.md docs/**/*.md; expected zero missing live local links.

Duplicate check:
Compared against existing open Beads and the exhaustive bughunt candidate matrix after `bd find-duplicates` preflight. Not a duplicate because this candidate has a distinct root cause/failure mode/fix surface. Possible overlap: none.

Suggested fix direction:
Implement the smallest fix that makes observed behavior match the stated contract. For static-only candidates, first add a failure-injection or targeted regression test proving the risk.

Validation:
Run local markdown link checker over README.md docs/**/*.md; expected zero missing live local links.

Acceptance criteria:
- Concrete failure no longer occurs
- Regression test or equivalent validation covers the case
- Related contract/docs/tests remain consistent

Provenance:
Discovered by repo-bughunt candidate CAND-011 in domain docs-packaging-ci-ops.
Advisor gate: accepted after advisor critique; static-only candidates scoped with validation gap where applicable.
Disposition reason: Evidence spot-checked by coordinator; concrete failure mode; not a duplicate after root-cause/fix-surface comparison..
