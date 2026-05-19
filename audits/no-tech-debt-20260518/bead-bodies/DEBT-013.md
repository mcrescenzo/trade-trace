Context:
Domain: storage-persistence-events-schema
Candidate: DEBT-013
Raw source: lane:3#candidate-3
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-3.md

Technical-debt claim:
Make FTS5 dependency explicit or gracefully optional for memory migrations

Evidence:
database.py has has_fts5 helper but migrations.py unconditionally CREATE VIRTUAL TABLE memory_node_fts USING fts5.

Carrying cost / risk:
SQLite builds without FTS5 cannot initialize/migrate; failure mode not clearly preflighted or documented.

Target paydown:
Choose required vs optional policy; fail early with clear error or provide degraded no-FTS behavior.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: investigation
- debt_class: ops-deploy-debt, migration-schema-debt
- priority: P2
- risk: medium
- confidence: high
- justification: Track=investigation; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- Migration test simulating FTS5 creation failure
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Make FTS5 dependency explicit or gracefully optional for memory migrations
- Paydown boundary followed: Choose required vs optional policy; fail early with clear error or provide degraded no-FTS behavior.
- Validation evidence: Migration test simulating FTS5 creation failure
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-013 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-3.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-013.
