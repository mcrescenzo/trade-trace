Context:
Domain: storage-persistence-events-schema
Candidate: DEBT-016
Raw source: lane:3#candidate-6
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-3.md

Technical-debt claim:
Validate polymorphic edge endpoints and audit orphan edges

Evidence:
edges table stores source_kind/source_id/target_kind/target_id with enum checks but no endpoint existence FK/triggers; reports/traversals can silently drop orphan edges.

Carrying cost / risk:
Memory/source/playbook graph integrity can drift as endpoint kinds expand.

Target paydown:
Add write-tool endpoint validation and/or orphan-edge audit; consider DB triggers for core endpoint kinds.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.
- Do not alter public CLI/MCP semantics, migrate historical data, loosen security guarantees, or change product policy without an explicit design note and regression tests.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: design
- debt_class: state-persistence-debt, type-schema-debt
- priority: P2
- risk: medium
- confidence: high
- justification: Track=design; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- Tests for valid/invalid edge endpoints and orphan-edge audit query
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Validate polymorphic edge endpoints and audit orphan edges
- Paydown boundary followed: Add write-tool endpoint validation and/or orphan-edge audit; consider DB triggers for core endpoint kinds.
- Validation evidence: Tests for valid/invalid edge endpoints and orphan-edge audit query
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-016 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-3.md.
- Compatibility/backfill/security blast radius is explicitly evaluated before implementation; if uncertain, stop at design/investigation output.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-016.
