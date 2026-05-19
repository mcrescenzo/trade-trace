Context:
cli-mcp-contracts-tools / src/trade_trace/cli.py, docs/architecture/contracts.md

Observed behavior:
Malformed --mode-json exits 1 with empty stdout and raw stderr.

Expected behavior:
Emit parseable ErrorEnvelope on stdout with VALIDATION_ERROR and exit code 2.

Evidence:
primary_evidence.txt: invalid --*-json probe rc=1, stdout empty, stderr raw SystemExit; cli.py raises SystemExit on json.JSONDecodeError.

Failure mode / impact:
Agent callers cannot parse standard error envelope for malformed JSON args.

## Steps to Reproduce
PYTHONPATH=src TRADE_TRACE_HOME=$(mktemp -d) python3 -m trade_trace.cli report filter_schema --mode-json "{bad"

Duplicate check:
Compared against existing open Beads and the exhaustive bughunt candidate matrix after `bd find-duplicates` preflight. Not a duplicate because this candidate has a distinct root cause/failure mode/fix surface. Possible overlap: none.

Suggested fix direction:
Implement the smallest fix that makes observed behavior match the stated contract. For static-only candidates, first add a failure-injection or targeted regression test proving the risk.

Validation:
PYTHONPATH=src TRADE_TRACE_HOME=$(mktemp -d) python3 -m trade_trace.cli report filter_schema --mode-json "{bad"

Acceptance criteria:
- Concrete failure no longer occurs
- Regression test or equivalent validation covers the case
- Related contract/docs/tests remain consistent

Provenance:
Discovered by repo-bughunt candidate CAND-001 in domain cli-mcp-contracts-tools.
Advisor gate: accepted after advisor critique; static-only candidates scoped with validation gap where applicable.
Disposition reason: Evidence spot-checked by coordinator; concrete failure mode; not a duplicate after root-cause/fix-surface comparison..
