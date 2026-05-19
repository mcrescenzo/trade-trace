Context:
storage-events-domain-security / src/trade_trace/tools/ledger.py

Observed behavior:
Second-phase failure can leave replacement forecast without supersedes edge.

Expected behavior:
Replacement forecast/outcomes, supersedes edge, and events commit atomically or roll back.

Evidence:
primary_evidence.txt: ledger.py lines 1389-1397 call _forecast_add then open a second UnitOfWork for edge/event.

Failure mode / impact:
Data-integrity risk in forecast lineage after crash/lock/disk failure.

## Steps to Reproduce
Add failure-injection test around forecast.supersede; run idempotency/transaction tests.

Duplicate check:
Compared against existing open Beads and the exhaustive bughunt candidate matrix after `bd find-duplicates` preflight. Not a duplicate because this candidate has a distinct root cause/failure mode/fix surface. Possible overlap: none.

Suggested fix direction:
Implement the smallest fix that makes observed behavior match the stated contract. For static-only candidates, first add a failure-injection or targeted regression test proving the risk.

Validation:
Add failure-injection test around forecast.supersede; run idempotency/transaction tests.

Acceptance criteria:
- Concrete failure no longer occurs
- Regression test or equivalent validation covers the case
- Related contract/docs/tests remain consistent

Provenance:
Discovered by repo-bughunt candidate CAND-005 in domain storage-events-domain-security.
Advisor gate: accepted after advisor critique; static-only candidates scoped with validation gap where applicable.
Disposition reason: Accepted as static-only data-integrity bug: inspected code contradicts documented/logical atomic operation. Bead must explicitly say not dynamically reproduced and require failure-injection regression..
