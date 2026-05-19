Context:
Domain: storage-persistence-events-schema
Candidate: DEBT-012
Raw source: lane:3#candidate-2
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-3.md

Technical-debt claim:
Enforce or explicitly grandfather strategy_id references after strategies table exists

Evidence:
strategy_id columns were reserved pre-M3 with no FK; migration 007 creates strategies but no FK/triggers; tests assert arbitrary decision.strategy_id is allowed.

Carrying cost / risk:
Rows can reference nonexistent strategies, making strategy reports/links/orphan cleanup fragile.

Target paydown:
Decide strict FK, new-row triggers, or documented soft validation/orphan audit; test invalid/null/valid strategy_id.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.
- Do not alter public CLI/MCP semantics, migrate historical data, loosen security guarantees, or change product policy without an explicit design note and regression tests.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: design
- debt_class: migration-schema-debt, type-schema-debt
- priority: P2
- risk: medium
- confidence: high
- justification: Track=design; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_schema.py tests/integration/test_strategy_tools.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Enforce or explicitly grandfather strategy_id references after strategies table exists
- Paydown boundary followed: Decide strict FK, new-row triggers, or documented soft validation/orphan audit; test invalid/null/valid strategy_id.
- Validation evidence: python3 -m pytest -q tests/integration/test_schema.py tests/integration/test_strategy_tools.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-012 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-3.md.
- Compatibility/backfill/security blast radius is explicitly evaluated before implementation; if uncertain, stop at design/investigation output.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-012.
