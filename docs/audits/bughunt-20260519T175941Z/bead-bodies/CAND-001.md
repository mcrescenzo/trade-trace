Context:
cli-mcp-contracts-tools — src/trade_trace/cli.py, src/trade_trace/core.py, docs/architecture/contracts.md, tests/golden/test_journal_status_parity.py

Observed behavior:
Invalid CLI invocation prints raw stderr and no JSON.

Expected behavior:
Invalid CLI invocation returns stable ErrorEnvelope JSON and non-zero exit.

Evidence:
primary_evidence.txt unknown_cli_command_envelope: rc=1, stdout empty, stderr raw unknown-command text; cli.py _invocation_from_args raises SystemExit before dispatch.

Failure mode / impact:
Agent callers cannot parse errors for typo/unregistered commands, breaking CLI/MCP parity.

## Steps to Reproduce
TRADE_TRACE_HOME=$(mktemp -d) python3 -m trade_trace.cli nonexistent tool

Duplicate check:
Compared against existing open and closed bughunt items in preflight_prior_bughunt_readback.txt. Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback. Possible overlap: none.

Suggested fix direction:
Repair the cited contract/runtime path with the smallest behavior-preserving change; add the listed regression proof.

Validation:
TRADE_TRACE_HOME=$(mktemp -d) python3 -m trade_trace.cli nonexistent tool

Acceptance criteria:
- Unknown CLI invocations return parseable ErrorEnvelope JSON on stdout
- Exit code remains non-zero
- Contract/golden test asserts JSON envelope, not only SystemExit/non-zero

Provenance:
Discovered by repo-bughunt candidate CAND-001 in domain cli-mcp-contracts-tools.