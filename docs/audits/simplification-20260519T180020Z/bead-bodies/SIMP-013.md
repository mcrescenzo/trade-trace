Context:
Materialized from repo-simplification-review row SIMP-013 (DOCSIM-004 + DOCSIM-005) under epic trade-trace-mea1. Domain: packaging. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Investigate single-sourcing release quality gates and package version. Complexity class: duplicate-logic.

Evidence:
- .github/workflows/ci.yml and .github/workflows/workflow.yml repeat install, ruff, mypy, and pytest quality gate steps; ci.yml explicitly notes publish duplicates the gate as safety net.
- pyproject.toml and src/trade_trace/version.py both hold 0.0.1rc2, and publish workflow has a custom tag/version consistency check.

Why this is investigation/design-first:
The candidate touches behavior-sensitive or high-risk surfaces. The first deliverable is characterization/findings and a safe downstream plan, not refactor implementation.

Target simplification:
Investigation/design only: choose reusable workflow/script and single version source without weakening publish safety.

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
- python -m build --sdist --wheel
- ruff check src tests && mypy src && pytest
- Close with a release-safety decision covering tag/version/wheel metadata checks.

Acceptance criteria:

- Findings/decision record documents exact current behavior, risks, and whether downstream implementation should be created.
- No implementation refactor is performed unless behavior characterization and validation commands are explicit.
- Any proposed follow-up tasks reference this bead and include concrete validation.

Provenance:
Discovered by repo-simplification-review candidate SIMP-013 from source candidate(s) DOCSIM-004 + DOCSIM-005. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
