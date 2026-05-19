Context:
Materialized from repo-simplification-review row SIMP-009 (TESTS-SIMPLIFY-002/003) under epic trade-trace-mea1. Domain: tests. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Add explicit test data builders for direct-SQL and MCP ledger setup. Complexity class: test-drag.

Evidence:
- Multiple integration tests copy direct-SQL _db/_seed_minimal helpers for venues, instruments, theses, forecasts, decisions, outcomes, sources, edges, scores, and signals.
- Many tests repeat MCP graph setup venue.add -> instrument.add -> thesis.add -> forecast.add -> outcome.add/decision.add.

Why simplification is safe/desirable:
The target removes duplicated mechanics or contract-drift surface while preserving existing behavior. It is bounded to the cited files/surfaces and requires compatibility validation before close.

Target simplification:
Create explicit test seed builders for common direct-SQL and MCP ledger graphs while keeping direct SQL intentional where tests need storage-level control.

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
- python -m pytest tests/integration/test_append_only.py tests/integration/test_edges.py tests/integration/test_edge_endpoint_audit.py tests/integration/test_scoring_lifecycle.py tests/integration/test_scoring_p1.py tests/golden/test_cli_mcp_parity.py
- Verify generated IDs, event counts, and append-only behavior are unchanged.

Acceptance criteria:

- Simplification is limited to the cited bounded surface.
- Existing behavior and public contracts are preserved.
- Listed validation passes or any gap is explicitly resolved before close.
- No unrelated behavior change or broad rewrite lands under this bead.

Provenance:
Discovered by repo-simplification-review candidate SIMP-009 from source candidate(s) TESTS-SIMPLIFY-002/003. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
