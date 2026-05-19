Context:
Materialized from repo-simplification-review row SIMP-008 (TESTS-SIMPLIFY-001) under epic trade-trace-mea1. Domain: tests. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Centralize repeated test home and MCP/CLI fixtures without reducing isolation. Complexity class: test-drag.

Evidence:
- tests/conftest.py currently only inserts src/ into sys.path.
- Initialized-home helpers and mcp_call wrappers are repeated across contracts, golden, and integration tests including test_agent_ergonomics.py, test_event_enum_coverage.py, test_report_envelope_completeness.py, test_cli_mcp_parity.py, test_admin_tools.py, and memory/playbook/report tests.

Why simplification is safe/desirable:
The target removes duplicated mechanics or contract-drift surface while preserving existing behavior. It is bounded to the cited files/surfaces and requires compatibility validation before close.

Target simplification:
Add shared test-support fixtures/helpers for initialized homes and MCP/CLI calls, with explicit per-test isolation and no security no-network fixture merging.

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
- python -m pytest tests/contracts tests/golden tests/integration/test_admin_tools.py tests/integration/test_memory_layer.py tests/integration/test_playbook_layer.py
- Run touched files first; verify each test still receives a fresh tmp home.

Acceptance criteria:

- Simplification is limited to the cited bounded surface.
- Existing behavior and public contracts are preserved.
- Listed validation passes or any gap is explicitly resolved before close.
- No unrelated behavior change or broad rewrite lands under this bead.

Provenance:
Discovered by repo-simplification-review candidate SIMP-008 from source candidate(s) TESTS-SIMPLIFY-001. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
