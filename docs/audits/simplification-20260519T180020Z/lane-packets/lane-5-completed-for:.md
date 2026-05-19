Read-only simplification review completed for:

- security-boundaries
- crosscutting-small-modules

Repository/workdir:
- /home/hermes/code/trade-trace

Commit verified:
- 6f62a5f7a83cec823302bbe80892172b1e6936cb

Mode:
- Read-only. I did not edit files, create artifacts, or update Beads.

Coverage accounting:
- crosscutting-small-modules: reviewed 6/6 assigned files
  - LICENSE
  - src/trade_trace/__init__.py
  - src/trade_trace/clock.py
  - src/trade_trace/contracts/__init__.py
  - src/trade_trace/timestamps.py
  - src/trade_trace/version.py

- security-boundaries: reviewed 14/14 assigned files
  - src/trade_trace/security/__init__.py
  - src/trade_trace/security/patterns.py
  - tests/security/__init__.py
  - tests/security/test_embeddings_api_keyring.py
  - tests/security/test_embeddings_off_by_default.py
  - tests/security/test_file_permissions.py
  - tests/security/test_mcp_stdio_boundary.py
  - tests/security/test_mvp_boundary_audit.py
  - tests/security/test_no_credentials.py
  - tests/security/test_no_network_default.py
  - tests/security/test_no_telemetry_packages.py
  - tests/security/test_redacted_exports.py
  - tests/security/test_report_sql_filters.py
  - tests/security/test_secret_pattern_writes.py

Additional adjacent read-only spot checks:
- src/trade_trace/exporter.py secret-scanning adapter around scan_for_secrets / SECRET_PATTERNS alias
- src/trade_trace/mcp_server.py SECRET_TRANSPORT_HINT_KEYS and MCP schema guard
- search across src/trade_trace for timestamp/security/no-network related uses

Git status note:
- Working tree already had pre-existing changes/untracked audit artifacts:
  - M tests/contracts/test_grammar.py
  - ?? audits/no-tech-debt-20260519T180002Z/
  - ?? docs/audits/bughunt-20260519T175941Z/
  - ?? docs/audits/simplification-20260519T180020Z/
- I did not modify them.

Candidate records:

Candidate: SIM-SEC-001
Domain: security-boundaries
Title: Centralize duplicated credential/secret-key vocabulary used by MCP and credential audits
Files:
- src/trade_trace/mcp_server.py
- tests/security/test_mcp_stdio_boundary.py
- tests/security/test_no_credentials.py
Evidence:
- mcp_server.py defines SECRET_TRANSPORT_HINT_KEYS with credential-like field names.
- test_mcp_stdio_boundary.py defines PROJECT_CREDENTIAL_KEYS with a highly overlapping set and asserts it is covered by SECRET_TRANSPORT_HINT_KEYS.
- test_no_credentials.py defines CREDENTIAL_KEYS with another overlapping vocabulary for schema/tool/persistence audits.
Simplification:
- Move the common credential-key vocabulary to one dedicated security constants module, e.g. trade_trace.security.vocabulary or trade_trace.security.patterns if acceptable.
- Let MCP-specific and test-specific sets extend that canonical base with boundary-specific extras such as "transport_hint", "credential", "credentials", and generic "token"/"secret".
Why it is safe:
- This is a consolidation of deny-list constants, not a weakening of checks.
- It reduces drift risk where one boundary audit adds a new credential term but the MCP exposure guard or no-credential persistence audit misses it.
Risk:
- Medium. Credential vocabulary is security-sensitive; implementation must preserve exact current superset behavior and keep tests proving MCP coverage.
Disposition:
- Recommended simplification, but security-reviewed. Preserve fail-closed behavior.

Candidate: SIM-SEC-002
Domain: security-boundaries
Title: Replace exporter secret-scanning compatibility wrapper with a clearer public adapter or direct security API
Files:
- src/trade_trace/security/patterns.py
- src/trade_trace/security/__init__.py
- src/trade_trace/exporter.py
- tests/security/test_redacted_exports.py
Evidence:
- security.patterns exposes scan_text returning SecretMatch records.
- exporter.py re-exports a private alias:
  - from trade_trace.security.patterns import _compiled as SECRET_PATTERNS
- exporter.py also defines scan_for_secrets(text) that converts SecretMatch fields into dicts with keys pattern/match/match_offset/match_length.
- tests/security/test_redacted_exports.py imports SECRET_PATTERNS and scan_for_secrets from exporter, even though the canonical registry now lives under trade_trace.security.
Simplification:
- Add a public helper in trade_trace.security, for example scan_text_dicts() or scan_for_secrets(), and have exporter use/import that.
- Replace the private _compiled alias with a public list_patterns()/BUILTIN_PATTERNS-based compatibility surface, or update tests to assert against security.list_patterns().
- Keep exporter focused on export/drain behavior, not registry compatibility.
Why it is safe:
- The current wrapper is mostly shape conversion and backward compatibility.
- Consolidating on the security package would reduce private-state coupling and keep write-time scanning, export-time warning, and log redaction under one public API.
Risk:
- Medium. Export behavior intentionally differs from write-time behavior: export warns but does not block. Do not change that product/security contract.
Disposition:
- Recommended simplification if compatibility expectations are understood. Otherwise track as investigation/design.

Candidate: SIM-SEC-003
Domain: security-boundaries
Title: Consolidate duplicated no-network pytest fixtures/helpers
Files:
- tests/security/test_embeddings_off_by_default.py
- tests/security/test_no_network_default.py
Evidence:
- test_embeddings_off_by_default.py defines a no_network fixture that replaces socket.socket entirely with a raising stub.
- test_no_network_default.py defines another no_network fixture that patches socket.socket.connect and socket.getaddrinfo.
- Both protect the same default air-gap/no-outbound-network guarantee, with slightly different scopes.
Simplification:
- Move shared network-blocking fixtures into tests/security/conftest.py or tests/conftest.py with explicit variants, e.g.:
  - no_socket_creation
  - no_outbound_connect_or_dns
