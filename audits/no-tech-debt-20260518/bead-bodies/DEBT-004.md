Context:
Domain: docs-contract-truth
Candidate: DEBT-004
Raw source: lane:1#docs-contract-truth-001
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-1.md

Technical-debt claim:
Fix broken relative links across README, PRD, and architecture docs

Evidence:
Lane link checker found README links to ./VISION.md and ./PRD.md though actual files live under docs/, PRD links to ./docs/architecture/* resolving to docs/docs/*, and architecture docs use ../../PRD.md/../../VISION.md.

Carrying cost / risk:
Users/agents get broken setup/design links; docs drift is rediscovered during audits.

Target paydown:
Correct relative links and add a lightweight markdown link check.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: docs-contract-drift
- priority: P2
- risk: medium
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 <markdown link checker> over README.md docs/**/*.md
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Fix broken relative links across README, PRD, and architecture docs
- Paydown boundary followed: Correct relative links and add a lightweight markdown link check.
- Validation evidence: python3 <markdown link checker> over README.md docs/**/*.md
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-004 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-1.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-004.
