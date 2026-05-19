Context:
Domain: domain-tools-ledger-memory-playbook
Candidate: DEBT-018
Raw source: lane:4#DTLMP-002
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-4.md

Technical-debt claim:
Reconcile memory.reflect docs/API shape with implementation

Evidence:
Code requires target_kind/target_id/body and creates only about edge; README uses target object + insight; PRD/memory-layer advertise derived_from/supports/contradicts/supersedes sugar.

Carrying cost / risk:
Agents following docs receive validation errors; future schema derivation may fossilize wrong surface.

Target paydown:
Either implement compatibility aliases/edge sugar or update docs/examples; add tests replaying README/PRD examples.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: docs-contract-drift, integration-provider-drift
- priority: P2
- risk: medium
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- Contract tests for README/PRD memory.reflect examples through dispatch
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Reconcile memory.reflect docs/API shape with implementation
- Paydown boundary followed: Either implement compatibility aliases/edge sugar or update docs/examples; add tests replaying README/PRD examples.
- Validation evidence: Contract tests for README/PRD memory.reflect examples through dispatch
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-018 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-4.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-018.
