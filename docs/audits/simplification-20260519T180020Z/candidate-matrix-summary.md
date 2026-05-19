# Trade Trace exhaustive simplification review — report-only fallback

This artifact is temporary because repo/Beads truth changed materially after lane discovery. No simplification candidate beads were materialized after the moving-target detection.

Root epic already created before detection: trade-trace-mea1.

## Matrix rows
- SIMP-001 [accept-merged/task] Centralize CLI and dispatcher error-envelope construction — Would materialize if stable; behavior contract needs exact ErrorEnvelope field/status equivalence.
- SIMP-002 [defer/investigation] Evaluate declarative registration tables for simple tool families — Too likely to become over-abstraction; keep as artifact-only lead.
- SIMP-003 [accept-as-investigation/investigation] Split monolithic SQLite migrations into versioned modules without changing schema — High-risk/L-sized; requires schema equivalence harness before refactor.
- SIMP-004 [accept-as-investigation/investigation] Centralize schema-governed enum and timestamp registries without weakening explicit audits — High-risk safety-boundary registry duplication; inventory/decision first.
- SIMP-005 [defer/investigation] Decide whether public model stubs are stable DTOs, generated schemas, or deprecation candidates — Needs product/API compatibility decision.
- SIMP-006 [accept-merged/task] Extract small shared report-row and result helpers where report semantics already match — Only exact common substrate; no report hierarchy.
- SIMP-007 [accept/task] Co-locate or auto-register report filter support declarations to reduce drift — Specific contract-drift simplification.
- SIMP-008 [accept/task] Centralize repeated test home and MCP/CLI fixtures without reducing isolation — Split from security no-network fixture after advisor.
- SIMP-009 [accept/task] Add explicit test data builders for direct-SQL and MCP ledger setup — Keep direct SQL where intentional.
- SIMP-010 [defer/task] Reduce dogfood/report test coupling without losing coverage — Lower leverage until broader test-support work lands.
- SIMP-011 [accept-merged/task] Single-source MCP setup docs and tool-registry discovery guidance — Docs source-of-truth simplification.
- SIMP-012 [accept-tightened/task] Tightly de-duplicate AGENTS.md and CLAUDE.md without changing session policy — Advisor: no policy change; preserve trade-trace-9zy substance and generated block integrity.
- SIMP-013 [accept-as-investigation/investigation] Simplify release maintenance by single-sourcing quality gates and package version — Release-sensitive; investigation-first.
- SIMP-014 [accept-as-investigation/investigation] Separate current capability status from design-only architecture docs — Needs docs taxonomy/current-vs-design decision.
- SIMP-015 [accept/task] Extend docs validation for anchors and canonical-source drift — Small validation enabler.
- SIMP-016A [accept/task] Centralize credential and secret-key vocabulary for MCP and credential audits — Direct constants/vocabulary task only.
- SIMP-016B [accept-as-investigation/investigation] Investigate replacing exporter secret-scanning private alias with a public security adapter — Advisor downgraded until golden scan corpus exists.
- SIMP-017 [reject/none] Intentional complexity guardrails: keep public facades and avoid broad report hierarchy — Intentional public facades/local report metrics; no work.
- SIMP-018 [accept/task] Consolidate duplicated no-network pytest fixtures with explicit coverage variants — Security-boundary test helper split from SIMP-008.
- SIMP-019 [accept/task] Extract light schema/table audit helpers for security tests without hiding assertions — Security assertion mechanics only; do not merge test meanings.
