Context:
Materialized from repo-simplification-review row SIMP-019 (SIM-SEC-004) under epic trade-trace-mea1. Domain: security-tests. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Extract light schema/table audit helpers for security tests without hiding assertions. Complexity class: test-drag.

Evidence:
- tests/security/test_mvp_boundary_audit.py and tests/security/test_no_credentials.py overlap in credential-shaped schema column scans.
- tests/security/test_report_sql_filters.py repeatedly opens DB and checks required tables after injection-shaped payloads.

Why simplification is safe/desirable:
The target removes duplicated mechanics or contract-drift surface while preserving existing behavior. It is bounded to the cited files/surfaces and requires compatibility validation before close.

Target simplification:
Add small test helpers for iterating tables/columns, asserting no credential-shaped columns, and asserting required tables exist while keeping product/security assertions separate.

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
- python -m pytest tests/security/test_mvp_boundary_audit.py tests/security/test_no_credentials.py tests/security/test_report_sql_filters.py
- Manual readback verifies helpers do not hide the specific security assertions.

Acceptance criteria:

- Simplification is limited to the cited bounded surface.
- Existing behavior and public contracts are preserved.
- Listed validation passes or any gap is explicitly resolved before close.
- No unrelated behavior change or broad rewrite lands under this bead.

Provenance:
Discovered by repo-simplification-review candidate SIMP-019 from source candidate(s) SIM-SEC-004. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
