Context:
Materialized from repo-simplification-review row SIMP-016A (SIM-SEC-001) under epic trade-trace-mea1. Domain: security. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Centralize credential and secret-key vocabulary for MCP and credential audits. Complexity class: duplicate-logic.

Evidence:
- mcp_server.py defines SECRET_TRANSPORT_HINT_KEYS.
- tests/security/test_mcp_stdio_boundary.py defines PROJECT_CREDENTIAL_KEYS with overlapping names and checks coverage.
- tests/security/test_no_credentials.py defines CREDENTIAL_KEYS for schema/tool/persistence audits.

Why simplification is safe/desirable:
The target removes duplicated mechanics or contract-drift surface while preserving existing behavior. It is bounded to the cited files/surfaces and requires compatibility validation before close.

Target simplification:
Move common credential-key vocabulary to a security constants module; allow boundary-specific sets to extend it with explicit extras.

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
- python -m pytest tests/security/test_mcp_stdio_boundary.py tests/security/test_no_credentials.py tests/security/test_mvp_boundary_audit.py
- Verify MCP stdio boundary and no-credential audits preserve existing coverage.

Acceptance criteria:

- Simplification is limited to the cited bounded surface.
- Existing behavior and public contracts are preserved.
- Listed validation passes or any gap is explicitly resolved before close.
- No unrelated behavior change or broad rewrite lands under this bead.

Provenance:
Discovered by repo-simplification-review candidate SIMP-016A from source candidate(s) SIM-SEC-001. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
