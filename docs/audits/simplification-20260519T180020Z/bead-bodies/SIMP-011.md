Context:
Materialized from repo-simplification-review row SIMP-011 (DOCSIM-001 + DOCSIM-003) under epic trade-trace-mea1. Domain: docs. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Single-source MCP setup docs and tool-registry discovery guidance. Complexity class: duplicate-logic.

Evidence:
- README.md, docs/AI_AGENT_MCP_GETTING_STARTED.md, docs/CLAUDE_CODE.md, docs/CLAUDE_DESKTOP.md, docs/IDE_MCP_SETUP.md, and docs/AGENT_GUIDE.md repeat install, TRADE_TRACE_HOME, journal init, startup, and actor defaults.
- README.md hand-lists every tool while also saying tt tool schema is the source of truth.

Why simplification is safe/desirable:
The target removes duplicated mechanics or contract-drift surface while preserving existing behavior. It is bounded to the cited files/surfaces and requires compatibility validation before close.

Target simplification:
Create one canonical MCP setup source and replace high-churn repeated setup/tool-registry lists with links, representative categories, and tt tool schema guidance.

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
- Manual docs readback for README and each client setup doc; run tt tool schema if available to verify source-of-truth wording.

Acceptance criteria:

- Simplification is limited to the cited bounded surface.
- Existing behavior and public contracts are preserved.
- Listed validation passes or any gap is explicitly resolved before close.
- No unrelated behavior change or broad rewrite lands under this bead.

Provenance:
Discovered by repo-simplification-review candidate SIMP-011 from source candidate(s) DOCSIM-001 + DOCSIM-003. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
