Context:
Materialized from repo-simplification-review row SIMP-016B (SIM-SEC-002) under epic trade-trace-mea1. Domain: security. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Investigate replacing exporter secret-scanning private alias with a public security adapter. Complexity class: over-abstraction.

Evidence:
- security.patterns exposes scan_text returning SecretMatch records.
- exporter.py imports private _compiled as SECRET_PATTERNS and defines scan_for_secrets dict conversion; tests/security/test_redacted_exports.py imports SECRET_PATTERNS and scan_for_secrets from exporter.

Why this is investigation/design-first:
The candidate touches behavior-sensitive or high-risk surfaces. The first deliverable is characterization/findings and a safe downstream plan, not refactor implementation.

Target simplification:
Investigation/design only until a golden scan corpus exists: decide whether to add a public security adapter and migrate exporter/tests without changing redaction behavior.

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
- python -m pytest tests/security/test_redacted_exports.py tests/security/test_secret_pattern_writes.py
- Close with golden scan corpus requirements and adapter API decision.

Acceptance criteria:

- Findings/decision record documents exact current behavior, risks, and whether downstream implementation should be created.
- No implementation refactor is performed unless behavior characterization and validation commands are explicit.
- Any proposed follow-up tasks reference this bead and include concrete validation.

Provenance:
Discovered by repo-simplification-review candidate SIMP-016B from source candidate(s) SIM-SEC-002. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
