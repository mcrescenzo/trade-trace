Context:
reports-memory-playbook-strategy / src/trade_trace/tools/memory.py

Observed behavior:
Failure after node commit can leave orphan reflection node.

Expected behavior:
Reflection node, about edge, and events are in one transaction.

Evidence:
primary_evidence.txt: memory.py docstring promises one transaction; code calls _memory_retain then opens a second UnitOfWork for edge.

Failure mode / impact:
Memory graph integrity can be violated under partial failure.

## Steps to Reproduce
Failure-injection test around memory.reflect edge insert; orphan invariant remains zero.

Duplicate check:
Compared against existing open Beads and the exhaustive bughunt candidate matrix after `bd find-duplicates` preflight. Not a duplicate because this candidate has a distinct root cause/failure mode/fix surface. Possible overlap: none.

Suggested fix direction:
Implement the smallest fix that makes observed behavior match the stated contract. For static-only candidates, first add a failure-injection or targeted regression test proving the risk.

Validation:
Failure-injection test around memory.reflect edge insert; orphan invariant remains zero.

Acceptance criteria:
- Concrete failure no longer occurs
- Regression test or equivalent validation covers the case
- Related contract/docs/tests remain consistent

Provenance:
Discovered by repo-bughunt candidate CAND-007 in domain reports-memory-playbook-strategy.
Advisor gate: accepted after advisor critique; static-only candidates scoped with validation gap where applicable.
Disposition reason: Accepted as static-only data-integrity bug: inspected code contradicts documented/logical atomic operation. Bead must explicitly say not dynamically reproduced and require failure-injection regression..
