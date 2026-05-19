Context:
reports-memory-playbook-strategy / src/trade_trace/reports/calibration.py, src/trade_trace/reports/tag_aggregates.py, src/trade_trace/reports/watchlist.py, src/trade_trace/reports/unscored.py, src/trade_trace/reports/playbook_adherence.py, src/trade_trace/contracts/report_filter.py

Observed behavior:
Reports accept/echo filters but compute over global or over-broad rows.

Expected behavior:
Apply supported filters or reject unsupported filter fields; never echo ignored filters as applied.

Evidence:
primary_evidence.txt: calibration.py validates ReportFilter then calls _load_scored_rows(conn) globally; delegate found same pattern in tag_aggregates/watchlist/unscored/playbook_adherence.

Failure mode / impact:
Agents can make strategy/time/instrument decisions from falsely scoped reports.

## Steps to Reproduce
Seed mixed data and run report.calibration/report.playbook_adherence with filters; metrics/record_ids must exclude non-matching rows.

Duplicate check:
Compared against existing open Beads and the exhaustive bughunt candidate matrix after `bd find-duplicates` preflight. Not a duplicate because this candidate has a distinct root cause/failure mode/fix surface. Possible overlap: none.

Suggested fix direction:
Implement the smallest fix that makes observed behavior match the stated contract. For static-only candidates, first add a failure-injection or targeted regression test proving the risk.

Validation:
Seed mixed data and run report.calibration/report.playbook_adherence with filters; metrics/record_ids must exclude non-matching rows.

Acceptance criteria:
- Concrete failure no longer occurs
- Regression test or equivalent validation covers the case
- Related contract/docs/tests remain consistent

Provenance:
Discovered by repo-bughunt candidate CAND-006 in domain reports-memory-playbook-strategy.
Advisor gate: accepted after advisor critique; static-only candidates scoped with validation gap where applicable.
Disposition reason: Evidence spot-checked by coordinator; concrete failure mode; not a duplicate after root-cause/fix-surface comparison..