- Use named variants where the distinction matters.
Why it is safe:
- This is a test-harness simplification only.
- It can make the boundary clearer by naming the exact blocked network surface instead of duplicating local fixture logic.
Risk:
- Low/Medium. The two fixtures are not identical. A careless merge could reduce coverage. Preserve both scopes if both are intentional.
Disposition:
- Recommended small test simplification.

Candidate: SIM-SEC-004
Domain: security-boundaries
Title: Extract common schema/table audit helpers for credential-column and SQL-injection tests
Files:
- tests/security/test_mvp_boundary_audit.py
- tests/security/test_no_credentials.py
- tests/security/test_report_sql_filters.py
Evidence:
- test_mvp_boundary_audit.py has its own schema column scan for credential-shaped column names.
- test_no_credentials.py has a broader no-credential schema/tool/persistence audit with overlapping credential column logic.
- test_report_sql_filters.py repeatedly opens the DB and checks core tables still exist after injection-shaped filter payloads.
Simplification:
- Add small local test helpers for:
  - iterating non-sqlite tables/columns
  - asserting no credential-shaped schema columns
  - asserting required tables still exist
- Keep the boundary tests themselves separate, but share the mechanical database introspection.
Why it is safe:
- The product/security assertions remain separate and readable.
- Reduces copy-paste SQL introspection while preserving independent QC gates.
Risk:
- Low/Medium. Duplicate security tests can be intentional defense-in-depth. Avoid over-abstracting assertions into opaque helpers.
Disposition:
- Recommended only as a light helper extraction, not a broad test-framework rewrite.

Candidate: SIM-XCUT-001
Domain: crosscutting-small-modules
Title: Treat src/trade_trace/contracts/__init__.py as a deliberate public facade, not dead pass-through
Files:
- src/trade_trace/contracts/__init__.py
Evidence:
- The file is a pure re-export facade for envelope, errors, grammar, and tool_registry symbols.
- It is a pass-through module, which was in the lane’s complexity lens.
Simplification:
- Possible simplification would be removing or shrinking the facade and requiring direct imports from submodules.
Why this is not recommended now:
- This is likely intentional public API ergonomics for a contracts package.
- Removing it may create import churn without meaningful complexity reduction.
Risk:
- Medium for downstream/API compatibility, low code reduction.
Disposition:
- No action recommended. Counted as reviewed intentional pass-through.

Candidate: SIM-XCUT-002
Domain: crosscutting-small-modules
Title: Keep src/trade_trace/security/__init__.py as a deliberate public security facade
Files:
- src/trade_trace/security/__init__.py
Evidence:
- The file only re-exports security.patterns symbols.
- It is a pass-through module.
Simplification:
- Possible simplification would be importing directly from trade_trace.security.patterns.
Why this is not recommended now:
- The facade gives callers a stable public security API and hides implementation layout.
- Given security.patterns has private registry state, the facade helps steer users to supported symbols.
Risk:
- Low code savings, medium API churn.
Disposition:
- No action recommended.

Candidate: SIM-XCUT-003
Domain: crosscutting-small-modules
Title: Investigate deriving TIMESTAMP_API_GOVERNED_COLUMNS from schema/migrations instead of maintaining a large static set
Files:
- src/trade_trace/timestamps.py
Evidence:
- TIMESTAMP_API_GOVERNED_COLUMNS is a large hardcoded frozenset of table/column pairs.
- Comments state schema audit tests fail if a new timestamp-shaped TEXT column appears without being added.
Simplification:
- Potentially derive governed timestamp columns from migration/schema metadata or a migration-owned registry to avoid duplicated schema knowledge.
Why this is only investigation/design:
- The static set is an explicit safety boundary because SQLite constraints are intentionally not retrofitted broadly.
- Automatic derivation could weaken the “explicitly governed” property if it silently blesses new timestamp columns.
Risk:
- Medium/High. Timestamp normalization is a data integrity/security-adjacent boundary. Do not auto-derive unless the audit semantics are preserved.
Disposition:
- Investigation/design only; no immediate simplification recommended.

Non-candidates / intentional complexity:
- src/trade_trace/security/patterns.py:
  - The process-global pattern registry, reset_patterns(), ReDoS guards, scan cap, and redaction loop are intentional security complexity.
  - I would not simplify register()/scan_text()/redact_for_log without targeted performance/security tests.
- tests/security/test_file_permissions.py:
  - The detailed POSIX permission coverage is intentionally broad and security-boundary preserving.
  - No simplification recommended beyond possible local helper cleanup already present.
- tests/security/test_secret_pattern_writes.py:
  - The large pattern x field matrix is intentionally exhaustive after prior audit findings.
  - Do not collapse parametrization in a way that hides exact field coverage.
- tests/security/test_no_network_default.py:
  - The representative registry smoke table is verbose but valuable because the no-network guarantee is product-critical.
  - Only fixture/helper consolidation is recommended, not reducing coverage.
- src/trade_trace/clock.py:
  - Small and already simplified; comments document removal of a previous global default clock.
  - No candidate.
- src/trade_trace/version.py and src/trade_trace/__init__.py:
  - Minimal metadata/public API surface.
  - No candidate.
- LICENSE:
  - No simplification candidate.

Files created or modified:
- None.

Issues encountered:
- None blocking.
- The repository had pre-existing modified/untracked files as noted above, but this lane was read-only and did not alter them.