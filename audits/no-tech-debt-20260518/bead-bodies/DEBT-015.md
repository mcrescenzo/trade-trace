Context:
Domain: storage-persistence-events-schema
Candidate: DEBT-015
Raw source: lane:3#candidate-5
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-3.md

Technical-debt claim:
Add schema/meta consistency checks for migration recovery

Evidence:
Migrations are version-gated and transaction-wrapped, but later DDL steps are not reentrant; stale/lost meta.schema_version can fail on existing objects.

Carrying cost / risk:
Manual recovery/out-of-band corruption yields opaque DDL failures instead of actionable repair path.

Target paydown:
Add schema audit before migration or defensively detect schema/meta mismatch with clear guidance.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: investigation
- debt_class: migration-schema-debt, ops-deploy-debt
- priority: P3
- risk: low
- confidence: medium
- justification: Track=investigation; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- Add migration recovery tests with stale meta and partially existing objects
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Add schema/meta consistency checks for migration recovery
- Paydown boundary followed: Add schema audit before migration or defensively detect schema/meta mismatch with clear guidance.
- Validation evidence: Add migration recovery tests with stale meta and partially existing objects
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-015 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-3.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-015.
