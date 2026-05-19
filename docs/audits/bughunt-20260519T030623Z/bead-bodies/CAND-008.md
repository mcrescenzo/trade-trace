Context:
reports-memory-playbook-strategy / src/trade_trace/tools/memory.py

Observed behavior:
Same logical retry conflicts because default valid_from differs.

Expected behavior:
Same idempotency key and same caller args replay the original result without conflict.

Evidence:
primary_evidence.txt: repeating memory.reflect with same idempotency_key returned IDEMPOTENCY_CONFLICT diff_keys=[valid_from]; _memory_retain defaults valid_from to created_at only on first write but replay recomputes None/current.

Failure mode / impact:
Retry safety is broken for memory.reflect/memory.retain calls that omit valid_from.

## Steps to Reproduce
Temp dispatch memory.reflect twice with same idempotency_key and no valid_from; second should ok/replay, not conflict.

Duplicate check:
Compared against existing open Beads and the exhaustive bughunt candidate matrix after `bd find-duplicates` preflight. Not a duplicate because this candidate has a distinct root cause/failure mode/fix surface. Possible overlap: none.

Suggested fix direction:
Implement the smallest fix that makes observed behavior match the stated contract. For static-only candidates, first add a failure-injection or targeted regression test proving the risk.

Validation:
Temp dispatch memory.reflect twice with same idempotency_key and no valid_from; second should ok/replay, not conflict.

Acceptance criteria:
- Concrete failure no longer occurs
- Regression test or equivalent validation covers the case
- Related contract/docs/tests remain consistent

Provenance:
Discovered by repo-bughunt candidate CAND-008 in domain reports-memory-playbook-strategy.
Advisor gate: accepted after advisor critique; static-only candidates scoped with validation gap where applicable.
Disposition reason: Evidence spot-checked by coordinator; concrete failure mode; not a duplicate after root-cause/fix-surface comparison..
