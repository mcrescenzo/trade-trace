Context:
Materialized from repo-simplification-review row SIMP-014 (DOCSIM-006 + DOCSIM-007) under epic trade-trace-mea1. Domain: docs. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Investigate separating current capability status from design-only architecture docs. Complexity class: contract-drift.

Evidence:
- README.md has conflicting shipped/deferred capability prose across sections for imports, reports, review.bundle, and semantic recall.
- docs/architecture/http-sse-subscribe.md is explicitly proposed/not implemented while README/MCP setup docs say stdio-only; PRD lists HTTP/SSE as P1.

Why this is investigation/design-first:
The candidate touches behavior-sensitive or high-risk surfaces. The first deliverable is characterization/findings and a safe downstream plan, not refactor implementation.

Target simplification:
Investigation/design only: define docs taxonomy/status markers for current user-facing capability vs design/archive material before broad docs moves.

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
- Close with a current-vs-design documentation decision and list of docs to move/update.

Acceptance criteria:

- Findings/decision record documents exact current behavior, risks, and whether downstream implementation should be created.
- No implementation refactor is performed unless behavior characterization and validation commands are explicit.
- Any proposed follow-up tasks reference this bead and include concrete validation.

Provenance:
Discovered by repo-simplification-review candidate SIMP-014 from source candidate(s) DOCSIM-006 + DOCSIM-007. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
