Context:
Materialized from repo-simplification-review row SIMP-001 (SIM-CLI-MCP-001 + SIM-CLI-MCP-002) under epic trade-trace-mea1. Domain: cli-mcp. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Centralize CLI and dispatcher error-envelope construction. Complexity class: duplicate-logic.

Evidence:
- src/trade_trace/cli.py lines 194-268 hand-builds ErrorEnvelope blocks for startup/name/argument errors.
- src/trade_trace/core.py dispatch() lines 101-255 mixes handler invocation with repeated ToolError, IdempotencyConflictError, sqlite3, and invariant-to-envelope mappings.
- Both surfaces import/use ErrorEnvelope/ErrorBody/Meta/dump_envelope and must preserve exact JSON envelopes and exit/status behavior.

Why simplification is safe/desirable:
The target removes duplicated mechanics or contract-drift surface while preserving existing behavior. It is bounded to the cited files/surfaces and requires compatibility validation before close.

Target simplification:
Extract small helpers for constructing CLI/dispatch error envelopes and applying hints; leave dispatch routing and handler contracts unchanged.

Non-goals:
- Do not change CLI/MCP contracts, storage semantics, report schemas, security posture, or agent-facing workflow policy.
- Do not perform broad rewrites or introduce generic frameworks beyond the bounded helper/decision described here.
- Do not absorb deferred/rejected matrix rows into this work without a new explicit decision.

Behavior preservation:
- Preserve current observable behavior for all cited public/tool/test surfaces.
- For investigation rows, preserve behavior by not refactoring until the findings record defines exact current behavior and validation evidence.

Risks / intentional complexity check:
Some duplication is intentional for compatibility, auditability, release safety, or security boundaries. Keep intentional explicitness where the validation plan cannot prove an equivalent simpler shape.

Validation:
- python -m pytest tests/contracts/test_envelope.py tests/contracts/test_agent_ergonomics.py tests/golden/test_cli_mcp_parity.py tests/integration/test_mcp_stdio_server.py
- Capture before/after invalid JSON, stray positional args, ToolError, idempotency conflict, sqlite IntegrityError, and non-dict handler result envelopes and verify field/status equivalence.

Acceptance criteria:

- Simplification is limited to the cited bounded surface.
- Existing behavior and public contracts are preserved.
- Listed validation passes or any gap is explicitly resolved before close.
- No unrelated behavior change or broad rewrite lands under this bead.

Provenance:
Discovered by repo-simplification-review candidate SIMP-001 from source candidate(s) SIM-CLI-MCP-001 + SIM-CLI-MCP-002. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
