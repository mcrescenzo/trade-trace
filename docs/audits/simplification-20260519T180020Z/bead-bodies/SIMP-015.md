Context:
Materialized from repo-simplification-review row SIMP-015 (DOCSIM-008) under epic trade-trace-mea1. Domain: docs. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Extend docs validation for anchors and canonical-source drift. Complexity class: contract-drift.

Evidence:
- tests/docs/test_markdown_links.py lines 36-42 strips anchors and only checks target files exist.
- Upcoming docs consolidation relies on section references and volatile generated facts that need stronger validation.

Why simplification is safe/desirable:
The target removes duplicated mechanics or contract-drift surface while preserving existing behavior. It is bounded to the cited files/surfaces and requires compatibility validation before close.

Target simplification:
Extend docs link tests to validate practical Markdown anchors and add small canonical-source drift checks for retained volatile facts.

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
- python -m pytest tests/docs/test_markdown_links.py
- Add allowlist only for intentional/generated anchors and document the exception.

Acceptance criteria:

- Simplification is limited to the cited bounded surface.
- Existing behavior and public contracts are preserved.
- Listed validation passes or any gap is explicitly resolved before close.
- No unrelated behavior change or broad rewrite lands under this bead.

Provenance:
Discovered by repo-simplification-review candidate SIMP-015 from source candidate(s) DOCSIM-008. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
