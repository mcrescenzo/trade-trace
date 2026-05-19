Context:
tests-fixtures-crosscutting / src/trade_trace/version.py, pyproject.toml, tests/test_smoke.py, tests/golden/test_journal_status_parity.py

Observed behavior:
Smoke/golden tests fail against current package version.

Expected behavior:
Tests assert canonical current version or package version is intentionally changed.

Evidence:
primary_evidence.txt: targeted pytest failed two tests asserting 0.0.1; pyproject/version.py are 0.0.1rc0.

Failure mode / impact:
Test failures obscure real regressions and block clean CI after collection fix.

## Steps to Reproduce
PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider tests/test_smoke.py tests/golden/test_journal_status_parity.py

Duplicate check:
Compared against existing open Beads and the exhaustive bughunt candidate matrix after `bd find-duplicates` preflight. Not a duplicate because this candidate has a distinct root cause/failure mode/fix surface. Possible overlap: none.

Suggested fix direction:
Implement the smallest fix that makes observed behavior match the stated contract. For static-only candidates, first add a failure-injection or targeted regression test proving the risk.

Validation:
PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider tests/test_smoke.py tests/golden/test_journal_status_parity.py

Acceptance criteria:
- Concrete failure no longer occurs
- Regression test or equivalent validation covers the case
- Related contract/docs/tests remain consistent

Provenance:
Discovered by repo-bughunt candidate CAND-014 in domain tests-fixtures-crosscutting.
Advisor gate: accepted after advisor critique; static-only candidates scoped with validation gap where applicable.
Disposition reason: Evidence spot-checked by coordinator; concrete failure mode; not a duplicate after root-cause/fix-surface comparison..
