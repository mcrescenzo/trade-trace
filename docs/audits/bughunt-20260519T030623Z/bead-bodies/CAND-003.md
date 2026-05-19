Context:
storage-events-domain-security / src/trade_trace/exporter.py, tests/security/test_redacted_exports.py, .github/workflows/workflow.yml

Observed behavior:
Full pytest collection aborts with ImportError.

Expected behavior:
Compatibility alias exists or tests/docs use canonical registry; collection succeeds.

Evidence:
primary_evidence.txt: pytest collect-only reports ImportError cannot import SECRET_PATTERNS; exporter.py comments promise alias; test imports it.

Failure mode / impact:
CI/release validation cannot collect suite; public import compatibility broken.

## Steps to Reproduce
PYTHONPATH=src python3 -m pytest --collect-only -q -p no:cacheprovider

Duplicate check:
Compared against existing open Beads and the exhaustive bughunt candidate matrix after `bd find-duplicates` preflight. Not a duplicate because this candidate has a distinct root cause/failure mode/fix surface. Possible overlap: none.

Suggested fix direction:
Implement the smallest fix that makes observed behavior match the stated contract. For static-only candidates, first add a failure-injection or targeted regression test proving the risk.

Validation:
PYTHONPATH=src python3 -m pytest --collect-only -q -p no:cacheprovider

Acceptance criteria:
- Concrete failure no longer occurs
- Regression test or equivalent validation covers the case
- Related contract/docs/tests remain consistent

Provenance:
Discovered by repo-bughunt candidate CAND-003 in domain storage-events-domain-security.
Advisor gate: accepted after advisor critique; static-only candidates scoped with validation gap where applicable.
Disposition reason: Evidence spot-checked by coordinator; concrete failure mode; not a duplicate after root-cause/fix-surface comparison..
