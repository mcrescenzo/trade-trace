Context:
Domain: docs-contract-truth
Candidate: DEBT-005
Raw source: lane:1#docs-contract-truth-002 + lane:0#agent-doc-contract-drift-003
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-1.md

Technical-debt claim:
Scope AGENTS/CLAUDE session-close rules for read-only and no-push workflows

Evidence:
AGENTS.md/CLAUDE.md mandate filing issues, bd dolt push, git push, and “never stop before pushing” for every session, conflicting with legitimate read-only/no-Beads/no-push delegated lanes.

Carrying cost / risk:
Agents may mutate Beads or push from read-only audits; workflow contract conflict creates safety and coordination risk.

Target paydown:
Amend agent docs to preserve mandatory push for authorized mutating work while explicitly exempting read-only/no-push/delegated audit lanes.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: docs-contract-drift, config-drift
- priority: P2
- risk: medium
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- Manual readback of AGENTS.md and CLAUDE.md; simulate mutating vs read-only workflow interpretation
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Scope AGENTS/CLAUDE session-close rules for read-only and no-push workflows
- Paydown boundary followed: Amend agent docs to preserve mandatory push for authorized mutating work while explicitly exempting read-only/no-push/delegated audit lanes.
- Validation evidence: Manual readback of AGENTS.md and CLAUDE.md; simulate mutating vs read-only workflow interpretation
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-005 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-1.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-005.
