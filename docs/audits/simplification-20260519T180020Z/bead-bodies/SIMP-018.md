Context:
Materialized from repo-simplification-review row SIMP-018 (SIM-SEC-003) under epic trade-trace-mea1. Domain: security-tests. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Consolidate duplicated no-network pytest fixtures with explicit coverage variants. Complexity class: test-drag.

Evidence:
- tests/security/test_embeddings_off_by_default.py defines no_network by replacing socket.socket with a raising stub.
- tests/security/test_no_network_default.py defines another no_network fixture patching socket.socket.connect and socket.getaddrinfo.

Why simplification is safe/desirable:
The target removes duplicated mechanics or contract-drift surface while preserving existing behavior. It is bounded to the cited files/surfaces and requires compatibility validation before close.

Target simplification:
Move shared no-network fixtures into tests/security/conftest.py or tests/conftest.py as explicit variants such as no_socket_creation and no_outbound_connect_or_dns.

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
- python -m pytest tests/security/test_embeddings_off_by_default.py tests/security/test_no_network_default.py tests/security/test_no_telemetry_packages.py
- Verify tests still fail on attempted socket creation, connect, and DNS as intended.

Acceptance criteria:

- Simplification is limited to the cited bounded surface.
- Existing behavior and public contracts are preserved.
- Listed validation passes or any gap is explicitly resolved before close.
- No unrelated behavior change or broad rewrite lands under this bead.

Provenance:
Discovered by repo-simplification-review candidate SIMP-018 from source candidate(s) SIM-SEC-003. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
