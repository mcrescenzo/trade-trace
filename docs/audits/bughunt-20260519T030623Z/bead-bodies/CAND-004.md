Context:
storage-events-domain-security / src/trade_trace/tools/ledger.py, src/trade_trace/tools/_helpers.py, src/trade_trace/events/semantic_keys.py

Observed behavior:
source.note/title/summary can persist secret-shaped strings.

Expected behavior:
All source free-text fields are scanned/rejected or explicitly handled by sensitive/redaction policy.

Evidence:
primary_evidence.txt: source.add note with sk-... returned ok=True; sources.note stored redacted-looking secret; event payload contains secret=True. ledger.py scans excerpt/extracted_text only.

Failure mode / impact:
Privacy/security boundary gap; raw secrets can enter journal/events/export path.

## Steps to Reproduce
Temp dispatch source.add with note="sk-"+24 chars; expected VALIDATION_ERROR.

Duplicate check:
Compared against existing open Beads and the exhaustive bughunt candidate matrix after `bd find-duplicates` preflight. Not a duplicate because this candidate has a distinct root cause/failure mode/fix surface. Possible overlap: none.

Suggested fix direction:
Implement the smallest fix that makes observed behavior match the stated contract. For static-only candidates, first add a failure-injection or targeted regression test proving the risk.

Validation:
Temp dispatch source.add with note="sk-"+24 chars; expected VALIDATION_ERROR.

Acceptance criteria:
- Concrete failure no longer occurs
- Regression test or equivalent validation covers the case
- Related contract/docs/tests remain consistent

Provenance:
Discovered by repo-bughunt candidate CAND-004 in domain storage-events-domain-security.
Advisor gate: accepted after advisor critique; static-only candidates scoped with validation gap where applicable.
Disposition reason: Evidence spot-checked by coordinator; concrete failure mode; not a duplicate after root-cause/fix-surface comparison..
