Context:
Domain: cli-mcp-contracts-tooling
Candidate: DEBT-008
Raw source: lane:2#candidate-2
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-2.md

Technical-debt claim:
Choose strict or extensible semantics for ToolContext.meta_hints unknown keys

Evidence:
ToolContext.meta_hints is a write-back surface; Meta.extra allows unknown fields, but core._apply_hints only applies Meta.model_fields and silently drops others.

Carrying cost / risk:
Future tools/providers can set metadata that disappears silently.

Target paydown:
Pick strict rejection or extensible propagation and test fake custom meta_hints plus standard hints.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: design
- debt_class: type-schema-debt, integration-provider-drift
- priority: P2
- risk: medium
- confidence: high
- justification: Track=design; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- Unit/contract test for fake handler setting custom meta_hints plus standard hints
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Choose strict or extensible semantics for ToolContext.meta_hints unknown keys
- Paydown boundary followed: Pick strict rejection or extensible propagation and test fake custom meta_hints plus standard hints.
- Validation evidence: Unit/contract test for fake handler setting custom meta_hints plus standard hints
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-008 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-2.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-008.
